"""Helper functions for server-related operations."""
from __future__ import annotations

import aiohttp
from sqlalchemy import select

from ..client.ptero_rest import PteroClient
from ..db import SessionLocal
from ..db.models import ServerAlias, UserCredential
from ..utils.permissions import SERVER_UUID_RE


async def list_user_panels(user_id: int) -> list[str]:
    """Get list of panel URLs for which the user has credentials."""
    async with SessionLocal() as s:
        res = await s.execute(select(UserCredential.panel_url).where(UserCredential.discord_user_id == user_id))
        urls = sorted(set([row[0] for row in res.all()]))
        return urls


async def get_user_token_for_panel(user_id: int, panel_url: str) -> str | None:
    """Get user's token for a specific panel."""
    async with SessionLocal() as s:
        from ..services.credentials import get_user_token
        return await get_user_token(s, user_id, panel_url)


async def resolve_identifier_and_panel(user_id: int, value: str) -> tuple[str | None, str | None]:
    """Resolve a user input (UUID/alias/name) to a server UUID and panel URL.
    
    Returns:
        Tuple of (uuid, panel_url) or (None, None) if not found
    """
    val = value.strip()
    
    # If it's a UUID, try to find which panel it's on
    if SERVER_UUID_RE.match(val):
        panels = await list_user_panels(user_id)
        if not panels:
            return (val, None)
        if len(panels) == 1:
            return (val, panels[0])
        # Multiple panels - probe each to find which has this UUID
        async with aiohttp.ClientSession() as sess:
            for p in panels:
                tok = await get_user_token_for_panel(user_id, p)
                if not tok:
                    continue
                cli = PteroClient(sess, p, tok)
                try:
                    await cli.server_details(val)
                    return (val, p)
                except Exception:
                    continue
        return (val, None)
    
    # Check if it's an alias
    async with SessionLocal() as s:
        res = await s.execute(select(ServerAlias).where(ServerAlias.alias == val))
        alias = res.scalar_one_or_none()
        if alias:
            if alias.panel_url:
                return (alias.uuid, alias.panel_url)
            uuid_guess = alias.uuid
        else:
            uuid_guess = None
    
    # Search across all panels by name/partial match
    panels = await list_user_panels(user_id)
    if not panels:
        return (None, None)
    
    async with aiohttp.ClientSession() as sess:
        for p in panels:
            tok = await get_user_token_for_panel(user_id, p)
            if not tok:
                continue
            cli = PteroClient(sess, p, tok)
            try:
                servers = await cli.list_servers()
                needle = val.lower()
                for srv in servers:
                    if uuid_guess and srv.get("uuid") == uuid_guess:
                        return (srv["uuid"], p)
                    uuid = srv.get("uuid", "")
                    name = srv.get("name", "")
                    if uuid.startswith(val) or needle in name.lower():
                        return (uuid, p)
            except Exception:
                continue
    
    return (None, None)
