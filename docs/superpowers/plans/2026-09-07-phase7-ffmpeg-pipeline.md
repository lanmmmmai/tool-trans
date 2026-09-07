# Phase 7: FFmpeg Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the audio/video assembly service layer: place per-segment dubbed audio on a full-length timeline using natural silence as padding and `atempo` as the last-resort timing fix; separate/duck the original audio per the project's chosen audio mode; generate SRT subtitles; burn or soft-embed them; and mux the final audio into the original video. This phase produces pure, independently testable **service functions** — no Celery task or API endpoint yet (those are Phase 8's `export_task` / `POST /export`, which call straight into this phase's functions).

**Architecture:** A `services/audio/assemble.py` module implementing steps 2-3 of the spec's timing-sync order (natural-gap padding, then `atempo`) on top of Phase 6's rate-adjusted clips; `services/audio/demucs.py` and `services/audio/ducking.py` for the two non-silent audio modes; `services/subtitle/srt.py` for SRT generation; `services/video/subtitle_burn.py` / `subtitle_embed.py`; `services/video/mux.py` to combine the final audio track with the original video.

**Tech Stack:** FFmpeg (subprocess), Demucs (subprocess), Python.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Timing sync order (spec §Đồng bộ thời gian): (1) TTS rate — done in Phase 6; (2) natural silence gaps as padding — this phase; (3) `atempo` as last resort — this phase.
- Audio mode is chosen per project (spec §Trộn âm thanh): `silent` (voice only), `music_separated` (Demucs-separated background + voice, user-adjustable volume), `ducking` (original audio lowered under the voice, user-adjustable volume). Demucs on CPU runs at ~1.5× real-time — a 60-minute video's separation step alone takes ~90 minutes (spec's documented cost, not something to optimize away here).
- Subtitles are Vietnamese-only, SRT format, always produced as three deliverables: standalone `.srt`, soft-embedded video, and a separately burned-in video with configurable font size/color/position (spec §Phụ đề). This phase builds the burn/embed/generate functions; Phase 8 wires them into the export flow and exposes the font/color/position choice via the API.
- Output resolution defaults to copying the original video stream (no re-encode) unless the user picks a different resolution at export time — that resolution choice is Phase 8's concern; this phase's `mux_video_with_audio` always copies the video stream (spec §Đầu vào Video, discovery Q19-A).
- `Project` needs a new `background_volume` field to support modes B/C's user-adjustable slider — added here since it's this phase's first consumer.

## Established Interfaces (produced here, consumed by Phase 8)

- `app.models.project.Project.background_volume: float` (new field, default `0.3`) — added via migration in Task 1.
- `app.services.audio.assemble.SegmentAudioPlacement(start_time: float, end_time: float, audio_path: str)`, `app.services.audio.assemble.assemble_dubbed_audio_track(placements: list[SegmentAudioPlacement], total_duration: float, out_path: str) -> None`.
- `app.services.audio.demucs.separate_vocals(input_audio_path: str, out_dir: str) -> DemucsResult` — `DemucsResult(vocals_path: str, accompaniment_path: str)`.
- `app.services.audio.ducking.duck_and_mix(original_audio_path: str, voice_path: str, out_path: str, background_volume: float) -> None`.
- `app.services.audio.mix.build_final_audio(audio_mode: str, voice_track_path: str, original_audio_path: str, background_volume: float, out_path: str) -> None` — the single entry point Phase 8 calls; it dispatches to silent/ducking/music_separated internally.
- `app.services.subtitle.srt.SubtitleCue(start: float, end: float, text: str)`, `app.services.subtitle.srt.generate_srt(cues: list[SubtitleCue]) -> str`.
- `app.services.video.subtitle_burn.burn_subtitles(video_path: str, srt_path: str, out_path: str, font_size: int = 28, font_color: str = "white", position: str = "bottom_center") -> None`.
- `app.services.video.subtitle_embed.embed_soft_subtitles(video_path: str, srt_path: str, out_path: str) -> None`.
- `app.services.video.mux.mux_video_with_audio(video_path: str, audio_path: str, out_path: str) -> None`.

