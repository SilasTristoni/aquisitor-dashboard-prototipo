import asyncio
from datetime import UTC, datetime

from fastapi import WebSocket

from app.core.config import get_settings


class WebSocketHub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, asyncio.Queue] = {}
        self._lock = asyncio.Lock()
        self.queue_size = get_settings().websocket_queue_size

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.clients[websocket] = asyncio.Queue(maxsize=self.queue_size)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self.clients.pop(websocket, None)

    async def publish(self, message_type: str, payload: dict) -> None:
        envelope = {
            "type": message_type,
            "timestamp": datetime.now(UTC).isoformat(),
            "payload": payload,
        }
        async with self._lock:
            clients = list(self.clients.items())
        for _, queue in clients:
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                pass


websocket_hub = WebSocketHub()
