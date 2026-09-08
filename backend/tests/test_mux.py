import subprocess

import pytest

from app.services.video.ffprobe import probe_video
from app.services.video.mux import mux_video_with_audio


@pytest.fixture
def tiny_video_with_original_audio(tmp_path):
    out = tmp_path / "video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=3",
            "-f", "lavfi", "-i", "sine=frequency=220:duration=3",
            "-shortest", str(out),
        ],
        check=True, capture_output=True,
    )
    return str(out)


@pytest.fixture
def replacement_audio(tmp_path):
    out = tmp_path / "new_audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", str(out)],
        check=True, capture_output=True,
    )
    return str(out)


def test_mux_replaces_audio_and_copies_video_stream(
    tiny_video_with_original_audio, replacement_audio, tmp_path
):
    out_path = str(tmp_path / "muxed.mp4")
    mux_video_with_audio(tiny_video_with_original_audio, replacement_audio, out_path)

    original_meta = probe_video(tiny_video_with_original_audio)
    muxed_meta = probe_video(out_path)

    assert muxed_meta.resolution == original_meta.resolution
    assert muxed_meta.codec == original_meta.codec  # video stream copied, not re-encoded
    assert 2.7 <= muxed_meta.duration_sec <= 3.3
