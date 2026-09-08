from collections import defaultdict
from typing import Any, Protocol


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
