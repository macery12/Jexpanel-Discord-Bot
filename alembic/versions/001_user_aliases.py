"""Add user-specific aliases support

Revision ID: 001_user_aliases
Revises: 
Create Date: 2026-01-20 14:26:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_user_aliases'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add discord_user_id column to server_alias table
    # This supports both user-specific aliases (when set) and global aliases (when NULL)
    op.add_column('server_alias', sa.Column('discord_user_id', sa.BigInteger(), nullable=True))
    op.create_index(op.f('ix_server_alias_discord_user_id'), 'server_alias', ['discord_user_id'], unique=False)
    
    # Add created_at column
    op.add_column('server_alias', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False))
    
    # Drop old unique constraint
    op.drop_constraint('uq_alias', 'server_alias', type_='unique')
    
    # Add new unique constraint on (alias, discord_user_id)
    # This allows the same alias for different users while keeping user aliases unique
    op.create_unique_constraint('uq_alias_user', 'server_alias', ['alias', 'discord_user_id'])


def downgrade() -> None:
    # Remove new unique constraint
    op.drop_constraint('uq_alias_user', 'server_alias', type_='unique')
    
    # Restore old unique constraint
    op.create_unique_constraint('uq_alias', 'server_alias', ['alias'])
    
    # Remove created_at column
    op.drop_column('server_alias', 'created_at')
    
    # Remove discord_user_id column
    op.drop_index(op.f('ix_server_alias_discord_user_id'), table_name='server_alias')
    op.drop_column('server_alias', 'discord_user_id')
