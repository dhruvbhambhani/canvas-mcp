"""
WebSocket bridge between the Chrome extension and the MCP server.

The extension connects TO this server (ws://localhost:3001).
Python tools send Canvas API requests through the live connection.
"""
from __future__ import annotations
import asyncio
import json
import sys
import uuid
from typing import Any

import websockets

_connection = None
_connected: bool = False
_pending: dict[str, asyncio.Future] = {}
_canvas_base_url: str = ""
_canvas_user: str = ""

PORT = 3001


async def _handler(websocket):
    global _connection, _connected, _canvas_base_url, _canvas_user

    _connection = websocket
    _connected = True
    print("[canvas-mcp] Chrome extension connected", file=sys.stderr, flush=True)

    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "connected":
                _canvas_base_url = msg.get("url", "").rstrip("/")
                _canvas_user = msg.get("user", "")
                print(f"[canvas-mcp] Canvas: {_canvas_base_url}  user: {_canvas_user}", file=sys.stderr, flush=True)

            elif "id" in msg:
                future = _pending.get(msg["id"])
                if future and not future.done():
                    future.set_result(msg)

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if _connection is websocket:
            _connection = None
        _connected = False
        print("[canvas-mcp] Chrome extension disconnected", file=sys.stderr, flush=True)


async def start(port: int = PORT):
    import socket
    import subprocess

    # Kill any leftover process on our port (previous MCP server run)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                result = subprocess.run(
                    ["netstat", "-ano"],
                    capture_output=True, text=True
                )
                for line in result.stdout.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        subprocess.run(["taskkill", "/F", "/PID", pid],
                                       capture_output=True)
                await asyncio.sleep(1)
    except Exception:
        pass

    for attempt in range(3):
        try:
            server = await websockets.serve(_handler, "localhost", port)
            print(f"[canvas-mcp] WebSocket listening on ws://localhost:{port}", file=sys.stderr, flush=True)
            return server
        except OSError:
            if attempt < 2:
                await asyncio.sleep(2)

    print(f"[canvas-mcp] WARNING: Could not bind port {port} — Chrome extension won't connect", file=sys.stderr, flush=True)
    return None


async def request(endpoint: str, params: dict | None = None, single: bool = False) -> Any:
    """Send a Canvas API request through the extension and await the response."""
    if not _connected or _connection is None:
        raise RuntimeError(
            "Chrome extension not connected. "
            "Open Canvas in Chrome with the canvas-mcp extension installed."
        )

    req_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    _pending[req_id] = future

    try:
        await _connection.send(json.dumps({
            "id": req_id,
            "endpoint": endpoint,
            "params": params or {},
            "single": single,
        }))
        result = await asyncio.wait_for(asyncio.shield(future), timeout=30.0)
        if result.get("error"):
            raise RuntimeError(f"Canvas API error: {result['error']}")
        return result.get("data")
    except asyncio.TimeoutError:
        raise RuntimeError(f"Canvas API request timed out: {endpoint}")
    finally:
        _pending.pop(req_id, None)


def is_connected() -> bool:
    return _connected


def get_canvas_url() -> str:
    return _canvas_base_url


def get_canvas_user() -> str:
    return _canvas_user
