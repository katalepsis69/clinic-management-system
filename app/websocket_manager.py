from typing import List
from fastapi import WebSocket
from app.redis_pubsub import bus


class QueueConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        # ponytail: hook local socket fan-out to cluster broadcast bus
        bus.subscribe("queue", self._send_local)

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def _send_local(self, message: dict):
        dead = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for connection in dead:
            self.disconnect(connection)

    async def broadcast(self, message: dict):
        await bus.publish("queue", message)


queue_manager = QueueConnectionManager()
