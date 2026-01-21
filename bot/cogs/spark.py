"""Spark profiler analysis cog for Discord bot."""

from __future__ import annotations

import asyncio
import re

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from ..client.ptero_rest import PteroClient
from ..client.ptero_ws import fetch_recent_logs, send_console_command
from ..config import settings
from ..db import SessionLocal
from ..db.models import UserCredential
from ..utils.spark import analyze_spark_report, format_discord_report


async def get_user_token_for_panel(user_id: int, panel_url: str) -> str | None:
    """Get user's API token for a specific panel."""
    async with SessionLocal() as s:
        from ..services.credentials import get_user_token
        return await get_user_token(s, user_id, panel_url)


async def resolve_identifier_and_panel(
    user_id: int, value: str
) -> tuple[str | None, str | None]:
    """
    Resolve a server identifier (alias, UUID, or name) to a UUID and panel URL.
    
    Resolution order:
    1. Check if it's an alias (user-specific, then global)
    2. Check if it's a full UUID
    3. Search by partial UUID or server name across all user's panels
    
    Args:
        user_id: Discord user ID
        value: Server identifier (alias, UUID, or name)
    
    Returns:
        Tuple of (uuid, panel_url) or (None, None) if not found
    """
    from ..core.permissions import SERVER_UUID_RE
    
    val = value.strip()
    
    # Step 1: Check if it's an alias (user-specific first, then global)
    async with SessionLocal() as s:
        from ..services.alias import get_alias
        alias = await get_alias(s, val, user_id)
        if alias:
            if alias.panel_url:
                return (alias.uuid, alias.panel_url)
            uuid_from_alias = alias.uuid
        else:
            uuid_from_alias = None
    
    # Step 2: Check if it's a full UUID
    if SERVER_UUID_RE.match(val):
        # Try to find which panel this UUID belongs to
        async with SessionLocal() as s:
            result = await s.execute(
                select(UserCredential.panel_url).where(UserCredential.discord_user_id == user_id)
            )
            panels = sorted({row[0] for row in result.all()})
        
        # Check each panel for the UUID
        async with aiohttp.ClientSession() as sess:
            for panel_url in panels:
                tok = await get_user_token_for_panel(user_id, panel_url)
                if not tok:
                    continue
                try:
                    cli = PteroClient(sess, panel_url, tok)
                    await cli.server_details(val)  # If this succeeds, the UUID exists on this panel
                    return (val, panel_url)
                except Exception:
                    continue
        
        return (None, None)
    
    # Step 3: Search by partial UUID or server name
    if uuid_from_alias:
        # If we have an alias without a panel, search for it
        async with SessionLocal() as s:
            result = await s.execute(
                select(UserCredential.panel_url).where(UserCredential.discord_user_id == user_id)
            )
            panels = sorted({row[0] for row in result.all()})
        
        async with aiohttp.ClientSession() as sess:
            for panel_url in panels:
                tok = await get_user_token_for_panel(user_id, panel_url)
                if not tok:
                    continue
                try:
                    cli = PteroClient(sess, panel_url, tok)
                    await cli.server_details(uuid_from_alias)
                    return (uuid_from_alias, panel_url)
                except Exception:
                    continue
    
    # Search across all panels
    async with SessionLocal() as s:
        result = await s.execute(
            select(UserCredential.panel_url).where(UserCredential.discord_user_id == user_id)
        )
        panels = sorted({row[0] for row in result.all()})
    
    async with aiohttp.ClientSession() as sess:
        for panel_url in panels:
            tok = await get_user_token_for_panel(user_id, panel_url)
            if not tok:
                continue
            try:
                cli = PteroClient(sess, panel_url, tok)
                servers = await cli.list_servers()
                
                for srv in servers:
                    uuid = srv.get("identifier", "")
                    name = srv.get("name", "")
                    
                    # Match by partial UUID or name (case-insensitive)
                    if val.lower() in uuid.lower() or val.lower() in name.lower():
                        return (uuid, panel_url)
            except Exception:
                continue
    
    return (None, None)


