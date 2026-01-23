"""Database migration utilities using Alembic."""
from __future__ import annotations

import os
import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()


def _get_alembic_config() -> Config:
    """Get Alembic config with proper path handling."""
    # Get the directory where this module is located
    module_dir = os.path.dirname(os.path.abspath(__file__))
    # alembic.ini is in the project root, two levels up from bot/db/
    project_root = os.path.dirname(os.path.dirname(module_dir))
    alembic_ini_path = os.path.join(project_root, "alembic.ini")
    
    return Config(alembic_ini_path)


async def run_migrations(engine: AsyncEngine) -> None:
    """
    Run Alembic migrations to upgrade the database to the latest version.
    
    This is automatically called on bot startup to ensure the database schema
    is up-to-date with the code.
    
    Args:
        engine: The async SQLAlchemy engine
    """
    try:
        # Create Alembic config
        alembic_cfg = _get_alembic_config()
        
        # Run migrations in a sync context (Alembic doesn't support async yet)
        def run_upgrade(connection):
            alembic_cfg.attributes['connection'] = connection
            command.upgrade(alembic_cfg, "head")
        
        # Use the engine to run migrations synchronously
        async with engine.begin() as conn:
            await conn.run_sync(run_upgrade)
        
        log.info("database_migrations_applied")
    except Exception as e:
        log.error("migration_failed", error=str(e), error_type=type(e).__name__)
        raise


def create_migration(message: str) -> None:
    """
    Create a new migration file with autogenerate.
    
    Usage:
        python -m bot.db.migrations create_migration "Add new field to table"
    
    Args:
        message: Description of the migration
    """
    alembic_cfg = _get_alembic_config()
    command.revision(alembic_cfg, message=message, autogenerate=True)
    log.info("migration_created", message=message)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        create_migration(" ".join(sys.argv[1:]))
    else:
        print("Usage: python -m bot.db.migrations <migration message>")
        sys.exit(1)
