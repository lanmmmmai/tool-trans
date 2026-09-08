from fastapi import FastAPI

from app.api.projects import router as projects_router
from app.api.transcript import router as transcript_router
from app.api.ws_progress import router as ws_progress_router

app = FastAPI(title="AI Video Dubbing API")
app.include_router(projects_router)
app.include_router(transcript_router)
app.include_router(ws_progress_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
