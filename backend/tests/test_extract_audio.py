import subprocess
import wave
from pathlib import Path

import pytest

from app.services.audio.extract import AudioExtractionError, extract_audio

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture(autouse=True)
def ensure_fixture():
    if not FIXTURE.exists():
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-shortest",
                str(FIXTURE),
            ],
            check=True,
        )


def test_extract_audio_produces_valid_wav(tmp_path):
    out_path = tmp_path / "out.wav"
    extract_audio(str(FIXTURE), str(out_path))

    assert out_path.exists()
    with wave.open(str(out_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() > 0


def test_extract_audio_raises_on_missing_input():
    with pytest.raises(AudioExtractionError):
        extract_audio("/nonexistent.mp4", "/tmp/out.wav")
