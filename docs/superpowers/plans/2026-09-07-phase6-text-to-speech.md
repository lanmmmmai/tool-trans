# Phase 6: Text-to-Speech — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user pick a voice per detected speaker (with preview), then generate dubbed audio for every translated segment using edge-tts (falling back — on explicit user confirmation, not automatically — to Gemini TTS when edge-tts fails), with per-segment speaking-rate adjustment as the first step of timing sync.

**Architecture:** `Voice` and `DubbedSegment` models; a `tts` service package with a `TTSEngine` interface and `EdgeTTSEngine`/`GeminiTTSEngine` implementations, each exposing a small hardcoded voice catalog; a two-pass rate-adjusted synthesis helper that measures natural duration then re-synthesizes at an adjusted rate to approach the original segment's duration; a `dub_task` Celery job that fails fast (does not silently fall back) when an engine errors, so the frontend can prompt the user; voice catalog/preview/assignment endpoints; a voice-selection UI.

**Tech Stack:** FastAPI, Celery, `edge-tts` (Python package), Gemini TTS (via `google-genai`), ffprobe (for measuring generated audio duration), Next.js.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Primary TTS engine: **edge-tts** (spec §Text-to-Speech). Vietnamese voices: `vi-VN-HoaiMyNeural` (female), `vi-VN-NamMinhNeural` (male).
- On edge-tts failure, the user must be **notified and asked** before falling back to **Gemini TTS** — never a silent automatic switch (spec §Text-to-Speech, discovery Q55-C).
- Detected speakers are auto-mapped to distinct voices; the user can override the mapping and adjust speed/pitch per voice (spec §Text-to-Speech).
- No voice cloning (spec §9 Out of Scope).
- Timing sync step 1 (of the 3-step order in spec §Đồng bộ thời gian) is TTS speaking-rate adjustment — implemented here as a two-pass synthesize-measure-resynthesize routine. Steps 2 (silence padding) and 3 (`atempo`) are Phase 7's concern, applied on top of what this phase produces.
- Auth is still the Phase-2..5 stub (`get_current_user_id`).

## Established Interfaces (produced here, consumed by later phases)

- `app.models.voice.Voice`, `app.models.dubbed_segment.DubbedSegment` — SQLModel tables (fields per spec §5).
- `app.services.tts.base.TTSEngine` — `synthesize(text: str, voice_id: str, speed: float, out_path: str) -> None`; `list_voices() -> list[VoiceCatalogEntry]`. `VoiceCatalogEntry(voice_id: str, name: str, gender: str, engine: str)`. `TTSProviderError(Exception)`.
- `app.services.tts.edge_tts_engine.EdgeTTSEngine(TTSEngine)`, `app.services.tts.gemini_tts_engine.GeminiTTSEngine(TTSEngine)`.
- `app.services.audio.duration.probe_audio_duration(path: str) -> float` — reused by Phase 7's sync logic.
- `app.services.tts.sync.synthesize_segment_with_rate_adjustment(engine: TTSEngine, text: str, voice_id: str, target_duration: float, out_path: str) -> float` (returns the final generated duration) — **this is the function Phase 8's per-segment "regenerate" endpoint calls directly.**
- `app.workers.dub.dub_task(project_id: str)` — Celery task; fails fast (job status `failed`, `error_message` names the failing engine and speaker) rather than auto-switching engines, so the frontend can prompt the user per spec.
- `GET /api/voices/catalog`, `GET /api/voices/preview`, `PUT /api/projects/{id}/voices`, `POST /api/projects/{id}/dub` — the last two are re-callable: after a failed job, the frontend updates the failing speaker's `Voice.engine` via `PUT .../voices` and calls `POST .../dub` again.

---

### Task 1: `Voice` and `DubbedSegment` models + migration

**Files:**
- Create: `backend/app/models/voice.py`
- Create: `backend/app/models/dubbed_segment.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_voice_models.py`

**Interfaces:**
- Produces: `Voice`, `DubbedSegment` SQLModel classes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_models.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.dubbed_segment import DubbedSegment
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.voice import Voice


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_voice_with_defaults():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        voice = Voice(
            project_id=project.id,
            speaker_label="speaker_1",
            engine="edge_tts",
            voice_id="vi-VN-HoaiMyNeural",
        )
        session.add(voice)
        session.commit()
        session.refresh(voice)

        assert voice.speed == 1.0
        assert voice.pitch == 0.0


def test_create_dubbed_segment():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        seg = TranscriptSegment(
            project_id=project.id, seq_index=0, start_time=0, end_time=2,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)

        dubbed = DubbedSegment(
            segment_id=seg.id, audio_storage_path="dubbed/x.mp3",
            duration_sec=2.1, status="done",
        )
        session.add(dubbed)
        session.commit()
        session.refresh(dubbed)
        assert dubbed.id is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_voice_models.py -v`
Expected: FAIL — models don't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/voice.py
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Voice(SQLModel, table=True):
    __tablename__ = "voices"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    speaker_label: str
    engine: str  # "edge_tts" | "gemini_tts"
    voice_id: str
    speed: float = Field(default=1.0)
    pitch: float = Field(default=0.0)
```

