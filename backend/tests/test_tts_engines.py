from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tts.base import TTSProviderError
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine


def test_edge_tts_list_voices_returns_vietnamese_voices():
    engine = EdgeTTSEngine()
    voices = engine.list_voices()
    voice_ids = {v.voice_id for v in voices}
    assert "vi-VN-HoaiMyNeural" in voice_ids
    assert "vi-VN-NamMinhNeural" in voice_ids
    assert all(v.engine == "edge_tts" for v in voices)


def test_edge_tts_synthesize_converts_speed_to_rate_string(tmp_path):
    engine = EdgeTTSEngine()
    out_path = str(tmp_path / "out.mp3")

    with patch("app.services.tts.edge_tts_engine.edge_tts.Communicate") as MockCommunicate:
        mock_instance = MockCommunicate.return_value
        mock_instance.save = AsyncMock()

        engine.synthesize("Xin chào", "vi-VN-HoaiMyNeural", speed=1.2, out_path=out_path)

        MockCommunicate.assert_called_once_with(
            "Xin chào", "vi-VN-HoaiMyNeural", rate="+20%"
        )
        mock_instance.save.assert_awaited_once_with(out_path)


def test_edge_tts_synthesize_raises_provider_error_on_failure(tmp_path):
    engine = EdgeTTSEngine()
    out_path = str(tmp_path / "out.mp3")

    with patch("app.services.tts.edge_tts_engine.edge_tts.Communicate") as MockCommunicate:
        mock_instance = MockCommunicate.return_value
        mock_instance.save = AsyncMock(side_effect=Exception("network unreachable"))

        with pytest.raises(TTSProviderError):
            engine.synthesize("Xin chào", "vi-VN-HoaiMyNeural", speed=1.0, out_path=out_path)


def test_gemini_tts_list_voices_returns_catalog():
    engine = GeminiTTSEngine(api_key="fake")
    voices = engine.list_voices()
    assert len(voices) > 0
    assert all(v.engine == "gemini_tts" for v in voices)


def test_gemini_tts_synthesize_writes_wav_from_pcm(tmp_path):
    engine = GeminiTTSEngine(api_key="fake")
    out_path = str(tmp_path / "out.wav")

    fake_pcm = b"\x00\x01" * 1000  # 16-bit PCM samples

    with patch("app.services.tts.gemini_tts_engine.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_part = MagicMock()
        mock_part.inline_data.data = fake_pcm
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
        mock_client.models.generate_content.return_value = mock_response

        engine.synthesize("Xin chào", "Kore", speed=1.0, out_path=out_path)

    import wave

    with wave.open(out_path, "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24000


def test_gemini_tts_synthesize_raises_provider_error_when_no_audio_returned(tmp_path):
    engine = GeminiTTSEngine(api_key="fake")
    out_path = str(tmp_path / "out.wav")

    with patch("app.services.tts.gemini_tts_engine.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=None)]
        mock_client.models.generate_content.return_value = mock_response

        with pytest.raises(TTSProviderError):
            engine.synthesize("Xin chào", "Kore", speed=1.0, out_path=out_path)
