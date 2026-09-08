from unittest.mock import patch

from app.services.stt.base import STTProviderError, STTSegment
from app.services.stt.router import transcribe_with_fallback


def test_uses_elevenlabs_when_it_succeeds():
    fake_segments = [STTSegment(start=0, end=1, speaker_label="speaker_1", text="hi")]

    with patch("app.services.stt.router.ElevenLabsSTT") as MockEleven:
        MockEleven.return_value.transcribe.return_value = fake_segments

        segments, engine_used = transcribe_with_fallback("/tmp/audio.wav")

    assert engine_used == "elevenlabs"
    assert segments == fake_segments


def test_falls_back_to_whisper_local_when_elevenlabs_fails():
    fake_segments = [STTSegment(start=0, end=1, speaker_label="speaker_1", text="hi")]

    with patch("app.services.stt.router.ElevenLabsSTT") as MockEleven, patch(
        "app.services.stt.router.WhisperLocalSTT"
    ) as MockWhisper:
        MockEleven.return_value.transcribe.side_effect = STTProviderError("quota exceeded")
        MockWhisper.return_value.transcribe.return_value = fake_segments

        segments, engine_used = transcribe_with_fallback("/tmp/audio.wav")

    assert engine_used == "whisper_local"
    assert segments == fake_segments
