from unittest.mock import MagicMock, patch

import pytest

from app.services.stt.base import STTProviderError
from app.services.stt.elevenlabs import ElevenLabsSTT

SAMPLE_RESPONSE = {
    "words": [
        {"text": "Hello", "start": 0.0, "end": 0.4, "speaker_id": "speaker_1"},
        {"text": "world", "start": 0.4, "end": 0.9, "speaker_id": "speaker_1"},
        {"text": "Hi", "start": 1.2, "end": 1.5, "speaker_id": "speaker_2"},
    ]
}


@pytest.fixture
def fake_audio_path(tmp_path):
    path = tmp_path / "audio.wav"
    path.write_bytes(b"fake-wav-bytes")
    return str(path)


def test_transcribe_groups_words_into_segments_by_speaker(fake_audio_path):
    engine = ElevenLabsSTT(api_key="fake-key")

    with patch("app.services.stt.elevenlabs.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE
        mock_post.return_value = mock_response

        segments = engine.transcribe(fake_audio_path)

    assert len(segments) == 2
    assert segments[0].speaker_label == "speaker_1"
    assert segments[0].text == "Hello world"
    assert segments[0].start == 0.0
    assert segments[0].end == 0.9
    assert segments[1].speaker_label == "speaker_2"
    assert segments[1].text == "Hi"


def test_transcribe_raises_provider_error_on_failure(fake_audio_path):
    engine = ElevenLabsSTT(api_key="fake-key")

    with patch("app.services.stt.elevenlabs.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "quota exceeded"
        mock_post.return_value = mock_response

        with pytest.raises(STTProviderError):
            engine.transcribe(fake_audio_path)
