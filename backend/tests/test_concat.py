import subprocess

import pytest

from app.services.audio.concat import concat_audio_pieces
from app.services.audio.duration import probe_audio_duration


@pytest.fixture
def two_clips(tmp_path):
    clip1 = tmp_path / "clip1.wav"
    clip2 = tmp_path / "clip2.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(clip1)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", str(clip2)],
        check=True, capture_output=True,
    )
    return [str(clip1), str(clip2)]


def test_concat_audio_pieces_sums_durations(two_clips, tmp_path):
    out_path = str(tmp_path / "combined.wav")
    concat_audio_pieces(two_clips, out_path)
    duration = probe_audio_duration(out_path)
    assert 2.7 <= duration <= 3.3  # ~1s + ~2s
