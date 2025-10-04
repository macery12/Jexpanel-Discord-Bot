from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..core.permissions import has_admin_role
from ..client.ptero_app import PteroApp


class AppAdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot, app: PteroApp | None):
        self.bot = bot
        self.app = app

    def require_app(self) -> PteroApp:
        if not self.app:
            raise RuntimeError("APP API key not configured")
        return self.app

    @app_commands.command(name="panel_nodes", description="List nodes (Application API, admin-only).")
    async def panel_nodes(self, inter: discord.Interaction):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        app = self.require_app()
        nodes = await app.list_nodes()
        if not nodes:
            await inter.followup.send("No nodes found.", ephemeral=True)
            return
        lines = [f"• **{n.get('name','node')}** (id={n.get('id','?')}) — {n.get('fqdn','')}" for n in nodes[:25]]
        await inter.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(name="panel_allocations", description="List allocations for a node (admin-only).")
    @app_commands.describe(node_id="Numeric node id")
    async def panel_allocations(self, inter: discord.Interaction, node_id: int):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        app = self.require_app()
        allocs = await app.list_allocations(node_id)
        if not allocs:
            await inter.followup.send("No allocations found.", ephemeral=True)
            return
        lines = [
            f"{a.get('ip_alias') or a.get('ip')}:{a.get('port')} — {'assigned' if a.get('assigned') else 'free'}"
            for a in allocs[:25]
        ]
        await inter.followup.send("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot):
    app: PteroApp | None = getattr(bot, "app_client", None)
    await bot.add_cog(AppAdminCog(bot, app))