```python
# backend/app/models/dubbed_segment.py
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class DubbedSegment(SQLModel, table=True):
    __tablename__ = "dubbed_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    segment_id: str = Field(foreign_key="transcript_segments.id", unique=True, index=True)
    audio_storage_path: str
    duration_sec: float
    status: str = Field(default="pending")  # "pending" | "done" | "failed"
    generated_at: Optional[datetime] = None
```

```python
# backend/app/models/__init__.py
from app.models.dubbed_segment import DubbedSegment  # noqa: F401
from app.models.glossary_term import GlossaryTerm  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.transcript_segment import TranscriptSegment  # noqa: F401
from app.models.translation_segment import TranslationSegment  # noqa: F401
from app.models.video import Video  # noqa: F401
from app.models.voice import Voice  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_voice_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add voices and dubbed_segments tables" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/voice.py backend/app/models/dubbed_segment.py backend/app/models/__init__.py backend/tests/test_voice_models.py backend/alembic/versions/
git commit -m "feat(backend): add Voice and DubbedSegment models + migration"
```

---

### Task 2: Audio duration prober

**Files:**
- Create: `backend/app/services/audio/duration.py`
- Create: `backend/tests/test_audio_duration.py`

**Interfaces:**
- Produces: `app.services.audio.duration.probe_audio_duration(path: str) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_audio_duration.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_audio_duration.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/duration.py
import json
import subprocess


def probe_audio_duration(path: str) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json", "-show_format",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return float(data["format"]["duration"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_audio_duration.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/duration.py backend/tests/test_audio_duration.py
git commit -m "feat(backend): add audio duration probe helper"
```

---

### Task 3: `TTSEngine` interface + edge-tts and Gemini TTS implementations

**Files:**
- Create: `backend/app/services/tts/__init__.py`
- Create: `backend/app/services/tts/base.py`
- Create: `backend/app/services/tts/edge_tts_engine.py`
- Create: `backend/app/services/tts/gemini_tts_engine.py`
- Create: `backend/tests/test_tts_engines.py`

**Interfaces:**
- Produces: `TTSEngine` (ABC), `VoiceCatalogEntry`, `TTSProviderError`; `EdgeTTSEngine`, `GeminiTTSEngine`.

- [ ] **Step 1: Add dependencies**

Add to `backend/pyproject.toml`'s `dependencies`: `"edge-tts>=6.1"`.
(`google-genai` was already added in Phase 5 for translation and is reused here.)
Run: `cd backend && pip install -e ".[dev]"`

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_tts_engines.py
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.tts.base import TTSProviderError
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine


def test_edge_tts_list_voices_returns_vietnamese_voices():
    engine = EdgeTTSEngine()
    voices = engine.list_voices()
    voice_ids = {v.voice_id for v in voices}
    assert "vi-VN-HoaiMyNeural" in voice_ids
    assert "vi-VN-NamMinhNeural" in voice_ids
    assert all(v.engine == "edge_tts" for v in voices)


def test_edge_tts_synthesize_converts_speed_to_rate_string(tmp_path):
    engine = EdgeTTSEngine()
    out_path = str(tmp_path / "out.mp3")

    with patch("app.services.tts.edge_tts_engine.edge_tts.Communicate") as MockCommunicate:
        mock_instance = MockCommunicate.return_value
        mock_instance.save = AsyncMock()

        engine.synthesize("Xin chào", "vi-VN-HoaiMyNeural", speed=1.2, out_path=out_path)

        MockCommunicate.assert_called_once_with(
            "Xin chào", "vi-VN-HoaiMyNeural", rate="+20%"
        )
        mock_instance.save.assert_awaited_once_with(out_path)


def test_edge_tts_synthesize_raises_provider_error_on_failure(tmp_path):
    engine = EdgeTTSEngine()
    out_path = str(tmp_path / "out.mp3")

    with patch("app.services.tts.edge_tts_engine.edge_tts.Communicate") as MockCommunicate:
        mock_instance = MockCommunicate.return_value
        mock_instance.save = AsyncMock(side_effect=Exception("network unreachable"))

        with pytest.raises(TTSProviderError):
            engine.synthesize("Xin chào", "vi-VN-HoaiMyNeural", speed=1.0, out_path=out_path)


def test_gemini_tts_list_voices_returns_catalog():
    engine = GeminiTTSEngine(api_key="fake")
    voices = engine.list_voices()
    assert len(voices) > 0
    assert all(v.engine == "gemini_tts" for v in voices)