---

### Task 1: `Project.background_volume` field + migration

**Files:**
- Modify: `backend/app/models/project.py`
- Create: `backend/tests/test_project_background_volume.py`

**Interfaces:**
- Produces: `Project.background_volume: float` (default `0.3`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_project_background_volume.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project


def test_project_defaults_background_volume_to_point_three():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)
        assert project.background_volume == 0.3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_project_background_volume.py -v`
Expected: FAIL — field doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/project.py  (add this field to the Project class, after audio_mode)
    background_volume: float = Field(default=0.3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_project_background_volume.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add background_volume to projects" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Also expose it in `ProjectUpdate`/`ProjectRead` schemas so Phase 8's UI can set it**

```python
# backend/app/schemas/project.py  (add to both ProjectUpdate and ProjectRead)
    background_volume: Optional[float] = None  # in ProjectUpdate
```

For `ProjectRead`, add `background_volume: float` (non-optional, since it always has a default).

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/project.py backend/app/schemas/project.py backend/tests/test_project_background_volume.py backend/alembic/versions/
git commit -m "feat(backend): add background_volume field to Project"
```

---

### Task 2: Silence generation + atempo helpers

**Files:**
- Create: `backend/app/services/audio/silence.py`
- Create: `backend/app/services/audio/atempo.py`
- Create: `backend/tests/test_silence.py`
- Create: `backend/tests/test_atempo.py`

**Interfaces:**
- Produces: `app.services.audio.silence.generate_silence(duration_sec: float, out_path: str) -> None`; `app.services.audio.atempo.apply_atempo(input_path: str, out_path: str, factor: float) -> None`, `app.services.audio.atempo.build_atempo_filter_chain(factor: float) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_silence.py
from app.services.audio.duration import probe_audio_duration
from app.services.audio.silence import generate_silence


def test_generate_silence_produces_correct_duration(tmp_path):
    out_path = str(tmp_path / "silence.wav")
    generate_silence(1.5, out_path)
    duration = probe_audio_duration(out_path)
    assert 1.4 <= duration <= 1.6
```

```python
# backend/tests/test_atempo.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_silence.py tests/test_atempo.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/silence.py
import subprocess


def generate_silence(duration_sec: float, out_path: str) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", str(duration_sec),
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

```python
# backend/app/services/audio/atempo.py
import subprocess

ATEMPO_MAX_PER_STAGE = 2.0
ATEMPO_MIN_PER_STAGE = 0.5


def build_atempo_filter_chain(factor: float) -> str:
    """ffmpeg's atempo filter only accepts [0.5, 2.0] per instance, so a
    factor outside that range must be split across chained instances."""
    if ATEMPO_MIN_PER_STAGE <= factor <= ATEMPO_MAX_PER_STAGE:
        return f"atempo={factor}"

    stages: list[float] = []
    remaining = factor
    while remaining > ATEMPO_MAX_PER_STAGE:
        stages.append(ATEMPO_MAX_PER_STAGE)
        remaining /= ATEMPO_MAX_PER_STAGE
    stages.append(round(remaining, 4))

    return ",".join(f"atempo={stage}" for stage in stages)


def apply_atempo(input_path: str, out_path: str, factor: float) -> None:
    filter_chain = build_atempo_filter_chain(factor)
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-filter:a", filter_chain, out_path],
        check=True,
        capture_output=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_silence.py tests/test_atempo.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/silence.py backend/app/services/audio/atempo.py backend/tests/test_silence.py backend/tests/test_atempo.py
