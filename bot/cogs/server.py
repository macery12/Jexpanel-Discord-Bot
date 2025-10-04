from __future__ import annotations

import io
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from ..db import SessionLocal
from ..db.models import ServerAlias, UserCredential
from ..core.permissions import SERVER_UUID_RE, has_admin_role
from ..client.ptero_rest import PteroClient
from ..client.ptero_ws import fetch_recent_logs, send_console_command


def _fmt_bytes(n: int | None) -> str:
    if not n:
        return "0 B"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    i = 0
    f = float(n)
    while f >= 1024.0 and i < len(units) - 1:
        f /= 1024.0
        i += 1
    if i >= 2:
        return f"{f:.2f} {units[i]}"
    return f"{f:.1f} {units[i]}"


def _fmt_gib_mib_pair(used_bytes: int, limit_mib: int | None) -> tuple[str, float | None]:
    used_s = _fmt_bytes(int(used_bytes or 0))
    if not limit_mib or limit_mib <= 0:
        return f"{used_s} / ∞", None
    limit_bytes = int(limit_mib) * 1024 * 1024
    lim_s = _fmt_bytes(limit_bytes)
    pct = (used_bytes / limit_bytes * 100.0) if limit_bytes > 0 else None
    return f"{used_s} / {lim_s} ({pct:.0f}%)", pct


