from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..core.permissions import SERVER_UUID_RE, has_admin_role
from ..db import SessionLocal


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="alias_set",
        description="Set a global alias for a server UUID (admin-only, visible to all).",
    )
    @app_commands.describe(
        uuid="Full server UUID",
        alias="Alias to assign",
        panel_url="Optional panel URL to speed up lookups",
    )
    async def alias_set(
        self, inter: discord.Interaction, uuid: str, alias: str, panel_url: str | None = None
    ):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        if not SERVER_UUID_RE.match(uuid):
            await inter.response.send_message("Invalid UUID format.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        try:
            async with SessionLocal() as s:
                from ..services.alias import create_or_update_alias
                
                # Create global alias (user_id=None)
                await create_or_update_alias(
                    s, alias=alias, uuid=uuid, panel_url=panel_url, user_id=None
                )
                await s.commit()
            await inter.followup.send(
                f"✅ Global alias `{alias}` → `{uuid}` saved. "
                f"Panel: `{panel_url or 'unspecified'}`",
                ephemeral=True,
            )
        except Exception as e:
            msg = str(e)
            if len(msg) > 300:
                msg = msg[:300] + "…"
            await inter.followup.send(f"Alias save failed: `{msg}`", ephemeral=True)

    @app_commands.command(
        name="alias_list_global", description="List all global server aliases (admin-only)."
    )
    async def alias_list_global(self, inter: discord.Interaction):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        
        async with SessionLocal() as s:
            from ..services.alias import list_global_aliases
            
            aliases = await list_global_aliases(s)
        
        if not aliases:
            await inter.followup.send("No global aliases found.", ephemeral=True)
            return
        
        lines = ["**Global Server Aliases:**\n"]
        for a in aliases[:25]:
            panel_info = f" → `{a.panel_url}`" if a.panel_url else ""
            lines.append(f"• **`{a.alias}`** → `{a.uuid[:8]}...`{panel_info}")
        
        await inter.followup.send("\n".join(lines), ephemeral=True)

    @app_commands.command(
        name="alias_delete_global", description="Delete a global server alias (admin-only)."
    )
    @app_commands.describe(alias="The global alias to delete")
    async def alias_delete_global(self, inter: discord.Interaction, alias: str):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        
        async with SessionLocal() as s:
            from ..services.alias import delete_alias
            
            # Delete global alias (user_id=None)
            deleted = await delete_alias(s, alias, user_id=None)
            await s.commit()
        
        if deleted:
            await inter.followup.send(
                f"✅ Global alias **`{alias}`** has been deleted.", ephemeral=True
            )
        else:
            await inter.followup.send(
                f"❌ Global alias **`{alias}`** not found.", ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
