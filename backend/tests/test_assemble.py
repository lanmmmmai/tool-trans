import subprocess

import pytest

from app.services.audio.assemble import SegmentAudioPlacement, assemble_dubbed_audio_track
from app.services.audio.duration import probe_audio_duration


def make_tone(tmp_path, name: str, duration: float, freq: int = 440):
    path = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}", str(path)],
        check=True, capture_output=True,
    )
    return str(path)


def test_assemble_pads_gaps_with_silence(tmp_path):
    clip_a = make_tone(tmp_path, "a.wav", duration=1.0)
    clip_b = make_tone(tmp_path, "b.wav", duration=1.0, freq=880)

    placements = [
        SegmentAudioPlacement(start_time=0.0, end_time=1.0, audio_path=clip_a),
        SegmentAudioPlacement(start_time=3.0, end_time=4.0, audio_path=clip_b),  # 2s gap before it
    ]

    out_path = str(tmp_path / "assembled.wav")
    assemble_dubbed_audio_track(placements, total_duration=5.0, out_path=out_path)

    duration = probe_audio_duration(out_path)
    assert 4.7 <= duration <= 5.3


def test_assemble_applies_atempo_when_clip_overflows_its_window(tmp_path):
    # 2-second clip must fit into a 1-second window -> gets sped up ~2x
    overflowing_clip = make_tone(tmp_path, "long.wav", duration=2.0)

    placements = [
        SegmentAudioPlacement(start_time=0.0, end_time=1.0, audio_path=overflowing_clip),
        SegmentAudioPlacement(start_time=1.0, end_time=2.0, audio_path=make_tone(tmp_path, "next.wav", duration=0.8, freq=880)),
    ]

    out_path = str(tmp_path / "assembled_overflow.wav")
    assemble_dubbed_audio_track(placements, total_duration=2.0, out_path=out_path)

    duration = probe_audio_duration(out_path)
    # Without atempo correction this would be ~2.8-3.0s; with correction it
    # should land close to the 2.0s total_duration.
    assert duration <= 2.5
