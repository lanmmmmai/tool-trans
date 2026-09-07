from fastapi import FastAPI

from app.api.projects import router as projects_router

app = FastAPI(title="AI Video Dubbing API")
app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
