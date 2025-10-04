from __future__ import annotations
import discord, traceback
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select
from ..core.permissions import has_admin_role, SERVER_UUID_RE
from ..db import SessionLocal
from ..db.models import ServerAlias

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="alias_set", description="Set an alias for a server UUID (optionally bind panel).")
    @app_commands.describe(uuid="Full server UUID", alias="Alias to assign", panel_url="Optional panel URL to speed up lookups")
    async def alias_set(self, inter: discord.Interaction, uuid: str, alias: str, panel_url: str | None = None):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        if not SERVER_UUID_RE.match(uuid):
            await inter.response.send_message("Invalid UUID format.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        try:
            async with SessionLocal() as s:
                row = await s.execute(select(ServerAlias).where(ServerAlias.alias == alias))
                existing = row.scalar_one_or_none()
                if existing:
                    existing.uuid = uuid
                    existing.panel_url = panel_url
                    await s.commit()
                else:
                    s.add(ServerAlias(alias=alias, uuid=uuid, panel_url=panel_url))
                    await s.commit()
            await inter.followup.send(f"Alias `{alias}` → `{uuid}` saved. Panel: `{panel_url or 'unspecified'}`", ephemeral=True)
        except Exception as e:
            msg = str(e)
            if len(msg) > 300:
                msg = msg[:300] + "…"
            await inter.followup.send(f"Alias save failed: `{msg}`", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
