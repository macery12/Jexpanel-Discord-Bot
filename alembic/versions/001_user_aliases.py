"""Add user-specific aliases support

Revision ID: 001_user_aliases
Revises: 
Create Date: 2026-01-20 14:26:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '001_user_aliases'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection for introspection
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Add discord_user_id column to server_alias table if it doesn't exist
    # This supports both user-specific aliases (when set) and global aliases (when NULL)
    columns = [col['name'] for col in inspector.get_columns('server_alias')]
    if 'discord_user_id' not in columns:
        op.add_column('server_alias', sa.Column('discord_user_id', sa.BigInteger(), nullable=True))
        op.create_index(op.f('ix_server_alias_discord_user_id'), 'server_alias', ['discord_user_id'], unique=False)
    
    # Add created_at column if it doesn't exist
    if 'created_at' not in columns:
        # Use DateTime with server default based on dialect
        op.add_column('server_alias', 
            sa.Column('created_at', sa.DateTime(timezone=True), 
                     server_default=sa.func.now(), nullable=False))
    
    # Check and update unique constraints
    constraints = inspector.get_unique_constraints('server_alias')
    constraint_names = [c['name'] for c in constraints]
    
    # Drop old unique constraint if it exists
    if 'uq_alias' in constraint_names:
        op.drop_constraint('uq_alias', 'server_alias', type_='unique')
    
    # Add new unique constraint if it doesn't exist
    if 'uq_alias_user' not in constraint_names:
        op.create_unique_constraint('uq_alias_user', 'server_alias', ['alias', 'discord_user_id'])


def downgrade() -> None:
    # WARNING: This downgrade may fail if data exists with duplicate aliases for different users
    # Get database connection for introspection
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check and update unique constraints
    constraints = inspector.get_unique_constraints('server_alias')
    constraint_names = [c['name'] for c in constraints]
    
    # Remove new unique constraint if it exists
    if 'uq_alias_user' in constraint_names:
        op.drop_constraint('uq_alias_user', 'server_alias', type_='unique')
    
    # Restore old unique constraint if it doesn't exist
    # NOTE: This will fail if there are duplicate aliases in the table
    if 'uq_alias' not in constraint_names:
        try:
            op.create_unique_constraint('uq_alias', 'server_alias', ['alias'])
        except Exception:
            # If this fails due to duplicate aliases, you'll need to clean up data first
            pass
    
    # Remove created_at column if it exists
    columns = [col['name'] for col in inspector.get_columns('server_alias')]
    if 'created_at' in columns:
        op.drop_column('server_alias', 'created_at')
    
    # Remove discord_user_id column if it exists
    if 'discord_user_id' in columns:
        op.drop_index(op.f('ix_server_alias_discord_user_id'), table_name='server_alias')
        op.drop_column('server_alias', 'discord_user_id')
