"""Spark profiler analysis cog for Discord bot."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..utils.spark import analyze_spark_report, format_discord_report


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


async def setup(bot: commands.Bot):
    """Load the Spark cog."""
    await bot.add_cog(SparkCog(bot))
