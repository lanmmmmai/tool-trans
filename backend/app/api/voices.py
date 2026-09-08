import os
import tempfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.config import settings
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine

router = APIRouter(prefix="/api/voices", tags=["voices"])

PREVIEW_TEXT = "Xin chào, đây là giọng đọc mẫu."


class VoiceCatalogEntryRead(BaseModel):
    voice_id: str
    name: str
    gender: str
    engine: str


def _get_engine(engine_name: str):
    if engine_name == "gemini_tts":
        return GeminiTTSEngine(api_key=settings.gemini_api_key)
    if engine_name == "edge_tts":
        return EdgeTTSEngine()
    raise HTTPException(status_code=400, detail=f"Unknown engine: {engine_name}")


@router.get("/catalog", response_model=list[VoiceCatalogEntryRead])
def get_voice_catalog():
    edge = EdgeTTSEngine().list_voices()
    gemini = GeminiTTSEngine(api_key=settings.gemini_api_key).list_voices()
    return [
        VoiceCatalogEntryRead(voice_id=v.voice_id, name=v.name, gender=v.gender, engine=v.engine)
        for v in [*edge, *gemini]
    ]


@router.get("/preview")
def get_voice_preview(engine: str = Query(...), voice_id: str = Query(...)):
    tts_engine = _get_engine(engine)
    suffix = ".wav" if engine == "gemini_tts" else ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name

    try:
        tts_engine.synthesize(PREVIEW_TEXT, voice_id, speed=1.0, out_path=tmp_path)
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
    finally:
        os.remove(tmp_path)

    media_type = "audio/wav" if suffix == ".wav" else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)
