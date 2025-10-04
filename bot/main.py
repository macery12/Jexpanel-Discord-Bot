from __future__ import annotations
import asyncio, structlog, aiohttp, discord
from discord.ext import commands, tasks
from .config import settings
from .db import init_db, SessionLocal
from .client.ptero_app import PteroApp
from .services.credentials import purge_old_credentials

log = structlog.get_logger()

INTENTS = discord.Intents.none()
INTENTS.guilds = True
INTENTS.members = True

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=INTENTS)
        self.http_session: aiohttp.ClientSession | None = None
        self.app_client: PteroApp | None = None
        self.purge_loop.start()

    async def setup_hook(self) -> None:
        await init_db()
        self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        if settings.app_api_key:
            self.app_client = PteroApp(self.http_session)

        await self.load_extension("bot.cogs.keys")
        await self.load_extension("bot.cogs.server")
        await self.load_extension("bot.cogs.admin")
        await self.load_extension("bot.cogs.app_admin")

        if settings.command_sync_scope == "dev" and settings.discord_guild_id:
            guild = discord.Object(id=settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("commands_synced", scope="dev", guild=settings.discord_guild_id, count=len(synced))
        else:
            synced = await self.tree.sync()
            log.info("commands_synced", scope="global", count=len(synced))

    async def on_ready(self):
        log.info("bot_ready", user=str(self.user))

    async def close(self):
        if self.http_session:
            await self.http_session.close()
        await super().close()

    @tasks.loop(hours=24)
    async def purge_loop(self):
        try:
            async with SessionLocal() as s:
                removed = await purge_old_credentials(s, settings.cred_purge_days)
            log.info("purge_credentials", removed=removed, days=settings.cred_purge_days)
        except Exception as e:
            log.warning("purge_error", error=str(e))

    @purge_loop.before_loop
    async def before_purge(self):
        await self.wait_until_ready()

async def main():
    bot = Bot()
    async with bot:
        await bot.start(settings.discord_token)

if __name__ == "__main__":
    asyncio.run(main())
