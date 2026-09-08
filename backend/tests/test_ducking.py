import subprocess

import pytest

from app.services.audio.ducking import duck_and_mix
from app.services.audio.duration import probe_audio_duration


@pytest.fixture
def two_tracks(tmp_path):
    original = tmp_path / "original.wav"
    voice = tmp_path / "voice.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=3", str(original)],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=3", str(voice)],
        check=True, capture_output=True,
    )
    return str(original), str(voice)


def test_duck_and_mix_produces_output_matching_voice_duration(two_tracks, tmp_path):
    original, voice = two_tracks
    out_path = str(tmp_path / "ducked.wav")

    duck_and_mix(original, voice, out_path, background_volume=0.3)

    duration = probe_audio_duration(out_path)
    assert 2.7 <= duration <= 3.3