def test_gemini_tts_synthesize_writes_wav_from_pcm(tmp_path):
    engine = GeminiTTSEngine(api_key="fake")
    out_path = str(tmp_path / "out.wav")

    fake_pcm = b"\x00\x01" * 1000  # 16-bit PCM samples

    with patch("app.services.tts.gemini_tts_engine.genai.Client") as MockClient:
        mock_client = MockClient.return_value
        mock_part = MagicMock()
        mock_part.inline_data.data = fake_pcm
        mock_response = MagicMock()
        mock_response.candidates = [MagicMock(content=MagicMock(parts=[mock_part]))]
        mock_client.models.generate_content.return_value = mock_response

        engine.synthesize("Xin chào", "Kore", speed=1.0, out_path=out_path)

    import wave

    with wave.open(out_path, "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24000
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tts_engines.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/services/tts/__init__.py
```

```python
# backend/app/services/tts/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class VoiceCatalogEntry:
    voice_id: str
    name: str
    gender: str
    engine: str


class TTSProviderError(Exception):
    pass


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_voices(self) -> list[VoiceCatalogEntry]:
        raise NotImplementedError
```

```python
# backend/app/services/tts/edge_tts_engine.py
import asyncio

import edge_tts

from app.services.tts.base import TTSEngine, TTSProviderError, VoiceCatalogEntry

VOICE_CATALOG = [
    VoiceCatalogEntry(voice_id="vi-VN-HoaiMyNeural", name="Hoài My (nữ)", gender="female", engine="edge_tts"),
    VoiceCatalogEntry(voice_id="vi-VN-NamMinhNeural", name="Nam Minh (nam)", gender="male", engine="edge_tts"),
]


def _speed_to_rate_string(speed: float) -> str:
    percent = round((speed - 1.0) * 100)
    sign = "+" if percent >= 0 else ""
    return f"{sign}{percent}%"


class EdgeTTSEngine(TTSEngine):
    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        rate = _speed_to_rate_string(speed)
        try:
            communicate = edge_tts.Communicate(text, voice_id, rate=rate)
            asyncio.run(communicate.save(out_path))
        except Exception as exc:
            raise TTSProviderError(f"edge-tts failed for voice {voice_id}: {exc}") from exc

    def list_voices(self) -> list[VoiceCatalogEntry]:
        return VOICE_CATALOG
```

```python
# backend/app/services/tts/gemini_tts_engine.py
import wave

from google import genai
from google.genai import types

from app.services.tts.base import TTSEngine, TTSProviderError, VoiceCatalogEntry

VOICE_CATALOG = [
    VoiceCatalogEntry(voice_id="Kore", name="Kore", gender="female", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Puck", name="Puck", gender="male", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Charon", name="Charon", gender="male", engine="gemini_tts"),
    VoiceCatalogEntry(voice_id="Leda", name="Leda", gender="female", engine="gemini_tts"),
]

MODEL_NAME = "gemini-2.5-flash-preview-tts"
SAMPLE_RATE_HZ = 24000


class GeminiTTSEngine(TTSEngine):
    """Gemini TTS has no numeric speed/rate parameter — speed is applied as
    a best-effort natural-language instruction, per the spec's documented
    caveat that Gemini TTS cannot hit an exact target duration."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def synthesize(self, text: str, voice_id: str, speed: float, out_path: str) -> None:
        prompt = text
        if speed > 1.05:
            prompt = f"(nói nhanh hơn một chút) {text}"
        elif speed < 0.95:
            prompt = f"(nói chậm hơn một chút) {text}"

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_id)
                        )
                    ),
                ),
            )
            pcm_data = response.candidates[0].content.parts[0].inline_data.data
        except Exception as exc:
            raise TTSProviderError(f"Gemini TTS failed for voice {voice_id}: {exc}") from exc

        with wave.open(out_path, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(SAMPLE_RATE_HZ)
            wav_file.writeframes(pcm_data)

    def list_voices(self) -> list[VoiceCatalogEntry]:
        return VOICE_CATALOG
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tts_engines.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/tts/ backend/tests/test_tts_engines.py backend/pyproject.toml
git commit -m "feat(backend): add TTSEngine interface with edge-tts and Gemini TTS implementations"
```

---

### Task 4: Two-pass rate-adjusted synthesis

**Files:**
- Create: `backend/app/services/tts/sync.py`
- Create: `backend/tests/test_tts_sync.py`

**Interfaces:**
- Produces: `app.services.tts.sync.synthesize_segment_with_rate_adjustment(engine, text, voice_id, target_duration, out_path) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_tts_sync.py
from unittest.mock import MagicMock, patch

from app.services.tts.sync import synthesize_segment_with_rate_adjustment


def test_no_resynthesis_needed_when_first_pass_fits():
    mock_engine = MagicMock()

    with patch("app.services.tts.sync.probe_audio_duration", return_value=2.0):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Xin chào",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=2.5,  # natural audio (2.0s) already fits inside target
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 2.0
    assert mock_engine.synthesize.call_count == 1
    assert mock_engine.synthesize.call_args.kwargs["speed"] == 1.0


def test_resynthesizes_faster_when_too_long():
    mock_engine = MagicMock()

    with patch(
        "app.services.tts.sync.probe_audio_duration", side_effect=[4.0, 2.6]
    ):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Một câu khá dài",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=2.5,
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 2.6
    assert mock_engine.synthesize.call_count == 2
    first_speed = mock_engine.synthesize.call_args_list[0].kwargs["speed"]
    second_speed = mock_engine.synthesize.call_args_list[1].kwargs["speed"]
    assert first_speed == 1.0
    assert second_speed == 1.3  # 4.0 / 2.5 = 1.6, clamped to the 1.3 cap


def test_does_not_slow_down_when_shorter_than_target():
    mock_engine = MagicMock()

    with patch("app.services.tts.sync.probe_audio_duration", return_value=1.0):
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=mock_engine,
            text="Ngắn",
            voice_id="vi-VN-HoaiMyNeural",
            target_duration=3.0,
            out_path="/tmp/out.mp3",
        )

    assert final_duration == 1.0
    assert mock_engine.synthesize.call_count == 1  # left for silence padding in Phase 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_tts_sync.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/tts/sync.py
from app.services.audio.duration import probe_audio_duration
from app.services.tts.base import TTSEngine

MAX_SPEED_MULTIPLIER = 1.3


def synthesize_segment_with_rate_adjustment(
    engine: TTSEngine,
    text: str,
    voice_id: str,
    target_duration: float,
    out_path: str,
) -> float:
    """Pass 1: synthesize at normal rate, measure it. Pass 2: if the audio
    ran longer than the original segment's duration, resynthesize at a
    faster rate (capped at 1.3x to avoid unnatural-sounding speech) and
    measure again. If it's already shorter than or equal to the target,
    leave it as-is — the gap becomes slack for Phase 7's silence padding.
    Anything still too long after the cap is handled by Phase 7's atempo
    step, per spec's documented 3-step correction order."""
    engine.synthesize(text, voice_id, speed=1.0, out_path=out_path)
    natural_duration = probe_audio_duration(out_path)

    if natural_duration <= target_duration:
        return natural_duration

    speed = min(natural_duration / target_duration, MAX_SPEED_MULTIPLIER)
    engine.synthesize(text, voice_id, speed=speed, out_path=out_path)
    return probe_audio_duration(out_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_tts_sync.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tts/sync.py backend/tests/test_tts_sync.py
git commit -m "feat(backend): add two-pass rate-adjusted TTS synthesis"
```

---

### Task 5: Voice catalog + preview endpoints

**Files:**
- Create: `backend/app/api/voices.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_voices_catalog_api.py`

**Interfaces:**
- Produces: `GET /api/voices/catalog` (returns both engines' catalogs), `GET /api/voices/preview?engine=&voice_id=` (returns `audio/mpeg` or `audio/wav` bytes — a short canned Vietnamese sample synthesized on the fly).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voices_catalog_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_get_voice_catalog_returns_both_engines():
    resp = client.get("/api/voices/catalog")
    assert resp.status_code == 200
    body = resp.json()
    engines = {v["engine"] for v in body}
    assert engines == {"edge_tts", "gemini_tts"}


def test_get_voice_preview_returns_audio_bytes():
    with patch("app.api.voices.EdgeTTSEngine") as MockEngine:
        def fake_synthesize(text, voice_id, speed, out_path):
            with open(out_path, "wb") as f:
                f.write(b"fake-mp3-bytes")

        MockEngine.return_value.synthesize.side_effect = fake_synthesize

        resp = client.get(
            "/api/voices/preview", params={"engine": "edge_tts", "voice_id": "vi-VN-HoaiMyNeural"}
        )

    assert resp.status_code == 200
    assert resp.content == b"fake-mp3-bytes"
    assert resp.headers["content-type"].startswith("audio/")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_voices_catalog_api.py -v`
Expected: FAIL — router doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/voices.py
import os
import tempfile

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from app.core.config import settings
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine

router = APIRouter(prefix="/api/voices", tags=["voices"])

PREVIEW_TEXT = "Xin chào, đây là giọng đọc mẫu."


class VoiceCatalogEntryRead(BaseModel):
    voice_id: str
    name: str
    gender: str
    engine: str


def _get_engine(engine_name: str):
    if engine_name == "gemini_tts":
        return GeminiTTSEngine(api_key=settings.gemini_api_key)
    if engine_name == "edge_tts":
        return EdgeTTSEngine()
    raise HTTPException(status_code=400, detail=f"Unknown engine: {engine_name}")


@router.get("/catalog", response_model=list[VoiceCatalogEntryRead])
def get_voice_catalog():
    edge = EdgeTTSEngine().list_voices()
    gemini = GeminiTTSEngine(api_key=settings.gemini_api_key).list_voices()
    return [
        VoiceCatalogEntryRead(voice_id=v.voice_id, name=v.name, gender=v.gender, engine=v.engine)
        for v in [*edge, *gemini]
    ]


@router.get("/preview")
def get_voice_preview(engine: str = Query(...), voice_id: str = Query(...)):
    tts_engine = _get_engine(engine)
    suffix = ".wav" if engine == "gemini_tts" else ".mp3"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = tmp.name

    try:
        tts_engine.synthesize(PREVIEW_TEXT, voice_id, speed=1.0, out_path=tmp_path)
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()
    finally:
        os.remove(tmp_path)

    media_type = "audio/wav" if suffix == ".wav" else "audio/mpeg"
    return Response(content=audio_bytes, media_type=media_type)
```

```python
# backend/app/main.py  (add to existing file)
from app.api.voices import router as voices_router

app.include_router(voices_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_voices_catalog_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/voices.py backend/app/main.py backend/tests/test_voices_catalog_api.py
git commit -m "feat(backend): add voice catalog and preview endpoints"
```

---

### Task 6: `PUT /projects/{id}/voices` — speaker→voice assignment

**Files:**
- Create: `backend/app/api/project_voices.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_project_voices_api.py`

**Interfaces:**
- Produces: `PUT /api/projects/{project_id}/voices` — body `list[{"speaker_label": str, "engine": str, "voice_id": str, "speed": float, "pitch": float}]`; replaces all existing `Voice` rows for the project with the given list. `GET /api/projects/{project_id}/voices` to read back the current assignment (needed by the frontend to pre-fill auto-detected speakers).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_project_voices_api.py
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def create_project():
    resp = client.post(
        "/api/projects",
        json={
            "title": "Voices test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_put_voices_replaces_assignment():
    project_id = create_project()

    resp = client.put(
        f"/api/projects/{project_id}/voices",
        json=[
            {
                "speaker_label": "speaker_1", "engine": "edge_tts",
                "voice_id": "vi-VN-HoaiMyNeural", "speed": 1.0, "pitch": 0.0,
            },
            {
                "speaker_label": "speaker_2", "engine": "edge_tts",
                "voice_id": "vi-VN-NamMinhNeural", "speed": 1.1, "pitch": 0.0,
            },
        ],
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    get_resp = client.get(f"/api/projects/{project_id}/voices")
    assert len(get_resp.json()) == 2

    # Replacing again should fully overwrite, not append
    resp2 = client.put(
        f"/api/projects/{project_id}/voices",
        json=[
            {
                "speaker_label": "speaker_1", "engine": "gemini_tts",
                "voice_id": "Kore", "speed": 1.0, "pitch": 0.0,
            },
        ],
    )
    assert resp2.status_code == 200
    get_resp2 = client.get(f"/api/projects/{project_id}/voices")
    assert len(get_resp2.json()) == 1
    assert get_resp2.json()[0]["engine"] == "gemini_tts"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_project_voices_api.py -v`
Expected: FAIL — router doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/project_voices.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.project import Project
from app.models.voice import Voice

router = APIRouter(prefix="/api/projects", tags=["voices"])


class VoiceAssignment(BaseModel):
    speaker_label: str
    engine: str
    voice_id: str
    speed: float = 1.0
    pitch: float = 0.0


class VoiceRead(BaseModel):
    id: str
    project_id: str
    speaker_label: str
    engine: str
    voice_id: str
    speed: float
    pitch: float

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.get("/{project_id}/voices", response_model=list[VoiceRead])
def get_project_voices(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)
    return session.exec(select(Voice).where(Voice.project_id == project_id)).all()


@router.put("/{project_id}/voices", response_model=list[VoiceRead])
def set_project_voices(
    project_id: str,
    payload: list[VoiceAssignment],
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    existing = session.exec(select(Voice).where(Voice.project_id == project_id)).all()
    for voice in existing:
        session.delete(voice)
    session.commit()

    created = []
    for assignment in payload:
        voice = Voice(project_id=project_id, **assignment.model_dump())
        session.add(voice)
        created.append(voice)
    session.commit()
    for voice in created:
        session.refresh(voice)

    return created
```

```python
# backend/app/main.py  (add to existing file)
from app.api.project_voices import router as project_voices_router

app.include_router(project_voices_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_project_voices_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-6 tests pass so far.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/project_voices.py backend/app/main.py backend/tests/test_project_voices_api.py
git commit -m "feat(backend): add speaker-to-voice assignment endpoints"
```

---

### Task 7: `dub_task` Celery task (fail-fast, no silent fallback)

**Files:**
- Create: `backend/app/workers/dub.py`
- Modify: `backend/app/core/celery_app.py`
- Create: `backend/tests/test_dub_task.py`

**Interfaces:**
- Consumes: `Voice`, `TranscriptSegment`, `TranslationSegment`, `DubbedSegment`, `synthesize_segment_with_rate_adjustment`, `EdgeTTSEngine`/`GeminiTTSEngine`, `get_r2_client`, `Job`, `ws_manager`.
- Produces: `app.workers.dub.dub_task(project_id: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_dub_task.py
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.dubbed_segment import DubbedSegment
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice
from app.services.tts.base import TTSProviderError


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    seg = TranscriptSegment(
        project_id=project.id, seq_index=0, start_time=0, end_time=2,
        speaker_label="speaker_1", source_text="Hello",
    )
    session.add(seg)
    session.commit()
    session.refresh(seg)

    session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
    session.add(Voice(project_id=project.id, speaker_label="speaker_1", engine="edge_tts", voice_id="vi-VN-HoaiMyNeural"))

    job = Job(project_id=project.id, job_type="dub")
    session.add(job)
    session.commit()
    session.refresh(job)

    return project, seg, job


def test_dub_task_creates_dubbed_segment_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project, seg, job = seed(session)

    with patch("app.workers.dub.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.dub.get_r2_client"
    ), patch("app.workers.dub.synthesize_segment_with_rate_adjustment", return_value=1.9), patch(
        "app.workers.dub.broadcast_sync"
    ):
        from app.workers.dub import dub_task

        dub_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "done"

        dubbed = session.exec(select(DubbedSegment)).all()
        assert len(dubbed) == 1
        assert dubbed[0].duration_sec == 1.9
        assert dubbed[0].status == "done"


def test_dub_task_fails_fast_without_auto_fallback_on_tts_error():
    engine = make_engine()
    with Session(engine) as session:
        project, seg, job = seed(session)

    with patch("app.workers.dub.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.dub.get_r2_client"
    ), patch(
        "app.workers.dub.synthesize_segment_with_rate_adjustment",
        side_effect=TTSProviderError("edge-tts unreachable"),
    ), patch("app.workers.dub.broadcast_sync") as mock_broadcast:
        from app.workers.dub import dub_task

        dub_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "failed"
        assert "edge-tts unreachable" in refreshed_job.error_message
        assert "speaker_1" in refreshed_job.error_message

        # no silent switch to another engine happened
        dubbed = session.exec(select(DubbedSegment)).all()
        assert len(dubbed) == 0

    # the frontend needs to know a fallback is offerable
    broadcast_payload = mock_broadcast.call_args_list[-1].args[1]
    assert broadcast_payload["can_retry_with_fallback"] is True
    assert broadcast_payload["failed_speaker"] == "speaker_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_dub_task.py -v`
Expected: FAIL — `app.workers.dub` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/dub.py
import asyncio
import os
import tempfile
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.storage import get_r2_client
from app.core.ws_manager import ws_manager
from app.db.session import engine
from app.models.dubbed_segment import DubbedSegment
from app.models.job import Job
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice
from app.services.tts.base import TTSProviderError
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine
from app.services.tts.sync import synthesize_segment_with_rate_adjustment


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    asyncio.run(ws_manager.broadcast(project_id, message))


def _build_tts_engine(engine_name: str):
    if engine_name == "gemini_tts":
        return GeminiTTSEngine(api_key=settings.gemini_api_key)
    return EdgeTTSEngine()


def _effective_translated_text(translation: TranslationSegment) -> str:
    return translation.translated_text_edited or translation.translated_text


@celery_app.task(name="app.workers.dub.dub_task")
def dub_task(project_id: str) -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "dub")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "synthesizing_speech"
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": "synthesizing_speech", "progress_pct": 5})

    try:
        rows = session.exec(
            select(TranscriptSegment, TranslationSegment)
            .join(TranslationSegment, TranslationSegment.segment_id == TranscriptSegment.id)
            .where(TranscriptSegment.project_id == project_id)
            .order_by(TranscriptSegment.seq_index)
        ).all()

        voices_by_speaker = {
            v.speaker_label: v
            for v in session.exec(select(Voice).where(Voice.project_id == project_id)).all()
        }

        r2_client = get_r2_client()
        total = max(len(rows), 1)

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, (transcript, translation) in enumerate(rows):
                voice = voices_by_speaker.get(transcript.speaker_label)
                if voice is None:
                    raise RuntimeError(f"No voice assigned for {transcript.speaker_label}")

                tts_engine = _build_tts_engine(voice.engine)
                out_path = os.path.join(tmp_dir, f"{transcript.id}.mp3")
                target_duration = transcript.end_time - transcript.start_time

                try:
                    final_duration = synthesize_segment_with_rate_adjustment(
                        engine=tts_engine,
                        text=_effective_translated_text(translation),
                        voice_id=voice.voice_id,
                        target_duration=target_duration,
                        out_path=out_path,
                    )
                except TTSProviderError as exc:
                    job.status = "failed"
                    job.error_message = (
                        f"{voice.engine} failed for speaker {transcript.speaker_label}: {exc}"
                    )
                    job.finished_at = datetime.now(timezone.utc)
                    session.add(job)
                    session.commit()
                    broadcast_sync(
                        project_id,
                        {
                            "status": "failed",
                            "error": job.error_message,
                            "can_retry_with_fallback": True,
                            "failed_speaker": transcript.speaker_label,
                            "failed_engine": voice.engine,
                        },
                    )
                    return

                key = f"dubbed/{project_id}/{transcript.id}.mp3"
                r2_client.upload_file(out_path, key)

                session.add(
                    DubbedSegment(
                        segment_id=transcript.id,
                        audio_storage_path=key,
                        duration_sec=final_duration,
                        status="done",
                        generated_at=datetime.now(timezone.utc),
                    )
                )
                session.commit()

                progress = int(((index + 1) / total) * 90) + 5
                job.progress_pct = progress
                session.add(job)
                session.commit()
                broadcast_sync(
                    project_id,
                    {"status": "running", "step": "synthesizing_speech", "progress_pct": progress},
                )

        job.status = "done"
        job.progress_pct = 100
        job.current_step = "done"
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "done", "progress_pct": 100})
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error_message = str(exc)
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "failed", "error": str(exc)})
    finally:
        session.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_dub_task.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Register the task module with Celery**

```python
# backend/app/core/celery_app.py  (update include list)
celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.ping",
        "app.workers.transcribe",
        "app.workers.translate",
        "app.workers.dub",
    ],
)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/dub.py backend/app/core/celery_app.py backend/tests/test_dub_task.py
git commit -m "feat(backend): add dub_task Celery job with fail-fast TTS error handling"
```

---

### Task 8: `POST /projects/{id}/dub` endpoint

**Files:**
- Create: `backend/app/api/dub.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_dub_api.py`

**Interfaces:**
- Produces: `POST /api/projects/{project_id}/dub` — enqueues `dub_task`, returns the `Job`. Re-callable after a failure once the frontend has updated the failing speaker's voice via `PUT .../voices`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_dub_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def test_start_dub_enqueues_task():
    create_resp = client.post(
        "/api/projects",
        json={
            "title": "Dub test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    project_id = create_resp.json()["id"]

    with patch("app.api.dub.dub_task") as mock_task:
        resp = client.post(f"/api/projects/{project_id}/dub")

    assert resp.status_code == 202, resp.text
    assert resp.json()["job_type"] == "dub"
    mock_task.delay.assert_called_once_with(project_id=project_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_dub_api.py -v`
Expected: FAIL — router doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/dub.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.workers.dub import dub_task

router = APIRouter(prefix="/api/projects", tags=["dub"])


class JobRead(BaseModel):
    id: str
    project_id: str
    job_type: str
    status: str
    progress_pct: float
    current_step: str | None
    error_message: str | None

    class Config:
        from_attributes = True


@router.post("/{project_id}/dub", response_model=JobRead, status_code=202)
def start_dub(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")

    job = Job(project_id=project_id, job_type="dub")
    session.add(job)
    project.status = "dubbing"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(job)

    dub_task.delay(project_id=project_id)

    return job
```

```python
# backend/app/main.py  (add to existing file)
from app.api.dub import router as dub_router

app.include_router(dub_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_dub_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/dub.py backend/app/main.py backend/tests/test_dub_api.py
git commit -m "feat(backend): add POST /projects/{id}/dub endpoint"
```

---

### Task 9: Frontend — voice selection + dubbing progress with fallback prompt

**Files:**
- Create: `frontend/app/projects/[id]/voices/page.tsx`
- Create: `frontend/app/projects/[id]/dub/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces: `lib/api.ts` exports `getVoiceCatalog()`, `getProjectVoices(projectId)`, `setProjectVoices(projectId, assignments)`, `previewVoiceUrl(engine, voiceId)`, `startDub(projectId)`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add)
it("setProjectVoices PUTs the assignment list", async () => {
  const { setProjectVoices } = await import("./api");
  const assignments = [
    { speaker_label: "speaker_1", engine: "edge_tts", voice_id: "vi-VN-HoaiMyNeural", speed: 1, pitch: 0 },
  ];
  await setProjectVoices("proj-1", assignments);
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/projects/proj-1/voices",
    expect.objectContaining({ method: "PUT", body: JSON.stringify(assignments) })
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `setProjectVoices` not exported.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/types.ts  (append)
export interface VoiceCatalogEntry {
  voice_id: string;
  name: string;
  gender: string;
  engine: string;
}

export interface VoiceAssignment {
  speaker_label: string;
  engine: string;
  voice_id: string;
  speed: number;
  pitch: number;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { VoiceAssignment, VoiceCatalogEntry } from "./types";

export async function getVoiceCatalog(): Promise<VoiceCatalogEntry[]> {
  const res = await apiFetch("/api/voices/catalog");
  if (!res.ok) throw new Error("Failed to load voice catalog");
  return res.json();
}

export function previewVoiceUrl(engine: string, voiceId: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base}/api/voices/preview?engine=${encodeURIComponent(engine)}&voice_id=${encodeURIComponent(voiceId)}`;
}

export async function getProjectVoices(projectId: string): Promise<VoiceAssignment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/voices`);
  if (!res.ok) throw new Error("Failed to load project voices");
  return res.json();
}

export async function setProjectVoices(
  projectId: string,
  assignments: VoiceAssignment[]
): Promise<VoiceAssignment[]> {
  const res = await apiFetch(`/api/projects/${projectId}/voices`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(assignments),
  });
  if (!res.ok) throw new Error("Failed to save voice assignment");
  return res.json();
}

export async function startDub(projectId: string) {
  const res = await apiFetch(`/api/projects/${projectId}/dub`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to start dubbing");
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the voice-selection page**

Speakers are derived from the distinct `speaker_label`s already visible in
the transcript (fetched via `getTranscript`, from Phase 3/4), auto-mapped to
alternating catalog voices as a starting point.

```typescript
// frontend/app/projects/[id]/voices/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getTranscript, getVoiceCatalog, previewVoiceUrl, setProjectVoices } from "@/lib/api";
import type { VoiceAssignment, VoiceCatalogEntry } from "@/lib/types";

export default function VoiceSelectionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [catalog, setCatalog] = useState<VoiceCatalogEntry[]>([]);
  const [assignments, setAssignments] = useState<VoiceAssignment[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const [transcript, voiceCatalog] = await Promise.all([
        getTranscript(id),
        getVoiceCatalog(),
      ]);

      const speakers = Array.from(new Set(transcript.map((t) => t.speaker_label)));
      const edgeVoices = voiceCatalog.filter((v) => v.engine === "edge_tts");

      setCatalog(voiceCatalog);
      setAssignments(
        speakers.map((speaker, i) => ({
          speaker_label: speaker,
          engine: "edge_tts",
          voice_id: edgeVoices[i % edgeVoices.length]?.voice_id ?? edgeVoices[0]?.voice_id ?? "",
          speed: 1.0,
          pitch: 0.0,
        }))
      );
      setLoading(false);
    }
    load();
  }, [id]);

  function updateAssignment(index: number, patch: Partial<VoiceAssignment>) {
    setAssignments((prev) =>
      prev.map((a, i) => (i === index ? { ...a, ...patch } : a))
    );
  }

  async function handleContinue() {
    await setProjectVoices(id, assignments);
    router.push(`/projects/${id}/dub`);
  }

  if (loading) return <p className="p-8">Đang tải...</p>;

  return (
    <main className="mx-auto max-w-2xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Chọn giọng đọc</h1>

      <div className="space-y-6">
        {assignments.map((assignment, index) => (
          <div key={assignment.speaker_label} className="rounded border p-4">
            <div className="mb-2 font-medium">{assignment.speaker_label}</div>

            <div className="grid grid-cols-2 gap-3">
              <select
                className="rounded border p-2"
                value={assignment.voice_id}
                onChange={(e) => {
                  const voice = catalog.find((v) => v.voice_id === e.target.value);
                  updateAssignment(index, {
                    voice_id: e.target.value,
                    engine: voice?.engine ?? assignment.engine,
                  });
                }}
              >
                {catalog.map((v) => (
                  <option key={`${v.engine}-${v.voice_id}`} value={v.voice_id}>
                    {v.name} ({v.engine === "edge_tts" ? "edge-tts" : "Gemini TTS"})
                  </option>
                ))}
              </select>

              <audio
                controls
                src={previewVoiceUrl(assignment.engine, assignment.voice_id)}
                className="h-9"
              />
            </div>

            <div className="mt-2 flex items-center gap-2 text-sm">
              <label>Tốc độ</label>
              <input
                type="range"
                min="0.7"
                max="1.3"
                step="0.05"
                value={assignment.speed}
                onChange={(e) => updateAssignment(index, { speed: Number(e.target.value) })}
              />
              <span>{assignment.speed.toFixed(2)}x</span>
            </div>
          </div>
        ))}
      </div>

      <button
        onClick={handleContinue}
        className="mt-6 rounded bg-blue-600 px-4 py-2 text-white"
      >
        Tiếp tục sang Lồng tiếng
      </button>
    </main>
  );
}
```

- [ ] **Step 6: Build the dubbing progress page with the edge-tts → Gemini TTS fallback prompt**

```typescript
// frontend/app/projects/[id]/dub/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getProjectVoices, setProjectVoices, startDub } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";

