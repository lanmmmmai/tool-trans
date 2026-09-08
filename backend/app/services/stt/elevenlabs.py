from typing import Optional

import httpx

from app.services.stt.base import STTEngine, STTProviderError, STTSegment

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
ELEVENLABS_MODEL_ID = "scribe_v2"
MAX_SILENCE_GAP_TO_MERGE = 0.5  # seconds; words within this gap join the same segment


class ElevenLabsSTT(STTEngine):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_path: str) -> list[STTSegment]:
        with open(audio_path, "rb") as f:
            response = httpx.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": self.api_key},
                files={"file": f},
                data={"model_id": ELEVENLABS_MODEL_ID, "diarize": "true"},
                timeout=600,
            )

        if response.status_code != 200:
            raise STTProviderError(
                f"ElevenLabs STT failed ({response.status_code}): {response.text}"
            )

        words = response.json().get("words", [])
        return self._group_words_into_segments(words)

    @staticmethod
    def _group_words_into_segments(words: list[dict]) -> list[STTSegment]:
        segments: list[STTSegment] = []
        current: Optional[dict] = None

        for word in words:
            speaker = word.get("speaker_id") or "speaker_1"
            if current is None or current["speaker_label"] != speaker or (
                word["start"] - current["end"] > MAX_SILENCE_GAP_TO_MERGE
            ):
                if current is not None:
                    segments.append(STTSegment(**current))
                current = {
                    "start": word["start"],
                    "end": word["end"],
                    "speaker_label": speaker,
                    "text": word["text"],
                    "confidence": None,
                }
            else:
                current["end"] = word["end"]
                current["text"] += f" {word['text']}"

        if current is not None:
            segments.append(STTSegment(**current))

        return segments
