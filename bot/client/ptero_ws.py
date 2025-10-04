from __future__ import annotations
import asyncio, json, time, collections
import websockets
from yarl import URL

async def _dial(socket_url: str, panel_url: str, token: str):
    origin = str(URL(panel_url).with_path("/")).rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Origin": origin}
    try:
        ws = await websockets.connect(socket_url, additional_headers=headers)
    except TypeError:
        ws = await websockets.connect(socket_url, extra_headers=headers)
    return ws

async def _auth(ws, token: str, timeout: float = 5.0) -> None:
    await ws.send(json.dumps({"event": "auth", "args": [token]}))
    end = time.time() + timeout
    while time.time() < end:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=end - time.time())
        except asyncio.TimeoutError:
            break
        data = json.loads(raw)
        ev = data.get("event")
        if ev == "auth success":
            return
        if ev in ("jwt error", "daemon error"):
            msg = (data.get("args") or [""])[0]
            raise RuntimeError(f"WebSocket auth failed: {msg}")
    raise RuntimeError("WebSocket auth timed out")

async def fetch_recent_logs(socket_url: str, panel_url: str, token: str, max_lines: int = 50, total_timeout: float = 2.5, idle_timeout: float = 0.4) -> list[str]:
    ws = await _dial(socket_url, panel_url, token)
    try:
        await _auth(ws, token)
        await ws.send(json.dumps({"event": "send logs", "args": [str(max_lines)]}))

        buf: collections.deque[str] = collections.deque(maxlen=max_lines)
        start = time.time()
        last_activity = start

        while time.time() - start < total_timeout:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                break
            last_activity = time.time()
            data = json.loads(raw)
            if data.get("event") == "console output":
                payload = (data.get("args") or [""])[0]
                for line in str(payload).splitlines():
                    buf.append(line)
                if len(buf) >= max_lines and (time.time() - last_activity) >= idle_timeout:
                    break
        return list(buf)
    finally:
        await ws.close()

async def send_console_command(socket_url: str, panel_url: str, token: str, command: str) -> None:
    ws = await _dial(socket_url, panel_url, token)
    try:
        await _auth(ws, token)
        await ws.send(json.dumps({"event": "send command", "args": [command]}))
    finally:
        await ws.close()