interface ProgressMessage {
  status?: string;
  progress_pct?: number;
  error?: string;
  can_retry_with_fallback?: boolean;
  failed_speaker?: string;
  failed_engine?: string;
}

export default function DubProgressPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [progress, setProgress] = useState<ProgressMessage>({});
  const [running, setRunning] = useState(false);

  useEffect(() => {
    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        router.push(`/projects/${id}/preview`);
      }
    });
    return () => ws.close();
  }, [id, router]);

  async function handleStart() {
    setRunning(true);
    setProgress({});
    await startDub(id);
  }

  async function handleFallbackToGemini() {
    if (!progress.failed_speaker) return;
    const voices = await getProjectVoices(id);
    const updated = voices.map((v) =>
      v.speaker_label === progress.failed_speaker
        ? { ...v, engine: "gemini_tts", voice_id: "Kore" }
        : v
    );
    await setProjectVoices(id, updated);
    await handleStart();
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Lồng tiếng</h1>

      {!running && (
        <button onClick={handleStart} className="rounded bg-blue-600 px-4 py-2 text-white">
          Bắt đầu lồng tiếng
        </button>
      )}

      {running && progress.status !== "failed" && (
        <div className="space-y-2">
          <div className="h-3 w-full rounded bg-gray-200">
            <div
              className="h-3 rounded bg-blue-600 transition-all"
              style={{ width: `${progress.progress_pct ?? 0}%` }}
            />
          </div>
          <p className="text-sm text-gray-600">Đang tạo giọng đọc... ({progress.progress_pct ?? 0}%)</p>
        </div>
      )}

      {progress.status === "failed" && (
        <div className="rounded border border-red-300 bg-red-50 p-4">
          <p className="mb-3 text-sm text-red-700">
            {progress.failed_engine === "edge_tts"
              ? `edge-tts gặp lỗi cho giọng của ${progress.failed_speaker}. Bạn có muốn chuyển sang Gemini TTS cho giọng này và thử lại không?`
              : `Lỗi: ${progress.error}`}
          </p>
          {progress.can_retry_with_fallback && (
            <button
              onClick={handleFallbackToGemini}
              className="rounded bg-blue-600 px-4 py-2 text-sm text-white"
            >
              Dùng Gemini TTS và thử lại
            </button>
          )}
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/app/projects/ frontend/lib/api.ts frontend/lib/types.ts frontend/lib/api.test.ts
git commit -m "feat(frontend): add voice selection and dubbing progress pages with TTS fallback prompt"
```

---

## Definition of Done for Phase 6

- [ ] `cd backend && pytest` passes (all Phase 1-6 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: on a translated project, assign voices per speaker (preview each), start dubbing, watch it complete, and confirm `dubbed_segments` rows exist with real R2-stored MP3s and reasonable durations.
- [ ] Manually: force an edge-tts failure (e.g., temporarily break network access to `speech.platform.bing.com` or monkeypatch), confirm the job fails fast with the fallback prompt shown, click through to Gemini TTS, and confirm dubbing completes on retry.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 7.
