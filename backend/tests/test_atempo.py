import subprocess
from pathlib import Path

import pytest

from app.services.audio.atempo import apply_atempo, build_atempo_filter_chain
from app.services.audio.duration import probe_audio_duration


def test_build_atempo_filter_chain_single_stage_for_valid_range():
    assert build_atempo_filter_chain(1.5) == "atempo=1.5"


def test_build_atempo_filter_chain_splits_large_factors():
    chain = build_atempo_filter_chain(4.0)
    assert chain == "atempo=2.0,atempo=2.0"


def test_build_atempo_filter_chain_splits_uneven_large_factors():
    chain = build_atempo_filter_chain(3.0)
    # 3.0 = 2.0 * 1.5
    assert chain == "atempo=2.0,atempo=1.5"


@pytest.fixture
def sample_audio(tmp_path):
    out = tmp_path / "sample.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=4", str(out)],
        check=True, capture_output=True,
    )
    return out


def test_apply_atempo_shortens_audio_by_factor(sample_audio, tmp_path):
    out_path = str(tmp_path / "sped_up.wav")
    apply_atempo(str(sample_audio), out_path, factor=2.0)
    duration = probe_audio_duration(out_path)
    assert 1.8 <= duration <= 2.2  # 4s audio at 2x speed -> ~2s