git commit -m "feat(backend): add silence generation and atempo helpers"
```

---

### Task 3: Audio concatenation helper

**Files:**
- Create: `backend/app/services/audio/concat.py`
- Create: `backend/tests/test_concat.py`

**Interfaces:**
- Produces: `app.services.audio.concat.concat_audio_pieces(piece_paths: list[str], out_path: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_concat.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_concat.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/concat.py
import subprocess


def concat_audio_pieces(piece_paths: list[str], out_path: str) -> None:
    """Uses filter_complex concat (not the concat demuxer) since pieces may
    come from different encoders (edge-tts mp3, Gemini TTS wav, generated
    silence) and are re-decoded into a uniform PCM stream before joining."""
    if not piece_paths:
        raise ValueError("piece_paths must not be empty")

    inputs: list[str] = []
    for path in piece_paths:
        inputs += ["-i", path]

    stream_labels = "".join(f"[{i}:a]" for i in range(len(piece_paths)))
    filter_complex = f"{stream_labels}concat=n={len(piece_paths)}:v=0:a=1[out]"

    subprocess.run(
        [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_concat.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/concat.py backend/tests/test_concat.py
git commit -m "feat(backend): add multi-clip audio concatenation helper"
```

---

### Task 4: `assemble_dubbed_audio_track` — the full timing-sync assembly

**Files:**
- Create: `backend/app/services/audio/assemble.py`
- Create: `backend/tests/test_assemble.py`

**Interfaces:**
- Consumes: `probe_audio_duration`, `generate_silence`, `apply_atempo`, `concat_audio_pieces`.
- Produces: `SegmentAudioPlacement`, `assemble_dubbed_audio_track(placements, total_duration, out_path) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_assemble.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_assemble.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/assemble.py
import os
import shutil
import tempfile
from dataclasses import dataclass

from app.services.audio.atempo import apply_atempo
from app.services.audio.concat import concat_audio_pieces
from app.services.audio.duration import probe_audio_duration
from app.services.audio.silence import generate_silence

MIN_GAP_TO_PAD_SEC = 0.02
OVERFLOW_TOLERANCE_SEC = 0.05


@dataclass
class SegmentAudioPlacement:
    start_time: float
    end_time: float
    audio_path: str


def assemble_dubbed_audio_track(
    placements: list[SegmentAudioPlacement],
    total_duration: float,
    out_path: str,
) -> None:
    """Steps 2-3 of the spec's timing-sync order: place each (already
    rate-adjusted, from Phase 6) clip at its original start_time, use the
    natural gap before the next clip as padding, and apply atempo to force
    a clip that still overflows its allotted window (end_time - start_time)
    to fit exactly."""
    tmp_dir = tempfile.mkdtemp(prefix="assemble_")
    try:
        ordered = sorted(placements, key=lambda p: p.start_time)
        pieces: list[str] = []
        cursor = 0.0

        for i, placement in enumerate(ordered):
            gap = placement.start_time - cursor
            if gap > MIN_GAP_TO_PAD_SEC:
                silence_path = os.path.join(tmp_dir, f"silence_{i}.wav")
                generate_silence(gap, silence_path)
                pieces.append(silence_path)
                cursor += gap

            target = placement.end_time - placement.start_time
            actual = probe_audio_duration(placement.audio_path)

            if actual > target + OVERFLOW_TOLERANCE_SEC and target > 0:
                adjusted_path = os.path.join(tmp_dir, f"seg_{i}_atempo.wav")
                apply_atempo(placement.audio_path, adjusted_path, factor=actual / target)
                pieces.append(adjusted_path)
                cursor += target
            else:
                pieces.append(placement.audio_path)
                cursor += actual

        trailing_gap = total_duration - cursor
        if trailing_gap > MIN_GAP_TO_PAD_SEC:
            trailing_path = os.path.join(tmp_dir, "trailing_silence.wav")
            generate_silence(trailing_gap, trailing_path)
            pieces.append(trailing_path)

        concat_audio_pieces(pieces, out_path)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_assemble.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/assemble.py backend/tests/test_assemble.py
git commit -m "feat(backend): add assemble_dubbed_audio_track implementing timing-sync steps 2-3"
```

---

### Task 5: Demucs source separation wrapper

**Files:**
- Create: `backend/app/services/audio/demucs.py`
- Create: `backend/tests/test_demucs.py`

**Interfaces:**
- Produces: `DemucsResult(vocals_path: str, accompaniment_path: str)`, `separate_vocals(input_audio_path: str, out_dir: str) -> DemucsResult`, `DemucsError(Exception)`.

- [ ] **Step 1: Add dependency**

Add `"demucs>=4.0"` to `backend/pyproject.toml`'s `dependencies`. Run: `cd backend && pip install -e ".[dev]"`
Note: this pulls in `torch`; the backend Docker image (Python 3.12, per Phase 1) is where this actually needs to work — installing `torch`/`demucs` on the host's Python 3.14 may fail per the spec's documented Python-version mismatch, which is exactly why Phase 1 pinned Docker to 3.12.

- [ ] **Step 2: Write the failing test**

Demucs itself is not invoked in the unit test (it would download a multi-GB
model on first run) — the test verifies command construction and output-path
resolution via a mocked `subprocess.run`.

```python
# backend/tests/test_demucs.py
import os
from unittest.mock import patch

import pytest

from app.services.audio.demucs import DemucsError, separate_vocals


def test_separate_vocals_invokes_demucs_and_resolves_output_paths(tmp_path):
    input_path = str(tmp_path / "input.wav")
    with open(input_path, "wb") as f:
        f.write(b"fake-audio")
    out_dir = str(tmp_path / "out")

    def fake_run(cmd, **kwargs):
        # Simulate demucs writing its standard nested output structure.
        model_dir = os.path.join(out_dir, "htdemucs", "input")
        os.makedirs(model_dir, exist_ok=True)
        open(os.path.join(model_dir, "vocals.wav"), "wb").close()
        open(os.path.join(model_dir, "no_vocals.wav"), "wb").close()

        class FakeResult:
            returncode = 0

        return FakeResult()

    with patch("app.services.audio.demucs.subprocess.run", side_effect=fake_run) as mock_run:
        result = separate_vocals(input_path, out_dir)

    called_cmd = mock_run.call_args.args[0]
    assert called_cmd[0] == "demucs"
    assert "--two-stems=vocals" in called_cmd
    assert input_path in called_cmd

    assert result.vocals_path.endswith("vocals.wav")
    assert result.accompaniment_path.endswith("no_vocals.wav")
    assert os.path.exists(result.vocals_path)
    assert os.path.exists(result.accompaniment_path)


def test_separate_vocals_raises_on_missing_output(tmp_path):
    input_path = str(tmp_path / "input.wav")
    with open(input_path, "wb") as f:
        f.write(b"fake-audio")
    out_dir = str(tmp_path / "out")

    with patch("app.services.audio.demucs.subprocess.run"):
        with pytest.raises(DemucsError):
            separate_vocals(input_path, out_dir)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_demucs.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/services/audio/demucs.py
import os
import subprocess
from dataclasses import dataclass


class DemucsError(Exception):
    pass


@dataclass
class DemucsResult:
    vocals_path: str
    accompaniment_path: str


def separate_vocals(input_audio_path: str, out_dir: str) -> DemucsResult:
    os.makedirs(out_dir, exist_ok=True)

    subprocess.run(
        ["demucs", "--two-stems=vocals", "-o", out_dir, input_audio_path],
        check=True,
        capture_output=True,
    )

    basename = os.path.splitext(os.path.basename(input_audio_path))[0]
    model_dir = os.path.join(out_dir, "htdemucs", basename)
    vocals_path = os.path.join(model_dir, "vocals.wav")
    accompaniment_path = os.path.join(model_dir, "no_vocals.wav")

    if not (os.path.exists(vocals_path) and os.path.exists(accompaniment_path)):
        raise DemucsError(
            f"Demucs did not produce expected output under {model_dir}"
        )

    return DemucsResult(vocals_path=vocals_path, accompaniment_path=accompaniment_path)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_demucs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/audio/demucs.py backend/tests/test_demucs.py backend/pyproject.toml
git commit -m "feat(backend): add Demucs vocal/accompaniment separation wrapper"
```

---

### Task 6: Ducking mix + music-preserved mix + mode router

**Files:**
- Create: `backend/app/services/audio/ducking.py`
- Create: `backend/app/services/audio/mix.py`
- Create: `backend/tests/test_ducking.py`
- Create: `backend/tests/test_mix.py`

**Interfaces:**
- Produces: `duck_and_mix(original_audio_path, voice_path, out_path, background_volume) -> None`; `build_final_audio(audio_mode, voice_track_path, original_audio_path, background_volume, out_path) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_ducking.py
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
```

```python
# backend/tests/test_mix.py
from unittest.mock import patch

from app.services.audio.mix import build_final_audio


def test_silent_mode_just_copies_voice_track(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    with open(voice_path, "wb") as f:
        f.write(b"voice-bytes")
    out_path = str(tmp_path / "out.wav")

    build_final_audio(
        audio_mode="silent",
        voice_track_path=voice_path,
        original_audio_path=str(tmp_path / "unused.wav"),
        background_volume=0.3,
        out_path=out_path,
    )

    with open(out_path, "rb") as f:
        assert f.read() == b"voice-bytes"


def test_ducking_mode_calls_duck_and_mix(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    original_path = str(tmp_path / "original.wav")
    out_path = str(tmp_path / "out.wav")

    with patch("app.services.audio.mix.duck_and_mix") as mock_duck:
        build_final_audio(
            audio_mode="ducking",
            voice_track_path=voice_path,
            original_audio_path=original_path,
            background_volume=0.4,
            out_path=out_path,
        )

    mock_duck.assert_called_once_with(original_path, voice_path, out_path, 0.4)


def test_music_separated_mode_calls_demucs_then_mixes(tmp_path):
    voice_path = str(tmp_path / "voice.wav")
    original_path = str(tmp_path / "original.wav")
    out_path = str(tmp_path / "out.wav")

    with patch("app.services.audio.mix.separate_vocals") as mock_separate, patch(
        "app.services.audio.mix.mix_background_with_voice"
    ) as mock_mix:
        from app.services.audio.demucs import DemucsResult

        mock_separate.return_value = DemucsResult(
            vocals_path="/tmp/vocals.wav", accompaniment_path="/tmp/no_vocals.wav"
        )

        build_final_audio(
            audio_mode="music_separated",
            voice_track_path=voice_path,
            original_audio_path=original_path,
            background_volume=0.5,
            out_path=out_path,
        )

    mock_separate.assert_called_once()
    mock_mix.assert_called_once_with("/tmp/no_vocals.wav", voice_path, out_path, 0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_ducking.py tests/test_mix.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/ducking.py
import subprocess


def duck_and_mix(
    original_audio_path: str, voice_path: str, out_path: str, background_volume: float
) -> None:
    """Sidechain-compresses the original audio against the voice track (so
    it automatically quiets down while the new voice is speaking), then
    mixes the two together. `background_volume` sets the original track's
    baseline gain before compression."""
    filter_complex = (
        f"[0:a]volume={background_volume}[bg];"
        f"[bg][1:a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=200[ducked];"
        f"[ducked][1:a]amix=inputs=2:duration=first:weights=1 1[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", original_audio_path,
            "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

```python
# backend/app/services/audio/mix.py
import shutil
import tempfile

from app.services.audio.demucs import separate_vocals
from app.services.audio.ducking import duck_and_mix


def mix_background_with_voice(
    background_path: str, voice_path: str, out_path: str, background_volume: float
) -> None:
    import subprocess

    filter_complex = (
        f"[0:a]volume={background_volume}[bg];"
        f"[bg][1:a]amix=inputs=2:duration=first:weights=1 1[out]"
    )
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", background_path,
            "-i", voice_path,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            out_path,
        ],
        check=True,
        capture_output=True,
    )


def build_final_audio(
    audio_mode: str,
    voice_track_path: str,
    original_audio_path: str,
    background_volume: float,
    out_path: str,
) -> None:
    if audio_mode == "silent":
        shutil.copyfile(voice_track_path, out_path)
        return

    if audio_mode == "ducking":
        duck_and_mix(original_audio_path, voice_track_path, out_path, background_volume)
        return

    if audio_mode == "music_separated":
        tmp_dir = tempfile.mkdtemp(prefix="demucs_")
        demucs_result = separate_vocals(original_audio_path, tmp_dir)
        mix_background_with_voice(
            demucs_result.accompaniment_path, voice_track_path, out_path, background_volume
        )
        return

    raise ValueError(f"Unknown audio_mode: {audio_mode}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_ducking.py tests/test_mix.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/ducking.py backend/app/services/audio/mix.py backend/tests/test_ducking.py backend/tests/test_mix.py
git commit -m "feat(backend): add ducking mix, music-separated mix, and audio-mode router"
```

---

### Task 7: SRT subtitle generation

**Files:**
- Create: `backend/app/services/subtitle/__init__.py`
- Create: `backend/app/services/subtitle/srt.py`
- Create: `backend/tests/test_srt.py`

**Interfaces:**
- Produces: `SubtitleCue(start: float, end: float, text: str)`, `generate_srt(cues: list[SubtitleCue]) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_srt.py
from app.services.subtitle.srt import SubtitleCue, generate_srt


def test_generate_srt_formats_timestamps_and_numbering():
    cues = [
        SubtitleCue(start=0.0, end=2.5, text="Xin chào"),
        SubtitleCue(start=2.5, end=5.125, text="Thế giới"),
    ]

    srt = generate_srt(cues)

    assert srt == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "Xin chào\n"
        "\n"
        "2\n"
        "00:00:02,500 --> 00:00:05,125\n"
        "Thế giới\n"
        "\n"
    )


def test_generate_srt_handles_hour_boundary():
    cues = [SubtitleCue(start=3661.2, end=3662.0, text="Muộn rồi")]
    srt = generate_srt(cues)
    assert "01:01:01,200 --> 01:01:02,000" in srt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_srt.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/subtitle/__init__.py
```

```python
# backend/app/services/subtitle/srt.py
from dataclasses import dataclass


@dataclass
class SubtitleCue:
    start: float
    end: float
    text: str


def _format_timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def generate_srt(cues: list[SubtitleCue]) -> str:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n"
            f"{_format_timestamp(cue.start)} --> {_format_timestamp(cue.end)}\n"
            f"{cue.text}\n\n"
        )
    return "".join(blocks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_srt.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/subtitle/ backend/tests/test_srt.py
git commit -m "feat(backend): add SRT subtitle generation"
```

---

### Task 8: Subtitle burn-in and soft-embed

**Files:**
- Create: `backend/app/services/video/subtitle_burn.py`
- Create: `backend/app/services/video/subtitle_embed.py`
- Create: `backend/tests/test_subtitle_burn.py`
- Create: `backend/tests/test_subtitle_embed.py`

**Interfaces:**
- Produces: `burn_subtitles(video_path, srt_path, out_path, font_size=28, font_color="white", position="bottom_center") -> None`; `embed_soft_subtitles(video_path, srt_path, out_path) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_subtitle_burn.py
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
```

```python
# backend/tests/test_subtitle_embed.py
import subprocess

import pytest

from app.services.video.ffprobe import probe_video
from app.services.video.subtitle_embed import embed_soft_subtitles


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


def test_embed_soft_subtitles_produces_video_with_subtitle_stream(tiny_video, tiny_srt, tmp_path):
    out_path = str(tmp_path / "soft.mp4")
    embed_soft_subtitles(tiny_video, tiny_srt, out_path)

    result = probe_video(out_path)
    assert 1.5 <= result.duration_sec <= 2.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_subtitle_burn.py tests/test_subtitle_embed.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/video/subtitle_burn.py
import subprocess

POSITION_ALIGNMENT = {
    "bottom_center": 2,  # libass \an alignment codes
    "top_center": 8,
    "middle_center": 5,
}


def burn_subtitles(
    video_path: str,
    srt_path: str,
    out_path: str,
    font_size: int = 28,
    font_color: str = "white",
    position: str = "bottom_center",
) -> None:
    alignment = POSITION_ALIGNMENT.get(position, 2)
    # TikTok-style default: large text, black outline, centered.
    force_style = (
        f"FontSize={font_size},PrimaryColour=&H{_color_to_ass_hex(font_color)},"
        f"OutlineColour=&H000000,BorderStyle=1,Outline=2,Alignment={alignment}"
    )
    escaped_srt_path = srt_path.replace("\\", "/").replace(":", "\\:")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles={escaped_srt_path}:force_style='{force_style}'",
            "-c:a", "copy",
            out_path,
        ],
        check=True,
        capture_output=True,
    )


def _color_to_ass_hex(color_name: str) -> str:
    # ASS colors are &HBBGGRR (reverse byte order from typical RGB names).
    named = {
        "white": "FFFFFF",
        "yellow": "00FFFF",
        "black": "000000",
    }
    return named.get(color_name, "FFFFFF")
```

```python
# backend/app/services/video/subtitle_embed.py
import subprocess


def embed_soft_subtitles(video_path: str, srt_path: str, out_path: str) -> None:
    """Adds the SRT as a toggleable subtitle track (mov_text, MP4-compatible)
    without altering the video/audio streams."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", srt_path,
            "-map", "0:v", "-map", "0:a", "-map", "1:s",
            "-c:v", "copy", "-c:a", "copy",
            "-c:s", "mov_text",
            "-metadata:s:s:0", "language=vie",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_subtitle_burn.py tests/test_subtitle_embed.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/video/subtitle_burn.py backend/app/services/video/subtitle_embed.py backend/tests/test_subtitle_burn.py backend/tests/test_subtitle_embed.py
git commit -m "feat(backend): add subtitle burn-in and soft-embed"
```

---

### Task 9: Final video/audio mux

**Files:**
- Create: `backend/app/services/video/mux.py`
- Create: `backend/tests/test_mux.py`

**Interfaces:**
- Produces: `mux_video_with_audio(video_path: str, audio_path: str, out_path: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_mux.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_mux.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/video/mux.py
import subprocess


def mux_video_with_audio(video_path: str, audio_path: str, out_path: str) -> None:
    """Copies the video stream unchanged (no re-encode, no quality loss —
    per spec's default resolution-copy behavior) and replaces the audio
    with the given track, re-encoded to AAC for MP4 compatibility."""
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_mux.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-7 tests pass (Demucs's own binary is never actually invoked in CI — that test path is mocked, per Task 5).

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/video/mux.py backend/tests/test_mux.py
git commit -m "feat(backend): add final video/audio mux"
```

---

## Definition of Done for Phase 7

- [ ] `cd backend && pytest` passes (all Phase 1-7 tests).
- [ ] Manually, inside the backend Docker container (where `ffmpeg` and `demucs` are actually installed): run `separate_vocals` on a short real audio clip with background music and confirm `vocals.wav`/`no_vocals.wav` sound right.
- [ ] Manually: assemble a fake multi-segment dubbed track (a few short generated tones with gaps) end-to-end through `assemble_dubbed_audio_track`, `build_final_audio` (try all three audio modes), `mux_video_with_audio`, and both subtitle functions, and play the result to confirm it sounds/looks correct.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 8.
