import asyncio
import json

import redis.asyncio as redis_async
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import settings
from app.core.ws_manager import PROGRESS_CHANNEL_PREFIX, ws_manager

router = APIRouter()


async def _relay_redis_to_websocket(project_id: str) -> None:
    """Bridges the Redis channel a worker process publishes progress to
    into this backend process's local WebSocket connections for the same
    project."""
    redis_conn = redis_async.from_url(settings.redis_url)
    pubsub = redis_conn.pubsub()
    channel = f"{PROGRESS_CHANNEL_PREFIX}{project_id}"
    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            data = json.loads(message["data"])
            await ws_manager.broadcast(project_id, data)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        await redis_conn.aclose()


@router.websocket("/ws/projects/{project_id}/progress")
async def project_progress_ws(websocket: WebSocket, project_id: str):
    await websocket.accept()
    ws_manager.connect(project_id, websocket)
    relay_task = asyncio.create_task(_relay_redis_to_websocket(project_id))

    try:
        while True:
            await websocket.receive_text()  # keep the connection open; client sends pings
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
    finally:
        relay_task.cancel()
