"""Initial database schema

Revision ID: 000_initial_schema
Revises: 
Create Date: 2026-01-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '000_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create guild_config table
    op.create_table(
        'guild_config',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('guild_id', sa.Integer(), nullable=False),
        sa.Column('admin_role_ids', sa.String(), nullable=False, server_default=''),
        sa.Column('log_channel_id', sa.Integer(), nullable=True),
        sa.Column('alert_channel_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('guild_id')
    )
    op.create_index(op.f('ix_guild_config_guild_id'), 'guild_config', ['guild_id'], unique=True)

    # Create server_alias table (without user-specific columns - those are added in 001_user_aliases)
    op.create_table(
        'server_alias',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('alias', sa.String(64), nullable=False),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('panel_url', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('alias', name='uq_alias')
    )
    op.create_index(op.f('ix_server_alias_alias'), 'server_alias', ['alias'], unique=False)
    op.create_index(op.f('ix_server_alias_uuid'), 'server_alias', ['uuid'], unique=False)

    # Create user_credentials table
    op.create_table(
        'user_credentials',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('discord_user_id', sa.BigInteger(), nullable=False),
        sa.Column('panel_url', sa.String(), nullable=False),
        sa.Column('label', sa.String(8), nullable=True),
        sa.Column('ciphertext_b64', sa.String(), nullable=False),
        sa.Column('key_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('token_fingerprint', sa.String(64), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked', sa.Boolean(), nullable=False, server_default='false'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('discord_user_id', 'panel_url', 'label', name='uq_user_panel_label')
    )
    op.create_index(op.f('ix_user_credentials_discord_user_id'), 'user_credentials', ['discord_user_id'], unique=False)
    op.create_index(op.f('ix_user_credentials_panel_url'), 'user_credentials', ['panel_url'], unique=False)
    op.create_index(op.f('ix_user_credentials_token_fingerprint'), 'user_credentials', ['token_fingerprint'], unique=False)


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_index(op.f('ix_user_credentials_token_fingerprint'), table_name='user_credentials')
    op.drop_index(op.f('ix_user_credentials_panel_url'), table_name='user_credentials')
    op.drop_index(op.f('ix_user_credentials_discord_user_id'), table_name='user_credentials')
    op.drop_table('user_credentials')
    
    op.drop_index(op.f('ix_server_alias_uuid'), table_name='server_alias')
    op.drop_index(op.f('ix_server_alias_alias'), table_name='server_alias')
    op.drop_table('server_alias')
    
    op.drop_index(op.f('ix_guild_config_guild_id'), table_name='guild_config')
    op.drop_table('guild_config')
