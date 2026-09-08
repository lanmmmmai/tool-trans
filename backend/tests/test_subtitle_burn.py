import subprocess
from pathlib import Path

import pytest

from app.services.video.subtitle_burn import burn_subtitles
from app.services.video.ffprobe import probe_video


@pytest.fixture
def tiny_video(tmp_path):
    out = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest", str(out),
        ],
        check=True, capture_output=True,
    )
    return str(out)


@pytest.fixture
def tiny_srt(tmp_path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nXin chào\n\n", encoding="utf-8"
    )
    return str(srt_path)


def test_burn_subtitles_produces_playable_video(tiny_video, tiny_srt, tmp_path):
    out_path = str(tmp_path / "burned.mp4")
    burn_subtitles(tiny_video, tiny_srt, out_path, font_size=32, font_color="yellow", position="bottom_center")

    result = probe_video(out_path)
    assert 1.5 <= result.duration_sec <= 2.5
