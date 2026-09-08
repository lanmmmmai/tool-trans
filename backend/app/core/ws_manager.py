import json
from collections import defaultdict
from typing import Any, Protocol

import redis

from app.core.config import settings

PROGRESS_CHANNEL_PREFIX = "progress:"


class SendsJSON(Protocol):
    async def send_json(self, data: Any) -> None: ...


class WSManager:
    def __init__(self):
        self._connections: dict[str, list[SendsJSON]] = defaultdict(list)

    def connect(self, project_id: str, websocket: SendsJSON) -> None:
        self._connections[project_id].append(websocket)

    def disconnect(self, project_id: str, websocket: SendsJSON) -> None:
        if websocket in self._connections[project_id]:
            self._connections[project_id].remove(websocket)

    async def broadcast(self, project_id: str, message: dict) -> None:
        for websocket in list(self._connections.get(project_id, [])):
            await websocket.send_json(message)


ws_manager = WSManager()


def publish_progress_sync(project_id: str, message: dict) -> None:
    """Called from Celery worker processes, which run in a separate
    container/process from the FastAPI backend that actually holds the
    WebSocket connections — an in-memory WSManager broadcast there would
    reach nothing. Publishing over Redis pub/sub is what actually crosses
    the process boundary; the backend's WebSocket route subscribes to the
    matching channel and relays into its own local WSManager."""
    client = redis.Redis.from_url(settings.redis_url)
    try:
        client.publish(f"{PROGRESS_CHANNEL_PREFIX}{project_id}", json.dumps(message))
    finally:
        client.close()
