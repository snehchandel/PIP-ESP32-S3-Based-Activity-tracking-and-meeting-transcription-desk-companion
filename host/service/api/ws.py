"""WebSocket hub: fan-out of state_updated / timer_tick / device_link_changed / ... events."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect


class WsHub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def publish(self, event: str, payload: dict[str, Any]) -> None:
        """Thread-safe: may be called from worker threads or the event loop."""
        if not self.loop or not self.clients:
            return
        msg = json.dumps({"event": event, "data": payload}, default=str)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self._broadcast(msg))
        else:
            asyncio.run_coroutine_threadsafe(self._broadcast(msg), self.loop)

    async def _broadcast(self, msg: str) -> None:
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        try:
            await ws.send_text(json.dumps({"event": "hello", "data": {}}))
            while True:
                await ws.receive_text()  # keepalive pings from the client; no commands over WS
        except WebSocketDisconnect:
            pass
        finally:
            self.clients.discard(ws)
