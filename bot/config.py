from __future__ import annotations
import base64
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Discord & sync
    discord_token: str = Field(alias="DISCORD_TOKEN")
    discord_guild_id: int | None = Field(default=None, alias="DISCORD_GUILD_ID")
    command_sync_scope: str = Field(default="dev", alias="COMMAND_SYNC_SCOPE")

    # Panel (app admin only)
    panel_url: str = Field(alias="PTERO_PANEL_URL")
    client_api_key: str | None = Field(default=None, alias="PTERO_CLIENT_API_KEY")  # now optional
    app_api_key: str | None = Field(default=None, alias="PTERO_APP_API_KEY")

    # Admin gating
    admin_role_ids: list[int] = Field(default_factory=list, alias="ADMIN_ROLE_IDS")
    log_channel_id: int | None = Field(default=None, alias="LOG_CHANNEL_ID")
    alert_channel_id: int | None = Field(default=None, alias="ALERT_CHANNEL_ID")

    # Storage & crypto
    database_url: str = Field(default="sqlite+aiosqlite:///./bot.db", alias="DATABASE_URL")
    bot_data_key_b64: str = Field(alias="ENCRYPTION_KEY")  # renamed from BOT_DATA_KEY
    data_key_version: int = Field(default=1, alias="DATA_KEY_VERSION")
    cred_purge_days: int = Field(default=7, alias="CRED_PURGE_DAYS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("discord_guild_id", mode="before")
    @classmethod
    def parse_guild_id(cls, v):
        if v is None: return None
        s = str(v).strip()
        if not s: return None
        try: return int(s)
        except ValueError: return None

    @field_validator("admin_role_ids", mode="before")
    @classmethod
    def parse_admin_roles(cls, v):
        if v in (None, ""): return []
        if isinstance(v, list): return [int(x) for x in v]
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        out: list[int] = []
        for p in parts:
            try: out.append(int(p))
            except ValueError: continue
        return out

    @property
    def bot_data_key(self) -> bytes:
        raw = self.bot_data_key_b64.strip()
        if not raw:
            raise ValueError("ENCRYPTION_KEY is required (base64, 32 bytes).")
        key = base64.b64decode(raw)
        if len(key) != 32:
            raise ValueError("ENCRYPTION_KEY must decode to exactly 32 bytes.")
        return key

settings = Settings()
