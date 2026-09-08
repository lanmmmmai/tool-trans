import subprocess
from pathlib import Path

import pytest

from app.services.audio.duration import probe_audio_duration


@pytest.fixture
def sample_audio(tmp_path):
    out = tmp_path / "sample.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def test_probe_audio_duration_returns_seconds(sample_audio):
    duration = probe_audio_duration(str(sample_audio))
    assert 2.5 <= duration <= 3.5
