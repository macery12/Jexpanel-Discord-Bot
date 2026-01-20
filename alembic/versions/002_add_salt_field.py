"""Add salt_b64 field for enhanced key derivation security

Revision ID: 002_add_salt_field
Revises: 001_user_aliases
Create Date: 2026-01-20 20:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = '002_add_salt_field'
down_revision = '001_user_aliases'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add salt_b64 column to user_credentials table for per-user key derivation.
    
    This field stores the salt used with Argon2id to derive user-specific encryption keys.
    Old credentials (salt_b64 = NULL) will use legacy decryption.
    New credentials will use the enhanced Argon2id-based encryption.
    """
    # Get database connection for introspection
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if user_credentials table exists
    tables = inspector.get_table_names()
    if 'user_credentials' not in tables:
        # Table doesn't exist yet, skip migration
        return
    
    # Add salt_b64 column if it doesn't exist
    columns = [col['name'] for col in inspector.get_columns('user_credentials')]
    if 'salt_b64' not in columns:
        op.add_column('user_credentials', 
            sa.Column('salt_b64', sa.String(), nullable=True))


def downgrade() -> None:
    """
    Remove salt_b64 column from user_credentials table.
    
    WARNING: This will make credentials encrypted with the new method unreadable.
    Only downgrade if you've migrated all credentials back to legacy encryption.
    """
    # Get database connection for introspection
    conn = op.get_bind()
    inspector = inspect(conn)
    
    # Check if user_credentials table exists
    tables = inspector.get_table_names()
    if 'user_credentials' not in tables:
        return
    
    # Remove salt_b64 column if it exists
    columns = [col['name'] for col in inspector.get_columns('user_credentials')]
    if 'salt_b64' in columns:
        op.drop_column('user_credentials', 'salt_b64')
