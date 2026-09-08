import asyncio

import edge_tts

from app.services.tts.base import TTSEngine, TTSProviderError, VoiceCatalogEntry

VOICE_CATALOG = [
    VoiceCatalogEntry(voice_id="vi-VN-HoaiMyNeural", name="Hoài My (nữ)", gender="female", engine="edge_tts"),
    VoiceCatalogEntry(voice_id="vi-VN-NamMinhNeural", name="Nam Minh (nam)", gender="male", engine="edge_tts"),
]


def _speed_to_rate_string(speed: float) -> str:
    percent = round((speed - 1.0) * 100)
    sign = "+" if percent >= 0 else ""
    return f"{sign}{percent}%"


class EdgeTTSEngine(TTSEngine):
    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        rate = _speed_to_rate_string(speed)
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=rate)
            asyncio.run(communicate.save(out_path))
        except Exception as exc:
            raise TTSProviderError(f"edge-tts failed for voice {voice_id}: {exc}") from exc

    def list_voices(self) -> list[VoiceCatalogEntry]:
        return VOICE_CATALOG
