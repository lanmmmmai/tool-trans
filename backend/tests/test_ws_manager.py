import asyncio
from unittest.mock import AsyncMock

from app.core.ws_manager import WSManager


def test_broadcast_sends_to_all_connections_for_project():
    manager = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws_other_project = AsyncMock()

    manager.connect("project-1", ws1)
    manager.connect("project-1", ws2)
    manager.connect("project-2", ws_other_project)

    asyncio.run(manager.broadcast("project-1", {"progress_pct": 50}))

    ws1.send_json.assert_awaited_once_with({"progress_pct": 50})
    ws2.send_json.assert_awaited_once_with({"progress_pct": 50})
    ws_other_project.send_json.assert_not_awaited()


def test_disconnect_removes_connection():
    manager = WSManager()
    ws1 = AsyncMock()
    manager.connect("project-1", ws1)
    manager.disconnect("project-1", ws1)

    asyncio.run(manager.broadcast("project-1", {"progress_pct": 100}))

    ws1.send_json.assert_not_awaited()