def _fmt_uptime(ms: int | None) -> str:
    if not ms or ms <= 0:
        return "—"
    s = int(ms // 1000)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d: parts.append(f"{d}d")
    if h: parts.append(f"{h}h")
    if m: parts.append(f"{m}m")
    if not parts: parts.append(f"{s}s")
    return " ".join(parts)


async def list_user_panels(user_id: int):
    async with SessionLocal() as s:
        res = await s.execute(select(UserCredential.panel_url).where(UserCredential.discord_user_id == user_id))
        urls = sorted(set([row[0] for row in res.all()]))
        return urls


async def get_user_token_for_panel(user_id: int, panel_url: str) -> str | None:
    async with SessionLocal() as s:
        from ..services.credentials import get_user_token
        return await get_user_token(s, user_id, panel_url)


async def resolve_identifier_and_panel(user_id: int, value: str) -> tuple[str | None, str | None]:
    val = value.strip()
    if SERVER_UUID_RE.match(val):
        panels = await list_user_panels(user_id)
        if not panels:
            return (val, None)
        if len(panels) == 1:
            return (val, panels[0])
        import aiohttp
        for p in panels:
            tok = await get_user_token_for_panel(user_id, p)
            if not tok: continue
            async with aiohttp.ClientSession() as sess:
                cli = PteroClient(sess, p, tok)
                try:
                    await cli.server_details(val)
                    return (val, p)
                except Exception:
                    continue
        return (val, None)

    async with SessionLocal() as s:
        res = await s.execute(select(ServerAlias).where(ServerAlias.alias == val))
        alias = res.scalar_one_or_none()
        if alias:
            if alias.panel_url:
                return (alias.uuid, alias.panel_url)
            uuid_guess = alias.uuid
        else:
            uuid_guess = None

    panels = await list_user_panels(user_id)
    if not panels:
        return (None, None)
    import aiohttp
    for p in panels:
        tok = await get_user_token_for_panel(user_id, p)
        if not tok: continue
        async with aiohttp.ClientSession() as sess:
            cli = PteroClient(sess, p, tok)
            try:
                servers = await cli.list_servers()
                needle = val.lower()
                for srv in servers:
                    if uuid_guess and srv.get("uuid") == uuid_guess:
                        return (srv["uuid"], p)
                    uuid = srv.get("uuid","")
                    name = srv.get("name","")
                    if uuid.startswith(val) or needle in name.lower():
                        return (uuid, p)
            except Exception:
                continue
    return (None, None)


class ServerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="list", description="List your Pterodactyl servers.")
    @app_commands.describe(filter="Filter by name or UUID prefix", panel_url="Filter by a specific panel URL (optional)")
    async def server_list(self, inter: discord.Interaction, filter: str | None = None, panel_url: str | None = None):
        await inter.response.defer(ephemeral=True)
        panels = [panel_url] if panel_url else await list_user_panels(inter.user.id)
        if not panels:
            await inter.followup.send("You have no linked keys. Use `/link` first.", ephemeral=True)
            return
        lines = []
        import aiohttp
        for p in panels:
            tok = await get_user_token_for_panel(inter.user.id, p)
            if not tok: 
                continue
            async with aiohttp.ClientSession() as sess:
                cli = PteroClient(sess, p, tok)
                try:
                    servers = await cli.list_servers()
                except Exception:
                    continue
                if filter:
                    f = filter.lower().strip()
                    servers = [s for s in servers if f in s.get("name","").lower() or s.get("uuid","").startswith(filter)]
                for s in servers[:25]:
                    lines.append(f"• **{s.get('name','(unknown)')}** — `{s.get('uuid','?')}` — _{p}_")
        if not lines:
            await inter.followup.send("No servers found.", ephemeral=True); return
        await inter.followup.send("\n".join(lines[:25]), ephemeral=True)

    @app_commands.command(name="status", description="Show power + live stats for a server (using your key).")
    @app_commands.describe(server="Alias, partial, or full UUID.")
    async def server_status(self, inter: discord.Interaction, server: str):
        await inter.response.defer(ephemeral=True)
        uuid, panel = await resolve_identifier_and_panel(inter.user.id, server)
        if not uuid or not panel:
            await inter.followup.send("Server not found for your linked panels. Try `/link` or specify the correct alias.", ephemeral=True)
            return
        tok = await get_user_token_for_panel(inter.user.id, panel)
        if not tok:
            await inter.followup.send("No key for that panel. Use `/link`.", ephemeral=True); return

        import aiohttp
        async with aiohttp.ClientSession() as sess:
            cli = PteroClient(sess, panel, tok)
            details = await cli.server_details(uuid)
            res = await cli.server_resources(uuid)
            try:
                backups = await cli.list_backups(uuid)
                backups_used = len(backups)
            except Exception:
                backups_used = 0

        attrs = details
        limits = attrs.get("limits", {}) or {}
        features = attrs.get("feature_limits", {}) or {}
        sftp = (attrs.get("sftp_details") or {})
        sftp_host = sftp.get("ip")
        sftp_port = sftp.get("port")

        r = res.get("resources") or {}
        cpu_now = float(r.get("cpu_absolute") or 0.0)
        mem_used = int(r.get("memory_bytes") or 0)
        disk_used = int(r.get("disk_bytes") or 0)
        rx = int(r.get("network_rx_bytes") or r.get("rx_bytes") or 0)
        tx = int(r.get("network_tx_bytes") or r.get("tx_bytes") or 0)
        uptime_ms = int(r.get("uptime") or res.get("uptime") or 0)
        power = res.get("current_state") or res.get("state") or "unknown"
        suspended = bool(res.get("is_suspended"))

        cpu_limit = int(limits.get("cpu") or 0)
        cpu_limit_s = "Unlimited" if cpu_limit == 0 else f"{cpu_limit}%"
        def pair(used, limit): return _fmt_gib_mib_pair(used, limit)[0]
        mem_s = pair(mem_used, limits.get("memory"))
        disk_s = pair(disk_used, limits.get("disk"))
        net_s = f"RX {_fmt_bytes(rx)} • TX {_fmt_bytes(tx)}"
        up_s = _fmt_uptime(uptime_ms)

        backups_limit = int(features.get("backups") or 0)
        backups_s = f"{backups_used}/{backups_limit or '∞'}" if backups_limit else f"{backups_used}/∞"

        docker_image = attrs.get("docker_image") or ""
        engine = docker_image.split(":")[-1] if ":" in docker_image else docker_image

        uuid_short = (attrs.get("uuid") or uuid)[:8]

        e = discord.Embed(title=f"{attrs.get('name','(unknown)')} — {uuid_short}")
        node = attrs.get("node")
        maint = attrs.get("is_node_under_maintenance")
        if node:
            value = f"{node}" + (" (maintenance)" if maint else "")
            e.add_field(name="Node", value=value, inline=True)
        e.add_field(name="Power", value=str(power), inline=True)
        e.add_field(name="Uptime", value=up_s, inline=True)
        e.add_field(name="Suspended", value="Yes" if suspended else "No", inline=True)
        e.add_field(name="CPU", value=f"{cpu_now:.1f}% / {cpu_limit_s}", inline=True)
        e.add_field(name="Memory", value=mem_s, inline=True)
        e.add_field(name="Disk", value=disk_s, inline=True)
        e.add_field(name="Network (since boot)", value=net_s, inline=False)
        e.add_field(name="Backups", value=backups_s, inline=True)
        e.add_field(name="Engine", value=engine or "—", inline=True)
        if sftp_host and sftp_port:
            e.add_field(name="SFTP", value=f"{sftp_host}:{sftp_port}", inline=False)

        await inter.followup.send(embed=e, ephemeral=True)

    @app_commands.command(name="logs", description="Tail recent console logs (fast, recent only; your key).")
    @app_commands.describe(server="Alias/UUID", lines="How many lines (default 50, max 200)")
    async def server_logs(self, inter: discord.Interaction, server: str, lines: int = 50):
        await inter.response.defer(ephemeral=True)
        uuid, panel = await resolve_identifier_and_panel(inter.user.id, server)
        if not uuid or not panel:
            await inter.followup.send("Server not found for your linked panels.", ephemeral=True); return
        tok = await get_user_token_for_panel(inter.user.id, panel)
        if not tok:
            await inter.followup.send("No key for that panel.", ephemeral=True); return

        lines = max(1, min(lines, 200))
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            cli = PteroClient(sess, panel, tok)
            info = await cli.websocket_info(uuid)
            token = info["data"]["token"]; socket = info["data"]["socket"]
        try:
            logs = await fetch_recent_logs(socket, panel, token, max_lines=lines, total_timeout=2.5, idle_timeout=0.4)
        except Exception as e:
            await inter.followup.send(f"WS error: {e}", ephemeral=True); return

        if not logs:
            await inter.followup.send("No logs available.", ephemeral=True); return
        text = "\n".join(logs)
        if len(text) > 1900:
            await inter.followup.send(file=discord.File(io.BytesIO(text.encode("utf-8")), filename="logs_tail.txt"), ephemeral=True)
        else:
            await inter.followup.send(f"```{text}```", ephemeral=True)

    @app_commands.command(name="console", description="Send a console command (admin-only; your key).")
    @app_commands.describe(server="Alias/UUID", command="Command to run")
    async def server_console(self, inter: discord.Interaction, server: str, command: str):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True); return
        await inter.response.defer(ephemeral=True)
        uuid, panel = await resolve_identifier_and_panel(inter.user.id, server)
        if not uuid or not panel:
            await inter.followup.send("Server not found for your linked panels.", ephemeral=True); return
        tok = await get_user_token_for_panel(inter.user.id, panel)
        if not tok:
            await inter.followup.send("No key for that panel.", ephemeral=True); return
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            cli = PteroClient(sess, panel, tok)
            info = await cli.websocket_info(uuid)
            try:
                await send_console_command(info["data"]["socket"], panel, info["data"]["token"], command)
            except Exception as e:
                await inter.followup.send(f"WS error: {e}", ephemeral=True); return
        await inter.followup.send("Command sent.", ephemeral=True)

    @app_commands.command(name="backups", description="List server backups (your key).")
    @app_commands.describe(server="Alias/UUID")
    async def server_backups(self, inter: discord.Interaction, server: str):
        await inter.response.defer(ephemeral=True)
        uuid, panel = await resolve_identifier_and_panel(inter.user.id, server)
        if not uuid or not panel:
            await inter.followup.send("Server not found for your linked panels.", ephemeral=True); return
        tok = await get_user_token_for_panel(inter.user.id, panel)
        if not tok:
            await inter.followup.send("No key for that panel.", ephemeral=True); return
        import aiohttp
        async with aiohttp.ClientSession() as sess:
            cli = PteroClient(sess, panel, tok)
            backups = await cli.list_backups(uuid)
        if not backups:
            await inter.followup.send("No backups found.", ephemeral=True); return
        lines = []
        for b in backups[:10]:
            size = b.get("bytes") or b.get("size") or 0
            size_mb = f"{(size or 0)/1024/1024:.1f} MiB"
            created = b.get("created_at") or b.get("createdAt") or "unknown"
            lines.append(f"• `{b.get('uuid','')[:8]}…` {b.get('name') or ''} — {size_mb} — {created}")
        await inter.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerCog(bot))
