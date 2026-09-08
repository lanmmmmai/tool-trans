from app.core.config import settings
from app.services.stt.base import STTProviderError, STTSegment
from app.services.stt.elevenlabs import ElevenLabsSTT
from app.services.stt.whisper_local import WhisperLocalSTT


def transcribe_with_fallback(audio_path: str) -> tuple[list[STTSegment], str]:
    try:
        engine = ElevenLabsSTT(api_key=settings.elevenlabs_api_key)
        return engine.transcribe(audio_path), "elevenlabs"
    except STTProviderError:
        fallback = WhisperLocalSTT()
        return fallback.transcribe(audio_path), "whisper_local"
