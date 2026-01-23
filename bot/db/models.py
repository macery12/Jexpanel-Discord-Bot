from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

Base = declarative_base()

class GuildConfig(Base):
    __tablename__ = "guild_config"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[int] = mapped_column(Integer, index=True, unique=True)
    admin_role_ids: Mapped[str] = mapped_column(String, default="")
    log_channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    alert_channel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ServerAlias(Base):
    __tablename__ = "server_alias"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias: Mapped[str] = mapped_column(String(64), index=True)
    uuid: Mapped[str] = mapped_column(String(36), index=True)
    panel_url: Mapped[str | None] = mapped_column(String, nullable=True)
    discord_user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        # Unique constraint for user-specific aliases (alias + user_id must be unique)
        # For global aliases (discord_user_id IS NULL), we want alias to be globally unique
        # This is handled in the service layer since SQL unique constraints treat NULL specially
        UniqueConstraint("alias", "discord_user_id", name="uq_alias_user"),
    )

class UserCredential(Base):
    __tablename__ = "user_credentials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    panel_url: Mapped[str] = mapped_column(String, index=True)
    label: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ciphertext_b64: Mapped[str] = mapped_column(String)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    token_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("discord_user_id", "panel_url", "label", name="uq_user_panel_label"),
    )
