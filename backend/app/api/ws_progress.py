from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws_manager import ws_manager

router = APIRouter()


@router.websocket("/ws/projects/{project_id}/progress")
async def project_progress_ws(websocket: WebSocket, project_id: str):
    await websocket.accept()
    ws_manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the connection open; client sends pings
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
