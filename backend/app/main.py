from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.glossary import router as glossary_router
from app.api.projects import router as projects_router
from app.api.transcript import router as transcript_router
from app.api.translation import router as translation_router
from app.api.voices import router as voices_router
from app.api.ws_progress import router as ws_progress_router

app = FastAPI(title="AI Video Dubbing API")

# Client Components (e.g. the transcript progress/editor pages) fetch the
# API directly from the browser, which is a cross-origin request in dev
# (frontend on :3000, backend on :8000) and gets blocked without this —
# found by actually loading a client-fetching page in a real browser, not
# by curl or server-rendered pages (those aren't subject to CORS at all).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects_router)
app.include_router(transcript_router)
app.include_router(translation_router)
app.include_router(glossary_router)
app.include_router(voices_router)
app.include_router(ws_progress_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
