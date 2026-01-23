from __future__ import annotations

import aiohttp
import discord
import structlog
from discord import app_commands
from discord.ext import commands

from ..client.ptero_rest import PteroClient
from ..core.permissions import has_admin_role
from ..db import SessionLocal
from ..services.credentials import (
    add_or_update_credential,
    delete_credential,
    list_user_credentials,
    set_default_credential,
    wipe_all_credentials,
    wipe_user_credentials,
)

log = structlog.get_logger()


async def validate_token(panel_url: str, token: str) -> bool:
    """Quick probe to ensure the user's Client token + panel are valid."""
    try:
        async with aiohttp.ClientSession() as sess:
            client = PteroClient(sess, panel_url, token)
            url = client.base.with_path("/api/client/account")
            async with sess.get(url, headers=client._headers()) as r:
                return r.status == 200
    except Exception:
        return False


class KeysCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="link", description="Link your Client API token (ephemeral).")
    @app_commands.describe(
        panel_url="Panel base URL (e.g., https://panel.example.com)",
        token="Client API token (kept encrypted)",
        label="Optional number label (1-9)",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def link(self, inter: discord.Interaction, panel_url: str, token: str, label: int | None = None):
        await inter.response.defer(ephemeral=True)
        try:
            if label is not None and (label < 1 or label > 9):
                await inter.followup.send("Label must be 1-9.", ephemeral=True)
                return
            ok = await validate_token(panel_url, token)
            if not ok:
                await inter.followup.send("Token validation failed. Check panel URL and token.", ephemeral=True)
                return
            async with SessionLocal() as s:
                cred = await add_or_update_credential(
                    s, inter.user.id, panel_url, token, label=str(label) if label else None
                )
            masked = "…" + cred.token_fingerprint
            await inter.followup.send(
                f"Linked **{panel_url}** as label **{cred.label or '-'}** (fp `{masked}`).",
                ephemeral=True,
            )
        except Exception as e:
            log.error("link_command_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to save credentials. Please contact an administrator.\n"
                f"Error: {type(e).__name__}",
                ephemeral=True
            )

    @app_commands.command(name="keys_list", description="List your linked keys.")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def keys_list(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True)
        try:
            async with SessionLocal() as s:
                rows = await list_user_credentials(s, inter.user.id)
            if not rows:
                await inter.followup.send("You have no linked keys. Use `/link` to add one.", ephemeral=True)
                return
            lines: list[str] = []
            for r in rows:
                masked = "…" + r.token_fingerprint
                lines.append(
                    f"• `{r.panel_url}` — label `{r.label or '-'}` — default: {'yes' if r.is_default else 'no'} — last_used: {r.last_used_at or '-'} — fp `{masked}`"
                )
            await inter.followup.send("\n".join(lines), ephemeral=True)
        except Exception as e:
            log.error("keys_list_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to retrieve credentials.\nError: {type(e).__name__}",
                ephemeral=True
            )

    @app_commands.command(name="keys_set_default", description="Set your default key for a panel.")
    @app_commands.describe(panel_url="Panel URL", label="Label (1-9)")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def keys_set_default(self, inter: discord.Interaction, panel_url: str, label: int):
        await inter.response.defer(ephemeral=True)
        try:
            async with SessionLocal() as s:
                changed = await set_default_credential(s, inter.user.id, panel_url, str(label))
            if changed:
                await inter.followup.send(f"Default set to label `{label}` for `{panel_url}`.", ephemeral=True)
            else:
                await inter.followup.send("No such key for that label/panel.", ephemeral=True)
        except Exception as e:
            log.error("keys_set_default_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to update default key.\nError: {type(e).__name__}",
                ephemeral=True
            )

    @app_commands.command(name="unlink", description="Remove one of your keys (or the default if label omitted).")
    @app_commands.describe(panel_url="Panel URL", label="Optional label to remove")
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def unlink(self, inter: discord.Interaction, panel_url: str, label: int | None = None):
        await inter.response.defer(ephemeral=True)
        try:
            async with SessionLocal() as s:
                removed = await delete_credential(s, inter.user.id, panel_url, str(label) if label else None)
            if removed:
                await inter.followup.send("Removed.", ephemeral=True)
            else:
                await inter.followup.send("No matching key found.", ephemeral=True)
        except Exception as e:
            log.error("unlink_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to remove credential.\nError: {type(e).__name__}",
                ephemeral=True
            )

    @app_commands.command(name="keys_wipe_mine", description='Delete ALL your keys (type "CONFIRM").')
    @app_commands.describe(confirm='Type exactly "CONFIRM" to proceed')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def keys_wipe_mine(self, inter: discord.Interaction, confirm: str):
        await inter.response.defer(ephemeral=True)
        if confirm != "CONFIRM":
            await inter.followup.send("Cancelled.", ephemeral=True)
            return
        try:
            async with SessionLocal() as s:
                count = await wipe_user_credentials(s, inter.user.id)
            await inter.followup.send(f"Wiped {count} key(s) from your account.", ephemeral=True)
        except Exception as e:
            log.error("keys_wipe_mine_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to wipe credentials.\nError: {type(e).__name__}",
                ephemeral=True
            )

    @app_commands.command(name="keys_wipe_all", description='(Admin) Delete ALL keys (type "CONFIRM").')
    @app_commands.describe(confirm='Type exactly "CONFIRM" to proceed')
    async def keys_wipe_all(self, inter: discord.Interaction, confirm: str):
        if not has_admin_role(inter):
            await inter.response.send_message("You don't have permission.", ephemeral=True)
            return
        await inter.response.defer(ephemeral=True)
        if confirm != "CONFIRM":
            await inter.followup.send("Cancelled.", ephemeral=True)
            return
        try:
            async with SessionLocal() as s:
                count = await wipe_all_credentials(s)
            await inter.followup.send(f"Wiped ALL keys: {count} removed.", ephemeral=True)
        except Exception as e:
            log.error("keys_wipe_all_error", user_id=inter.user.id, error=str(e), error_type=type(e).__name__)
            await inter.followup.send(
                f"❌ Failed to wipe all credentials.\nError: {type(e).__name__}",
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(KeysCog(bot))
