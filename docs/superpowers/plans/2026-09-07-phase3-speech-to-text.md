# Phase 3: Speech-to-Text — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Given a project with an uploaded video, extract its audio, transcribe it with word-level timestamps and speaker diarization via ElevenLabs Scribe (falling back to local Whisper on failure/quota exhaustion), persist the transcript as segments, and stream progress to the frontend over WebSocket via a Celery background job.

**Architecture:** A `TranscriptSegment` model; an `stt` service package with an ElevenLabs client and a local-Whisper fallback behind a common interface; a Celery task that extracts audio with FFmpeg, calls the STT engine, writes segments, and reports progress through a `WSManager` broadcasting on `/ws/projects/{id}/progress`; a `POST /api/projects/{id}/transcribe` endpoint that enqueues the task and a `GET /api/projects/{id}/transcript` endpoint to read results.

**Tech Stack:** FastAPI, Celery, ElevenLabs Scribe HTTP API (via `httpx`), `faster-whisper` (fallback), FFmpeg (audio extraction), WebSocket.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- STT primary engine: ElevenLabs Scribe — word-level timestamps + diarization in one call (spec §Speech-to-Text).
- Fallback: local `faster-whisper` (`medium` model, per Phase 1's assumption), used automatically when Scribe fails or the account's ElevenLabs quota is exhausted — no user prompt needed for this fallback (spec §Speech-to-Text, §56 discovery answer).
- Diarization is required; each detected speaker later maps to a distinct dubbing voice (spec §Speech-to-Text).
- All heavy work runs as a Celery background job with WebSocket progress; never synchronously in an HTTP request (spec §Xử lý/Background Jobs).
- Auth is still the Phase-2 stub (`get_current_user_id`); do not add real auth here.

## Established Interfaces (produced here, consumed by later phases)

- `app.models.transcript_segment.TranscriptSegment` — SQLModel table (fields per spec §5).
- `app.models.job.Job` — SQLModel table used by every subsequent background-job phase (translate, dub, export), not just STT.
- `app.core.ws_manager.WSManager` — `connect(project_id, websocket)`, `disconnect(project_id, websocket)`, `async broadcast(project_id, message: dict)`. Reused by Phases 5, 6, 7, 8 for their own job progress.
- `app.services.stt.base.STTEngine` — abstract interface: `transcribe(audio_path: str) -> list[STTSegment]`, where `STTSegment(start: float, end: float, speaker_label: str, text: str, confidence: float | None)`.
- `app.services.stt.elevenlabs.ElevenLabsSTT` and `app.services.stt.whisper_local.WhisperLocalSTT` — both implement `STTEngine`.
- `app.services.stt.router.transcribe_with_fallback(audio_path: str) -> tuple[list[STTSegment], str]` — tries ElevenLabs first, falls back to Whisper local on `STTProviderError`; returns `(segments, engine_used)`.
- `app.services.audio.extract.extract_audio(video_path: str, out_path: str) -> None` — FFmpeg wrapper used again in Phase 7.
- `app.workers.transcribe.transcribe_task(project_id: str)` — Celery task, the template every later pipeline task (translate/dub/export) follows for progress reporting.
- `WS /ws/projects/{id}/progress` — the WebSocket route consumed by every phase's frontend progress UI from here on.

---

### Task 1: `TranscriptSegment` and `Job` models + migration

**Files:**
- Create: `backend/app/models/transcript_segment.py`
- Create: `backend/app/models/job.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_transcript_and_job_models.py`

**Interfaces:**
- Produces: `TranscriptSegment`, `Job` SQLModel classes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_transcript_and_job_models.py
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def make_project(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_create_transcript_segment():
    engine = make_engine()
    with Session(engine) as session:
        project = make_project(session)
        seg = TranscriptSegment(
            project_id=project.id,
            seq_index=0,
            start_time=0.0,
            end_time=2.5,
            speaker_label="speaker_1",
            source_text="Hello world",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        assert seg.id is not None
        assert seg.source_text_edited is None


def test_create_job_defaults():
    engine = make_engine()
    with Session(engine) as session:
        project = make_project(session)
        job = Job(project_id=project.id, job_type="transcribe")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.status == "queued"
        assert job.progress_pct == 0

        fetched = session.exec(select(Job).where(Job.project_id == project.id)).one()
        assert fetched.job_type == "transcribe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_transcript_and_job_models.py -v`
Expected: FAIL — models don't exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/transcript_segment.py
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class TranscriptSegment(SQLModel, table=True):
    __tablename__ = "transcript_segments"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    source_text_edited: Optional[str] = None
    confidence: Optional[float] = None
```

```python
# backend/app/models/job.py
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    job_type: str  # "transcribe" | "translate" | "dub" | "export"
    status: str = Field(default="queued")  # "queued" | "running" | "done" | "failed"
    progress_pct: float = Field(default=0)
    current_step: Optional[str] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
```

```python
# backend/app/models/__init__.py
from app.models.job import Job  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.transcript_segment import TranscriptSegment  # noqa: F401
from app.models.video import Video  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_transcript_and_job_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add transcript_segments and jobs tables" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/transcript_segment.py backend/app/models/job.py backend/app/models/__init__.py backend/tests/test_transcript_and_job_models.py backend/alembic/versions/
git commit -m "feat(backend): add TranscriptSegment and Job models + migration"
```

---

### Task 2: Audio extraction (FFmpeg)

**Files:**
- Create: `backend/app/services/audio/__init__.py`
- Create: `backend/app/services/audio/extract.py`
- Create: `backend/tests/test_extract_audio.py`

**Interfaces:**
- Produces: `app.services.audio.extract.extract_audio(video_path: str, out_path: str) -> None`, `app.services.audio.extract.AudioExtractionError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_extract_audio.py
import subprocess
import wave
from pathlib import Path

import pytest

from app.services.audio.extract import AudioExtractionError, extract_audio

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture(autouse=True)
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


def test_extract_audio_produces_valid_wav(tmp_path):
    out_path = tmp_path / "out.wav"
    extract_audio(str(FIXTURE), str(out_path))

    assert out_path.exists()
    with wave.open(str(out_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() > 0


def test_extract_audio_raises_on_missing_input():
    with pytest.raises(AudioExtractionError):
        extract_audio("/nonexistent.mp4", "/tmp/out.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_extract_audio.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/audio/__init__.py
```

```python
# backend/app/services/audio/extract.py
import os
import subprocess


class AudioExtractionError(Exception):
    pass


def extract_audio(video_path: str, out_path: str) -> None:
    if not os.path.exists(video_path):
        raise AudioExtractionError(f"File not found: {video_path}")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-i", video_path,
                "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
                out_path,
            ],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise AudioExtractionError(
            f"ffmpeg failed extracting audio from {video_path}: {exc.stderr.decode(errors='replace')}"
        ) from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_extract_audio.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audio/ backend/tests/test_extract_audio.py
git commit -m "feat(backend): add FFmpeg-based audio extraction"
```

---

### Task 3: STT engine interface + ElevenLabs implementation

**Files:**
- Create: `backend/app/services/stt/__init__.py`
- Create: `backend/app/services/stt/base.py`
- Create: `backend/app/services/stt/elevenlabs.py`
- Create: `backend/tests/test_stt_elevenlabs.py`

**Interfaces:**
- Produces: `app.services.stt.base.STTSegment`, `app.services.stt.base.STTEngine` (ABC), `app.services.stt.base.STTProviderError(Exception)`; `app.services.stt.elevenlabs.ElevenLabsSTT(STTEngine)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stt_elevenlabs.py
from unittest.mock import MagicMock, patch

import pytest

from app.services.stt.base import STTProviderError
from app.services.stt.elevenlabs import ElevenLabsSTT

SAMPLE_RESPONSE = {
    "words": [
        {"text": "Hello", "start": 0.0, "end": 0.4, "speaker_id": "speaker_1"},
        {"text": "world", "start": 0.4, "end": 0.9, "speaker_id": "speaker_1"},
        {"text": "Hi", "start": 1.2, "end": 1.5, "speaker_id": "speaker_2"},
    ]
}


def test_transcribe_groups_words_into_segments_by_speaker():
    engine = ElevenLabsSTT(api_key="fake-key")

    with patch("app.services.stt.elevenlabs.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_RESPONSE
        mock_post.return_value = mock_response

        segments = engine.transcribe("/tmp/audio.wav")

    assert len(segments) == 2
    assert segments[0].speaker_label == "speaker_1"
    assert segments[0].text == "Hello world"
    assert segments[0].start == 0.0
    assert segments[0].end == 0.9
    assert segments[1].speaker_label == "speaker_2"
    assert segments[1].text == "Hi"


def test_transcribe_raises_provider_error_on_failure():
    engine = ElevenLabsSTT(api_key="fake-key")

    with patch("app.services.stt.elevenlabs.httpx.post") as mock_post:
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "quota exceeded"
        mock_post.return_value = mock_response

        with pytest.raises(STTProviderError):
            engine.transcribe("/tmp/audio.wav")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stt_elevenlabs.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/stt/__init__.py
```

```python
# backend/app/services/stt/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class STTSegment:
    start: float
    end: float
    speaker_label: str
    text: str
    confidence: Optional[float] = None


class STTProviderError(Exception):
    pass


class STTEngine(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str) -> list[STTSegment]:
        raise NotImplementedError
```

```python
# backend/app/services/stt/elevenlabs.py
import httpx

from app.services.stt.base import STTEngine, STTProviderError, STTSegment

ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
MAX_SILENCE_GAP_TO_MERGE = 0.5  # seconds; words within this gap join the same segment


class ElevenLabsSTT(STTEngine):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def transcribe(self, audio_path: str) -> list[STTSegment]:
        with open(audio_path, "rb") as f:
            response = httpx.post(
                ELEVENLABS_STT_URL,
                headers={"xi-api-key": self.api_key},
                files={"file": f},
                data={"model_id": "scribe_v1", "diarize": "true"},
                timeout=600,
            )

        if response.status_code != 200:
            raise STTProviderError(
                f"ElevenLabs STT failed ({response.status_code}): {response.text}"
            )

        words = response.json().get("words", [])
        return self._group_words_into_segments(words)

    @staticmethod
    def _group_words_into_segments(words: list[dict]) -> list[STTSegment]:
        segments: list[STTSegment] = []
        current: Optional[dict] = None

        for word in words:
            speaker = word["speaker_id"]
            if current is None or current["speaker_label"] != speaker or (
                word["start"] - current["end"] > MAX_SILENCE_GAP_TO_MERGE
            ):
                if current is not None:
                    segments.append(STTSegment(**current))
                current = {
                    "start": word["start"],
                    "end": word["end"],
                    "speaker_label": speaker,
                    "text": word["text"],
                    "confidence": None,
                }
            else:
                current["end"] = word["end"]
                current["text"] += f" {word['text']}"

        if current is not None:
            segments.append(STTSegment(**current))

        return segments
```

Add `from typing import Optional` to the top of `elevenlabs.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_stt_elevenlabs.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/stt/__init__.py backend/app/services/stt/base.py backend/app/services/stt/elevenlabs.py backend/tests/test_stt_elevenlabs.py
git commit -m "feat(backend): add STTEngine interface and ElevenLabs Scribe implementation"
```

---

### Task 4: Whisper local fallback + router with automatic fallback

**Files:**
- Create: `backend/app/services/stt/whisper_local.py`
- Create: `backend/app/services/stt/router.py`
- Create: `backend/tests/test_stt_router.py`

**Interfaces:**
- Produces: `app.services.stt.whisper_local.WhisperLocalSTT(STTEngine)`; `app.services.stt.router.transcribe_with_fallback(audio_path: str) -> tuple[list[STTSegment], str]`.

- [ ] **Step 1: Add `faster-whisper` dependency**

Add `"faster-whisper>=1.0"` to `backend/pyproject.toml`'s `dependencies`, then `pip install -e ".[dev]"`.

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_stt_router.py
from unittest.mock import MagicMock, patch

from app.services.stt.base import STTProviderError, STTSegment
from app.services.stt.router import transcribe_with_fallback


def test_uses_elevenlabs_when_it_succeeds():
    fake_segments = [STTSegment(start=0, end=1, speaker_label="speaker_1", text="hi")]

    with patch("app.services.stt.router.ElevenLabsSTT") as MockEleven:
        MockEleven.return_value.transcribe.return_value = fake_segments

        segments, engine_used = transcribe_with_fallback("/tmp/audio.wav")

    assert engine_used == "elevenlabs"
    assert segments == fake_segments


def test_falls_back_to_whisper_local_when_elevenlabs_fails():
    fake_segments = [STTSegment(start=0, end=1, speaker_label="speaker_1", text="hi")]

    with patch("app.services.stt.router.ElevenLabsSTT") as MockEleven, patch(
        "app.services.stt.router.WhisperLocalSTT"
    ) as MockWhisper:
        MockEleven.return_value.transcribe.side_effect = STTProviderError("quota exceeded")
        MockWhisper.return_value.transcribe.return_value = fake_segments

        segments, engine_used = transcribe_with_fallback("/tmp/audio.wav")

    assert engine_used == "whisper_local"
    assert segments == fake_segments
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_stt_router.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/services/stt/whisper_local.py
from faster_whisper import WhisperModel

from app.services.stt.base import STTEngine, STTSegment


class WhisperLocalSTT(STTEngine):
    """No diarization — every segment is labelled 'speaker_1'. Used only as
    a fallback; ElevenLabs Scribe is the only engine that diarizes."""

    def __init__(self, model_size: str = "medium"):
        self.model_size = model_size
        self._model: WhisperModel | None = None

    def _get_model(self) -> WhisperModel:
        if self._model is None:
            self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe(self, audio_path: str) -> list[STTSegment]:
        model = self._get_model()
        segments, _info = model.transcribe(audio_path, word_timestamps=False)
        return [
            STTSegment(
                start=seg.start,
                end=seg.end,
                speaker_label="speaker_1",
                text=seg.text.strip(),
                confidence=seg.avg_logprob,
            )
            for seg in segments
        ]
```

```python
# backend/app/services/stt/router.py
from app.core.config import settings
from app.services.stt.base import STTProviderError, STTSegment
from app.services.stt.elevenlabs import ElevenLabsSTT
from app.services.stt.whisper_local import WhisperLocalSTT


def transcribe_with_fallback(audio_path: str) -> tuple[list[STTSegment], str]:
    try:
        engine = ElevenLabsSTT(api_key=settings.elevenlabs_api_key)
        return engine.transcribe(audio_path), "elevenlabs"
    except STTProviderError:
        fallback = WhisperLocalSTT()
        return fallback.transcribe(audio_path), "whisper_local"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_stt_router.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/stt/whisper_local.py backend/app/services/stt/router.py backend/tests/test_stt_router.py backend/pyproject.toml
git commit -m "feat(backend): add Whisper local fallback with automatic STT routing"
```

---

### Task 5: WebSocket progress manager

**Files:**
- Create: `backend/app/core/ws_manager.py`
- Create: `backend/tests/test_ws_manager.py`

**Interfaces:**
- Produces: `app.core.ws_manager.WSManager` with `connect`, `disconnect`, `async broadcast`; module-level singleton `app.core.ws_manager.ws_manager`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ws_manager.py
import asyncio
from unittest.mock import AsyncMock

from app.core.ws_manager import WSManager


def test_broadcast_sends_to_all_connections_for_project():
    manager = WSManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    ws_other_project = AsyncMock()

    manager.connect("project-1", ws1)
    manager.connect("project-1", ws2)
    manager.connect("project-2", ws_other_project)

    asyncio.run(manager.broadcast("project-1", {"progress_pct": 50}))

    ws1.send_json.assert_awaited_once_with({"progress_pct": 50})
    ws2.send_json.assert_awaited_once_with({"progress_pct": 50})
    ws_other_project.send_json.assert_not_awaited()


def test_disconnect_removes_connection():
    manager = WSManager()
    ws1 = AsyncMock()
    manager.connect("project-1", ws1)
    manager.disconnect("project-1", ws1)

    asyncio.run(manager.broadcast("project-1", {"progress_pct": 100}))

    ws1.send_json.assert_not_awaited()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ws_manager.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/ws_manager.py
from collections import defaultdict
from typing import Any, Protocol


class SendsJSON(Protocol):
    async def send_json(self, data: Any) -> None: ...


class WSManager:
    def __init__(self):
        self._connections: dict[str, list[SendsJSON]] = defaultdict(list)

    def connect(self, project_id: str, websocket: SendsJSON) -> None:
        self._connections[project_id].append(websocket)

    def disconnect(self, project_id: str, websocket: SendsJSON) -> None:
        if websocket in self._connections[project_id]:
            self._connections[project_id].remove(websocket)

    async def broadcast(self, project_id: str, message: dict) -> None:
        for websocket in list(self._connections.get(project_id, [])):
            await websocket.send_json(message)


ws_manager = WSManager()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ws_manager.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the WebSocket route into the FastAPI app**

```python
# backend/app/api/ws_progress.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.ws_manager import ws_manager

router = APIRouter()


@router.websocket("/ws/projects/{project_id}/progress")
async def project_progress_ws(websocket: WebSocket, project_id: str):
    await websocket.accept()
    ws_manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keep the connection open; client sends pings
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)
```

```python
# backend/app/main.py  (add to existing file)
from app.api.ws_progress import router as ws_progress_router

app.include_router(ws_progress_router)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/ws_manager.py backend/app/api/ws_progress.py backend/app/main.py backend/tests/test_ws_manager.py
git commit -m "feat(backend): add WebSocket progress manager and /ws/projects/{id}/progress route"
```

---

### Task 6: `transcribe_task` Celery task

**Files:**
- Create: `backend/app/workers/transcribe.py`
- Create: `backend/tests/test_transcribe_task.py`

**Interfaces:**
- Consumes: `app.services.audio.extract.extract_audio`, `app.services.stt.router.transcribe_with_fallback`, `app.core.storage.get_r2_client`, `app.core.ws_manager.ws_manager`, `app.models.job.Job`, `app.models.transcript_segment.TranscriptSegment`, `app.models.video.Video`.
- Produces: `app.workers.transcribe.transcribe_task(project_id: str) -> None` (Celery task, registered as `app.workers.transcribe.transcribe_task`). This task's structure (fetch job row → mark running → do work with progress callbacks → mark done/failed) is the template Phases 5, 6, 7, 8 copy for `translate_task`, `dub_task`, and `export_task`.

- [ ] **Step 1: Write the failing test**

The test runs the Celery task function directly (not through a broker) and
stubs out I/O-heavy dependencies.

```python
# backend/tests/test_transcribe_task.py
from unittest.mock import MagicMock, patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.video import Video
from app.services.stt.base import STTSegment


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def seed_project_with_video(session):
    project = Project(
        user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    video = Video(
        project_id=project.id,
        source_type="upload",
        storage_path="videos/x/tiny.mp4",
        duration_sec=2.0,
        resolution="320x240",
        codec="h264",
        file_size_bytes=100,
    )
    session.add(video)
    session.commit()

    job = Job(project_id=project.id, job_type="transcribe")
    session.add(job)
    session.commit()
    session.refresh(job)

    return project, video, job


def test_transcribe_task_writes_segments_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project, video, job = seed_project_with_video(session)

    fake_segments = [
        STTSegment(start=0.0, end=1.0, speaker_label="speaker_1", text="Hello"),
        STTSegment(start=1.0, end=2.0, speaker_label="speaker_2", text="Hi there"),
    ]

    with patch("app.workers.transcribe.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.transcribe.get_r2_client"
    ) as mock_get_r2, patch("app.workers.transcribe.extract_audio"), patch(
        "app.workers.transcribe.transcribe_with_fallback",
        return_value=(fake_segments, "elevenlabs"),
    ), patch("app.workers.transcribe.broadcast_sync") as mock_broadcast:
        mock_get_r2.return_value.download_file = MagicMock()

        from app.workers.transcribe import transcribe_task

        transcribe_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "done"
        assert refreshed_job.progress_pct == 100

        segments = session.exec(
            select(TranscriptSegment).where(TranscriptSegment.project_id == project.id)
        ).all()
        assert len(segments) == 2
        assert segments[0].source_text == "Hello"
        assert segments[1].speaker_label == "speaker_2"

    assert mock_broadcast.called


def test_transcribe_task_marks_job_failed_on_exception():
    engine = make_engine()
    with Session(engine) as session:
        project, video, job = seed_project_with_video(session)

    with patch("app.workers.transcribe.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.transcribe.get_r2_client"
    ), patch("app.workers.transcribe.extract_audio", side_effect=RuntimeError("boom")), patch(
        "app.workers.transcribe.broadcast_sync"
    ):
        from app.workers.transcribe import transcribe_task

        transcribe_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "failed"
        assert "boom" in refreshed_job.error_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_transcribe_task.py -v`
Expected: FAIL — `app.workers.transcribe` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/transcribe.py
import asyncio
import os
import tempfile
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.storage import get_r2_client
from app.core.ws_manager import ws_manager
from app.db.session import engine
from app.models.job import Job
from app.models.transcript_segment import TranscriptSegment
from app.models.video import Video
from app.services.audio.extract import extract_audio
from app.services.stt.router import transcribe_with_fallback


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    asyncio.run(ws_manager.broadcast(project_id, message))


@celery_app.task(name="app.workers.transcribe.transcribe_task")
def transcribe_task(project_id: str) -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "transcribe")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    job.current_step = "downloading_video"
    job.progress_pct = 5
    session.add(job)
    session.commit()
    broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 5})

    try:
        video = session.exec(select(Video).where(Video.project_id == project_id)).first()
        if video is None:
            raise RuntimeError("No video found for project")

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = os.path.join(tmp_dir, "video.mp4")
            get_r2_client().download_file(video.storage_path, video_path)

            job.current_step = "extracting_audio"
            job.progress_pct = 20
            session.add(job)
            session.commit()
            broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 20})

            audio_path = os.path.join(tmp_dir, "audio.wav")
            extract_audio(video_path, audio_path)

            job.current_step = "transcribing"
            job.progress_pct = 40
            session.add(job)
            session.commit()
            broadcast_sync(project_id, {"status": "running", "step": job.current_step, "progress_pct": 40})

            stt_segments, engine_used = transcribe_with_fallback(audio_path)

            for index, seg in enumerate(stt_segments):
                session.add(
                    TranscriptSegment(
                        project_id=project_id,
                        seq_index=index,
                        start_time=seg.start,
                        end_time=seg.end,
                        speaker_label=seg.speaker_label,
                        source_text=seg.text,
                        confidence=seg.confidence,
                    )
                )
            session.commit()

        job.status = "done"
        job.current_step = f"done ({engine_used})"
        job.progress_pct = 100
        job.finished_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
        broadcast_sync(
            project_id,
            {"status": "done", "step": job.current_step, "progress_pct": 100},
        )
    except Exception as exc:  # noqa: BLE001 — job-failure path must catch everything
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

Run: `cd backend && pytest tests/test_transcribe_task.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/transcribe.py backend/tests/test_transcribe_task.py
git commit -m "feat(backend): add transcribe_task Celery job with progress broadcasting"
```

---

### Task 7: `POST /transcribe` and `GET /transcript` endpoints

**Files:**
- Create: `backend/app/api/transcript.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/core/celery_app.py` (include the new task module)
- Create: `backend/tests/test_transcript_api.py`

**Interfaces:**
- Produces: `POST /api/projects/{id}/transcribe` (enqueues `transcribe_task`, returns the `Job`), `GET /api/projects/{id}/transcript` (returns `list[TranscriptSegmentRead]`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_transcript_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.transcript_segment import TranscriptSegment

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
            "title": "STT test",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_start_transcribe_creates_queued_job_and_enqueues_task():
    project_id = create_project()

    with patch("app.api.transcript.transcribe_task") as mock_task:
        resp = client.post(f"/api/projects/{project_id}/transcribe")

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job_type"] == "transcribe"
    assert body["status"] == "queued"
    mock_task.delay.assert_called_once_with(project_id=project_id)


def test_get_transcript_returns_segments_ordered_by_seq_index():
    project_id = create_project()
    with Session(engine) as session:
        session.add(
            TranscriptSegment(
                project_id=project_id, seq_index=1, start_time=1, end_time=2,
                speaker_label="speaker_1", source_text="second",
            )
        )
        session.add(
            TranscriptSegment(
                project_id=project_id, seq_index=0, start_time=0, end_time=1,
                speaker_label="speaker_1", source_text="first",
            )
        )
        session.commit()

    resp = client.get(f"/api/projects/{project_id}/transcript")
    assert resp.status_code == 200
    texts = [seg["source_text"] for seg in resp.json()]
    assert texts == ["first", "second"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_transcript_api.py -v`
Expected: FAIL — `app.api.transcript` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/transcript.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.workers.transcribe import transcribe_task

router = APIRouter(prefix="/api/projects", tags=["transcript"])


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


class TranscriptSegmentRead(BaseModel):
    id: str
    project_id: str
    seq_index: int
    start_time: float
    end_time: float
    speaker_label: str
    source_text: str
    source_text_edited: str | None
    confidence: float | None

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/transcribe", response_model=JobRead, status_code=202)
def start_transcribe(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    job = Job(project_id=project.id, job_type="transcribe")
    session.add(job)
    project.status = "transcribing"
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(job)

    transcribe_task.delay(project_id=project_id)

    return job


@router.get("/{project_id}/transcript", response_model=list[TranscriptSegmentRead])
def get_transcript(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)
    return session.exec(
        select(TranscriptSegment)
        .where(TranscriptSegment.project_id == project_id)
        .order_by(TranscriptSegment.seq_index)
    ).all()
```

```python
# backend/app/main.py  (add to existing file)
from app.api.transcript import router as transcript_router

app.include_router(transcript_router)
```

```python
# backend/app/core/celery_app.py  (update the include list)
celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.ping", "app.workers.transcribe"],
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_transcript_api.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all tests from Phases 1-3 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/transcript.py backend/app/main.py backend/app/core/celery_app.py backend/tests/test_transcript_api.py
git commit -m "feat(backend): add transcribe and transcript endpoints"
```

---

### Task 8: Frontend — trigger transcription + live progress

**Files:**
- Create: `frontend/lib/ws.ts`
- Create: `frontend/app/projects/[id]/transcript/page.tsx`
- Create: `frontend/lib/ws.test.ts`

**Interfaces:**
- Produces: `lib/ws.ts` exports `connectProjectWS(projectId: string, onMessage: (data: any) => void): WebSocket` — reused by every later phase's progress page (translate, dub, export).
- Consumes: `apiFetch` (Phase 1).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/ws.test.ts
import { describe, expect, it, vi } from "vitest";
import { connectProjectWS } from "./ws";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onmessage: ((event: { data: string }) => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
}

describe("connectProjectWS", () => {
  it("connects to the right project progress URL and forwards parsed messages", () => {
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
    vi.stubEnv("NEXT_PUBLIC_WS_URL", "ws://localhost:8000");

    const onMessage = vi.fn();
    connectProjectWS("project-123", onMessage);

    const ws = FakeWebSocket.instances[FakeWebSocket.instances.length - 1];
    expect(ws.url).toBe("ws://localhost:8000/ws/projects/project-123/progress");

    ws.onmessage?.({ data: JSON.stringify({ progress_pct: 42 }) });
    expect(onMessage).toHaveBeenCalledWith({ progress_pct: 42 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `lib/ws.ts` doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/ws.ts
export function connectProjectWS(
  projectId: string,
  onMessage: (data: unknown) => void
): WebSocket {
  const base = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
  const ws = new WebSocket(`${base}/ws/projects/${projectId}/progress`);
  ws.onmessage = (event) => {
    onMessage(JSON.parse(event.data));
  };
  return ws;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the transcript progress/trigger page**

```typescript
// frontend/app/projects/[id]/transcript/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";

interface ProgressMessage {
  status?: string;
  step?: string;
  progress_pct?: number;
  error?: string;
}

export default function TranscriptProgressPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [started, setStarted] = useState(false);
  const [progress, setProgress] = useState<ProgressMessage>({});

  useEffect(() => {
    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        router.push(`/projects/${id}/transcript/edit`);
      }
    });
    return () => ws.close();
  }, [id, router]);

  async function startTranscribe() {
    setStarted(true);
    await apiFetch(`/api/projects/${id}/transcribe`, { method: "POST" });
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Nhận diện lời nói</h1>

      {!started && (
        <button
          onClick={startTranscribe}
          className="rounded bg-blue-600 px-4 py-2 text-white"
        >
          Bắt đầu nhận diện
        </button>
      )}

      {started && (
        <div className="space-y-2">
          <div className="h-3 w-full rounded bg-gray-200">
            <div
              className="h-3 rounded bg-blue-600 transition-all"
              style={{ width: `${progress.progress_pct ?? 0}%` }}
            />
          </div>
          <p className="text-sm text-gray-600">
            {progress.error
              ? `Lỗi: ${progress.error}`
              : progress.step ?? "Đang chờ..."}{" "}
            ({progress.progress_pct ?? 0}%)
          </p>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/lib/ws.ts frontend/lib/ws.test.ts frontend/app/projects/
git commit -m "feat(frontend): add transcription trigger page with live WebSocket progress"
```

---

## Definition of Done for Phase 3

- [ ] `cd backend && pytest` passes (all Phase 1-3 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: with a real `ELEVENLABS_API_KEY` in `.env`, upload a short video, call transcribe, watch progress reach 100% in the browser, and confirm `transcript_segments` rows exist with correct speaker labels.
- [ ] Manually: temporarily set an invalid `ELEVENLABS_API_KEY` and confirm the job still completes using the Whisper local fallback (`current_step` ends with `(whisper_local)`).
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 4.