class SparkCog(commands.Cog):
    """Cog for analyzing Spark profiler reports."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="spark",
        description="Analyze a Minecraft Spark profiler report for performance issues"
    )
    @app_commands.describe(url="The Spark profiler report URL (e.g., https://spark.lucko.me/...)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def spark_analyze(self, interaction: discord.Interaction, url: str):
        """Analyze a Spark profiler report and display performance diagnostics.
        
        Args:
            interaction: Discord interaction
            url: Spark profiler report URL
        """
        # Defer response as analysis may take a moment
        await interaction.response.defer()
        
        try:
            # Analyze the report
            result = await analyze_spark_report(url)
            
            # Format for Discord
            message = format_discord_report(result)
            
            # Send the analysis
            await interaction.followup.send(message)
            
        except ValueError as e:
            # Handle errors (invalid URL, fetch failures, etc.)
            error_message = f"❌ **Error analyzing Spark report:**\n{e!s}"
            await interaction.followup.send(error_message, ephemeral=True)
        except Exception as e:
            # Handle unexpected errors
            error_message = f"❌ **Unexpected error:**\n{e!s}"
            await interaction.followup.send(error_message, ephemeral=True)

    @app_commands.command(
        name="spark_auto",
        description="Automatically run Spark profiler on a server and analyze the results"
    )
    @app_commands.describe(server="Server UUID, name, or alias")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def spark_auto(self, interaction: discord.Interaction, server: str):
        """Automatically profile a server and analyze the Spark report.
        
        This command:
        1. Sends the configured Spark command to the server
        2. Waits for the profiling to complete
        3. Fetches the server logs
        4. Extracts the Spark report URL from the logs
        5. Analyzes and displays the performance report
        
        Args:
            interaction: Discord interaction
            server: Server identifier (alias, UUID, or name)
        """
        # Defer response as this will take some time
        await interaction.response.defer()
        
        try:
            # Resolve server identifier to UUID and panel
            uuid, panel = await resolve_identifier_and_panel(interaction.user.id, server)
            if not uuid or not panel:
                await interaction.followup.send(
                    "❌ Server not found for your linked panels. "
                    "Try `/link` or specify the correct alias.",
                    ephemeral=True
                )
                return
            
            # Get user's API token
            token = await get_user_token_for_panel(interaction.user.id, panel)
            if not token:
                await interaction.followup.send(
                    "❌ No API key found for that panel. Use `/link` to add one.",
                    ephemeral=True
                )
                return
            
            # Get the spark command from config
            spark_command = settings.spark_auto_command
            
            # Extract timeout value from the command (default to 30 seconds)
            timeout_match = re.search(r'--timeout\s+(\d+)', spark_command)
            timeout = int(timeout_match.group(1)) if timeout_match else 30
            
            # Send initial status message
            await interaction.followup.send(
                f"🔄 Starting Spark profiler on server...\n"
                f"⏱️ This will take approximately **{timeout} seconds**.\n"
                f"Command: `{spark_command}`"
            )
            
            # Get WebSocket info and send the command
            async with aiohttp.ClientSession() as sess:
                cli = PteroClient(sess, panel, token)
                ws_info = await cli.websocket_info(uuid)
                socket_url = ws_info["data"]["socket"]
                ws_token = ws_info["data"]["token"]
            
            # Send the Spark command to the server
            await send_console_command(socket_url, panel, ws_token, spark_command)
            
            # Wait for the profiling to complete (add a buffer of 5 seconds)
            await asyncio.sleep(timeout + 5)
            
            # Fetch logs to find the Spark URL
            async with aiohttp.ClientSession() as sess:
                cli = PteroClient(sess, panel, token)
                ws_info = await cli.websocket_info(uuid)
                socket_url = ws_info["data"]["socket"]
                ws_token = ws_info["data"]["token"]
            
            # Fetch recent logs (increase lines to ensure we catch the URL)
            logs = await fetch_recent_logs(
                socket_url, panel, ws_token, 
                max_lines=100, 
                total_timeout=3.0, 
                idle_timeout=0.5
            )
            
            if not logs:
                await interaction.followup.send(
                    "❌ No logs available after profiling. The server may not have responded.",
                    ephemeral=True
                )
                return
            
            # Search for Spark URL pattern in logs
            # Pattern: https://spark.lucko.me/XXXXXXXX
            spark_url_pattern = r'https?://spark\.lucko\.me/[a-zA-Z0-9]+'
            spark_url = None
            
            for log_line in reversed(logs):  # Start from the end (most recent)
                match = re.search(spark_url_pattern, log_line)
                if match:
                    spark_url = match.group(0)
                    break
            
            if not spark_url:
                # Send logs as fallback
                logs_text = "\n".join(logs[-30:])  # Last 30 lines
                await interaction.followup.send(
                    f"❌ Could not find Spark profiler URL in logs.\n"
                    f"Recent logs:\n```\n{logs_text[:1500]}\n```",
                    ephemeral=True
                )
                return
            
            # Found the Spark URL - now analyze it
            await interaction.followup.send(f"✅ Found Spark report: {spark_url}\n🔍 Analyzing...")
            
            # Analyze the report
            result = await analyze_spark_report(spark_url)
            
            # Format for Discord
            message = format_discord_report(result)
            
            # Send the analysis
            await interaction.followup.send(message)
            
        except ValueError as e:
            error_message = f"❌ **Error:**\n{e!s}"
            await interaction.followup.send(error_message, ephemeral=True)
        except Exception as e:
            error_message = f"❌ **Unexpected error:**\n{e!s}"
            await interaction.followup.send(error_message, ephemeral=True)


async def setup(bot: commands.Bot):
    """Load the Spark cog."""
    await bot.add_cog(SparkCog(bot))
