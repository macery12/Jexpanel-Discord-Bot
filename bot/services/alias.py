"""Alias management service for server identification."""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ServerAlias


async def get_alias(
    session: AsyncSession, alias: str, user_id: int | None = None
) -> ServerAlias | None:
    """
    Get an alias record. Checks user-specific aliases first, then global aliases.
    
    Args:
        session: Database session
        alias: The alias to look up
        user_id: Optional user ID for user-specific lookup
    
    Returns:
        ServerAlias record if found, None otherwise
    """
    if user_id:
        # First try user-specific alias
        res = await session.execute(
            select(ServerAlias).where(
                and_(ServerAlias.alias == alias, ServerAlias.discord_user_id == user_id)
            )
        )
        user_alias = res.scalar_one_or_none()
        if user_alias:
            return user_alias
    
    # Then try global alias (discord_user_id is None)
    res = await session.execute(
        select(ServerAlias).where(
            and_(ServerAlias.alias == alias, ServerAlias.discord_user_id == None)
        )
    )
    return res.scalar_one_or_none()


async def list_user_aliases(session: AsyncSession, user_id: int) -> list[ServerAlias]:
    """
    List all aliases for a specific user.
    
    Args:
        session: Database session
        user_id: Discord user ID
    
    Returns:
        List of ServerAlias records
    """
    res = await session.execute(
        select(ServerAlias)
        .where(ServerAlias.discord_user_id == user_id)
        .order_by(ServerAlias.alias)
    )
    return list(res.scalars().all())


async def list_global_aliases(session: AsyncSession) -> list[ServerAlias]:
    """
    List all global aliases (admin-created).
    
    Args:
        session: Database session
    
    Returns:
        List of ServerAlias records
    """
    res = await session.execute(
        select(ServerAlias)
        .where(ServerAlias.discord_user_id == None)
        .order_by(ServerAlias.alias)
    )
    return list(res.scalars().all())


async def create_or_update_alias(
    session: AsyncSession,
    alias: str,
    uuid: str,
    panel_url: str | None = None,
    user_id: int | None = None,
) -> ServerAlias:
    """
    Create or update an alias.
    
    Args:
        session: Database session
        alias: The alias name
        uuid: Server UUID
        panel_url: Optional panel URL
        user_id: Optional user ID (None for global aliases)
    
    Returns:
        The created or updated ServerAlias record
    """
    # Check if alias exists for this user/global
    res = await session.execute(
        select(ServerAlias).where(
            and_(ServerAlias.alias == alias, ServerAlias.discord_user_id == user_id)
        )
    )
    existing = res.scalar_one_or_none()
    
    if existing:
        # Update existing
        existing.uuid = uuid
        existing.panel_url = panel_url
        return existing
    else:
        # Create new
        new_alias = ServerAlias(
            alias=alias,
            uuid=uuid,
            panel_url=panel_url,
            discord_user_id=user_id,
        )
        session.add(new_alias)
        return new_alias


async def delete_alias(
    session: AsyncSession, alias: str, user_id: int | None = None
) -> bool:
    """
    Delete an alias.
    
    Args:
        session: Database session
        alias: The alias to delete
        user_id: Optional user ID (None for global aliases)
    
    Returns:
        True if deleted, False if not found
    """
    res = await session.execute(
        select(ServerAlias).where(
            and_(ServerAlias.alias == alias, ServerAlias.discord_user_id == user_id)
        )
    )
    alias_obj = res.scalar_one_or_none()
    
    if alias_obj:
        await session.delete(alias_obj)
        return True
    return False
