from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from ..config import settings
from .models import Base

engine = create_async_engine(settings.database_url, future=True, echo=False)
SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def init_db():
    """Initialize the database with automatic migrations."""
    from .migrations import run_migrations
    
    # Run Alembic migrations to ensure schema is up-to-date
    await run_migrations(engine)

