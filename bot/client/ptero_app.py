from __future__ import annotations
import aiohttp
from typing import Any
from yarl import URL
from ..config import settings

class PteroApp:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.base = URL(settings.panel_url)

    def _headers(self) -> dict[str, str]:
        if not settings.app_api_key:
            raise RuntimeError("APP API key not configured")
        return {
            "Authorization": f"Bearer {settings.app_api_key}",
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Content-Type": "application/json",
        }

    async def list_nodes(self) -> list[dict[str, Any]]:
        url = self.base.with_path("/api/application/nodes")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            data = await r.json()
            return [d["attributes"] for d in data.get("data", [])]

    async def list_allocations(self, node_id: int) -> list[dict[str, Any]]:
        url = self.base.with_path(f"/api/application/nodes/{node_id}/allocations")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            data = await r.json()
            return [d["attributes"] for d in data.get("data", [])]
