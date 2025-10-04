from __future__ import annotations
import aiohttp
from typing import Any
from yarl import URL

class PteroClient:
    def __init__(self, session: aiohttp.ClientSession, panel_url: str, client_api_key: str):
        self.session = session
        self.base = URL(panel_url)
        self.token = client_api_key

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Content-Type": "application/json",
        }

    async def list_servers(self) -> list[dict[str, Any]]:
        url = self.base.with_path("/api/client")
        params = {"per_page": 50}
        out: list[dict[str, Any]] = []
        while True:
            async with self.session.get(url, headers=self._headers(), params=params) as r:
                r.raise_for_status()
                data = await r.json()
                out.extend([d["attributes"] for d in data.get("data", [])])
                links = data.get("links", {}) or {}
                next_url = links.get("next")
                if not next_url:
                    break
                url = URL(next_url)
                params = None
        return out

    async def server_details(self, identifier: str) -> dict[str, Any]:
        url = self.base.with_path(f"/api/client/servers/{identifier}")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            data = await r.json()
            return data["attributes"]

    async def server_resources(self, identifier: str) -> dict[str, Any]:
        url = self.base.with_path(f"/api/client/servers/{identifier}/resources")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            data = await r.json()
            return data["attributes"]

    async def websocket_info(self, identifier: str) -> dict[str, Any]:
        url = self.base.with_path(f"/api/client/servers/{identifier}/websocket")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            return await r.json()

    async def list_backups(self, identifier: str) -> list[dict[str, Any]]:
        url = self.base.with_path(f"/api/client/servers/{identifier}/backups")
        async with self.session.get(url, headers=self._headers()) as r:
            r.raise_for_status()
            data = await r.json()
            return [d["attributes"] for d in data.get("data", [])]

    async def create_backup(self, identifier: str, name: str | None = None) -> dict[str, Any]:
        url = self.base.with_path(f"/api/client/servers/{identifier}/backups")
        payload = {"name": name} if name else {}
        async with self.session.post(url, headers=self._headers(), json=payload) as r:
            r.raise_for_status()
            return (await r.json()).get("attributes", {})

    async def get_download_url(self, identifier: str, file_path: str) -> str | None:
        url = self.base.with_path(f"/api/client/servers/{identifier}/files/download")
        params = {"file": file_path}
        async with self.session.get(url, headers=self._headers(), params=params) as r:
            r.raise_for_status()
            data = await r.json()
            return (data.get("data", {}) or {}).get("url") or (data.get("attributes", {}) or {}).get("url") or data.get("url")

    async def download_file_bytes(self, download_url: str, max_bytes: int = 8*1024*1024) -> bytes | None:
        async with self.session.get(download_url) as r:
            r.raise_for_status()
            chunk = await r.content.read(max_bytes)
            return chunk
