from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_voice_catalog_returns_both_engines():
    resp = client.get("/api/voices/catalog")
    assert resp.status_code == 200
    body = resp.json()
    engines = {v["engine"] for v in body}
    assert engines == {"edge_tts", "gemini_tts"}


def test_get_voice_preview_returns_audio_bytes():
    with patch("app.api.voices.EdgeTTSEngine") as MockEngine:
        def fake_synthesize(text, voice_id, speed, out_path):
            with open(out_path, "wb") as f:
                f.write(b"fake-mp3-bytes")

        MockEngine.return_value.synthesize.side_effect = fake_synthesize

        resp = client.get(
            "/api/voices/preview", params={"engine": "edge_tts", "voice_id": "vi-VN-HoaiMyNeural"}
        )

    assert resp.status_code == 200
    assert resp.content == b"fake-mp3-bytes"
    assert resp.headers["content-type"].startswith("audio/")
