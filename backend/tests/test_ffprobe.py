import subprocess
from pathlib import Path

import pytest

from app.services.video.ffprobe import ProbeError, probe_video

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture(scope="module", autouse=True)
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


def test_probe_video_returns_metadata():
    result = probe_video(str(FIXTURE))
    assert 1.5 <= result.duration_sec <= 2.5
    assert result.resolution == "320x240"
    assert result.codec  # e.g. "h264"
    assert result.file_size_bytes > 0


def test_probe_video_raises_on_missing_file():
    with pytest.raises(ProbeError):
        probe_video("/nonexistent/path.mp4")
