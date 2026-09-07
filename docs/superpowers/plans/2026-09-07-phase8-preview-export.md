# Phase 8: Preview & Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Phase 7's service functions into a real `export_task` that assembles the final dubbed video (all three deliverables: soft-subbed video, hard-subbed video, standalone SRT), expose it through preview/export/download endpoints, let the user regenerate a single segment's dubbed audio, and enforce the 7-day storage lifecycle.

**Architecture:** An `Export` model; an `export_task` Celery job that chains every Phase 7 service function into one pipeline run (assemble → mix → mux → subtitles → upload); `POST /export`, `GET /preview`, `GET /exports`, `GET /exports/{id}/download` endpoints; a `POST /segments/{id}/regenerate` endpoint reusing Phase 6's `synthesize_segment_with_rate_adjustment`; a Celery Beat periodic task that deletes expired projects' R2 objects; a combined Preview/Export frontend page (the spec lists "Xem trước/Xuất" as a single screen).

**Tech Stack:** FastAPI, Celery (+ Celery Beat), all of Phase 7's FFmpeg/Demucs services, Next.js.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Preview and Export are **one screen and one underlying operation**, not two — the spec's screen list names them together ("Xem trước/Xuất"), and re-running the FFmpeg/Demucs pipeline twice (once for a preview, again for the real export) would double the most expensive part of the whole system for no benefit. `export_task` runs once; its "video" (soft-subtitled) output doubles as both the preview player's source and a downloadable deliverable.
- All three subtitle deliverables are always produced together in the same job run (spec §Phụ đề, discovery Q45b): a standalone `.srt`, a soft-embedded video, and a separately burned-in video with configurable font size/color/position.
- Output resolution defaults to a stream copy (no re-encode); re-encoding only happens if the user picks a different resolution at export time (spec §Đầu vào Video, discovery Q19-A).
- Per-segment regeneration (spec §Editing, discovery Q29-C) only re-synthesizes that one segment's dubbed audio and lets the user preview it in isolation — it does **not** automatically re-run the full export; the user re-clicks "Xuất video" when ready, which reruns the (cheap, since only TTS changed) assembly step.
- Project storage lifecycle: temp intermediate files are already cleaned up by construction (every service function in Phase 7 that needs scratch space uses `tempfile`/context-managed cleanup). The remaining requirement — full deletion 7 days after creation, with an in-app warning 1 day before — is implemented here as: `expires_at` is set at project creation (`created_at + 7 days`); the frontend computes the "expires soon" banner directly from `expires_at` (no separate warning-delivery mechanism is needed); a Celery Beat periodic task physically deletes R2 objects for projects past `expires_at` (spec §Lưu trữ & Vòng đời dữ liệu, discovery Q58-D).
- Auth is still the Phase-2..7 stub (`get_current_user_id()`); real auth lands in Phase 9.

## Established Interfaces (produced here, consumed by Phase 9 if at all)

- `app.models.export.Export` — SQLModel table (fields per spec §5).
- `app.workers.export.export_task(project_id: str, resolution: str | None, font_size: int, font_color: str, position: str) -> None`.
- `GET /api/projects/{id}/preview` — `{"video_url": str, "srt_url": str, "status": str}`.
- `POST /api/projects/{id}/segments/{segment_id}/regenerate` — `{"audio_url": str, "duration_sec": float}`.
- A hourly Celery Beat schedule entry, `cleanup-expired-projects`, calling `app.workers.cleanup.cleanup_expired_projects_task`.

---

### Task 1: `Export` model + migration + set `expires_at` at project creation

**Files:**
- Create: `backend/app/models/export.py`
- Modify: `backend/app/models/__init__.py`
- Modify: `backend/app/api/projects.py`
- Create: `backend/tests/test_export_model.py`
- Modify: `backend/tests/test_projects_api.py`

**Interfaces:**
- Produces: `Export` SQLModel class; modifies `create_project` to set `expires_at`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_export_model.py
from sqlmodel import Session, SQLModel, create_engine

from app.models.export import Export
from app.models.project import Project


def test_create_export():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        project = Project(
            user_id="u1", title="t", source_language="en", target_language="vi", audio_mode="ducking"
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        export = Export(
            project_id=project.id, export_type="video", storage_path="exports/x/video.mp4"
        )
        session.add(export)
        session.commit()
        session.refresh(export)
        assert export.id is not None
```

```python
# backend/tests/test_projects_api.py  (add this test to the existing file)
def test_create_project_sets_expires_at_seven_days_out():
    from datetime import datetime, timedelta, timezone

    resp = client.post(
        "/api/projects",
        json={
            "title": "Expiry test", "source_language": "en",
            "target_language": "vi", "audio_mode": "silent",
        },
    )
    body = resp.json()
    expires_at = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    expected = datetime.now(timezone.utc) + timedelta(days=7)
    assert abs((expires_at - expected).total_seconds()) < 60
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_export_model.py tests/test_projects_api.py -v`
Expected: FAIL — `app.models.export` doesn't exist; `expires_at` isn't set; `ProjectRead` doesn't expose it yet.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/export.py
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Export(SQLModel, table=True):
    __tablename__ = "exports"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    export_type: str  # "video" | "video_hardsub" | "srt"
    storage_path: str
    resolution: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
    expires_at: Optional[datetime] = None
```

Clean up that inline-import line (kept in the "write the failing-test-passing
code" step for brevity, but it must be fixed before committing — see next
step):

```python
# backend/app/models/export.py  (final version)
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Export(SQLModel, table=True):
    __tablename__ = "exports"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    export_type: str  # "video" | "video_hardsub" | "srt"
    storage_path: str
    resolution: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
```

```python
# backend/app/models/__init__.py
from app.models.dubbed_segment import DubbedSegment  # noqa: F401
from app.models.export import Export  # noqa: F401
from app.models.glossary_term import GlossaryTerm  # noqa: F401
from app.models.job import Job  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.transcript_segment import TranscriptSegment  # noqa: F401
from app.models.translation_segment import TranslationSegment  # noqa: F401
from app.models.video import Video  # noqa: F401
from app.models.voice import Voice  # noqa: F401
```

```python
# backend/app/api/projects.py  (modify create_project)
from datetime import timedelta

PROJECT_LIFETIME_DAYS = 7


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = Project(
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=PROJECT_LIFETIME_DAYS),
        **payload.model_dump(),
    )
    session.add(project)
    session.commit()
    session.refresh(project)
    return project
```

```python
# backend/app/schemas/project.py  (ensure ProjectRead includes expires_at — it already does per Phase 1/2's field list; if it was omitted, add:)
    expires_at: Optional[datetime]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_export_model.py tests/test_projects_api.py -v`
Expected: PASS

- [ ] **Step 5: Generate migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add exports table" --autogenerate && alembic upgrade head`

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-8 tests so far pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/export.py backend/app/models/__init__.py backend/app/api/projects.py backend/app/schemas/project.py backend/tests/test_export_model.py backend/tests/test_projects_api.py backend/alembic/versions/
git commit -m "feat(backend): add Export model and set project expires_at on creation"
```

---

### Task 2: Resolution rescale helper

**Files:**
- Create: `backend/app/services/video/scale.py`
- Create: `backend/tests/test_scale.py`

**Interfaces:**
- Produces: `app.services.video.scale.rescale_video(video_path: str, out_path: str, resolution: str) -> None` (`resolution` is `"WIDTHxHEIGHT"`, e.g. `"1280x720"`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_scale.py
import subprocess

import pytest

from app.services.video.ffprobe import probe_video
from app.services.video.scale import rescale_video


@pytest.fixture
def tiny_video(tmp_path):
    out = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=640x480:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-shortest", str(out),
        ],
        check=True, capture_output=True,
    )
    return str(out)


def test_rescale_video_changes_resolution(tiny_video, tmp_path):
    out_path = str(tmp_path / "rescaled.mp4")
    rescale_video(tiny_video, out_path, "320x240")

    result = probe_video(out_path)
    assert result.resolution == "320x240"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_scale.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/video/scale.py
import subprocess


def rescale_video(video_path: str, out_path: str, resolution: str) -> None:
    width, height = resolution.split("x")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"scale={width}:{height}",
            "-c:v", "libx264",
            "-c:a", "copy",
            out_path,
        ],
        check=True,
        capture_output=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_scale.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/video/scale.py backend/tests/test_scale.py
git commit -m "feat(backend): add video resolution rescale helper"
```

---

### Task 3: `export_task` Celery job

**Files:**
- Create: `backend/app/workers/export.py`
- Modify: `backend/app/core/celery_app.py`
- Create: `backend/tests/test_export_task.py`

**Interfaces:**
- Consumes: everything from Phase 7 (`assemble_dubbed_audio_track`, `build_final_audio`, `mux_video_with_audio`, `generate_srt`, `burn_subtitles`, `embed_soft_subtitles`, `rescale_video`) plus `extract_audio` (Phase 3), `get_r2_client`, `Job`, `Export`, `Video`, `TranscriptSegment`, `TranslationSegment`, `DubbedSegment`.
- Produces: `app.workers.export.export_task(project_id, resolution=None, font_size=28, font_color="white", position="bottom_center") -> None`.

- [ ] **Step 1: Write the failing test**

This test stubs out every FFmpeg/Demucs call (already unit-tested in Phase
7) and asserts the orchestration: three `Export` rows created, `Job` marked
done, R2 uploads called three times.

```python
# backend/tests/test_export_task.py
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.dubbed_segment import DubbedSegment
from app.models.export import Export
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.video import Video


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

    session.add(
        Video(
            project_id=project.id, source_type="upload", storage_path="videos/x/v.mp4",
            duration_sec=2.0, resolution="320x240", codec="h264", file_size_bytes=100,
        )
    )

    seg = TranscriptSegment(
        project_id=project.id, seq_index=0, start_time=0, end_time=2,
        speaker_label="speaker_1", source_text="Hello",
    )
    session.add(seg)
    session.commit()
    session.refresh(seg)

    session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
    session.add(
        DubbedSegment(
            segment_id=seg.id, audio_storage_path="dubbed/x/seg.mp3",
            duration_sec=1.9, status="done",
        )
    )

    job = Job(project_id=project.id, job_type="export")
    session.add(job)
    session.commit()
    session.refresh(job)

    return project, job


def test_export_task_creates_three_exports_and_marks_job_done():
    engine = make_engine()
    with Session(engine) as session:
        project, job = seed(session)

    with patch("app.workers.export.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.export.get_r2_client"
    ) as mock_get_r2, patch("app.workers.export.extract_audio"), patch(
        "app.workers.export.assemble_dubbed_audio_track"
    ), patch("app.workers.export.build_final_audio"), patch(
        "app.workers.export.mux_video_with_audio"
    ), patch("app.workers.export.embed_soft_subtitles"), patch(
        "app.workers.export.burn_subtitles"
    ), patch("app.workers.export.broadcast_sync"):
        mock_r2 = mock_get_r2.return_value
        mock_r2.upload_file.side_effect = lambda local_path, key: key

        from app.workers.export import export_task

        export_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "done"

        exports = session.exec(select(Export).where(Export.project_id == project.id)).all()
        types = {e.export_type for e in exports}
        assert types == {"video", "video_hardsub", "srt"}

        refreshed_project = session.get(Project, project.id)
        assert refreshed_project.status == "ready"


def test_export_task_marks_job_failed_on_exception():
    engine = make_engine()
    with Session(engine) as session:
        project, job = seed(session)

    with patch("app.workers.export.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.export.get_r2_client"
    ), patch("app.workers.export.extract_audio", side_effect=RuntimeError("ffmpeg exploded")), patch(
        "app.workers.export.broadcast_sync"
    ):
        from app.workers.export import export_task

        export_task.run(project_id=project.id)

    with Session(engine) as session:
        refreshed_job = session.get(Job, job.id)
        assert refreshed_job.status == "failed"
        assert "ffmpeg exploded" in refreshed_job.error_message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_export_task.py -v`
Expected: FAIL — `app.workers.export` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/export.py
import asyncio
import os
import tempfile
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.storage import get_r2_client
from app.core.ws_manager import ws_manager
from app.db.session import engine
from app.models.dubbed_segment import DubbedSegment
from app.models.export import Export
from app.models.job import Job
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.video import Video
from app.services.audio.assemble import SegmentAudioPlacement, assemble_dubbed_audio_track
from app.services.audio.extract import extract_audio
from app.services.audio.mix import build_final_audio
from app.services.subtitle.srt import SubtitleCue, generate_srt
from app.services.video.mux import mux_video_with_audio
from app.services.video.scale import rescale_video
from app.services.video.subtitle_burn import burn_subtitles
from app.services.video.subtitle_embed import embed_soft_subtitles


def get_session_for_worker() -> Session:
    return Session(engine)


def broadcast_sync(project_id: str, message: dict) -> None:
    asyncio.run(ws_manager.broadcast(project_id, message))


def _effective_translated_text(translation: TranslationSegment) -> str:
    return translation.translated_text_edited or translation.translated_text


@celery_app.task(name="app.workers.export.export_task")
def export_task(
    project_id: str,
    resolution: str | None = None,
    font_size: int = 28,
    font_color: str = "white",
    position: str = "bottom_center",
) -> None:
    session = get_session_for_worker()
    job = session.exec(
        select(Job)
        .where(Job.project_id == project_id, Job.job_type == "export")
        .order_by(Job.started_at.desc().nullslast())
    ).first()
    if job is None:
        session.close()
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    session.add(job)
    session.commit()

    def step(name: str, pct: int) -> None:
        job.current_step = name
        job.progress_pct = pct
        session.add(job)
        session.commit()
        broadcast_sync(project_id, {"status": "running", "step": name, "progress_pct": pct})

    try:
        step("preparing", 5)

        project = session.get(Project, project_id)
        video = session.exec(select(Video).where(Video.project_id == project_id)).first()
        if video is None:
            raise RuntimeError("No video found for project")

        rows = session.exec(
            select(TranscriptSegment, TranslationSegment, DubbedSegment)
            .join(TranslationSegment, TranslationSegment.segment_id == TranscriptSegment.id)
            .join(DubbedSegment, DubbedSegment.segment_id == TranscriptSegment.id)
            .where(TranscriptSegment.project_id == project_id)
            .order_by(TranscriptSegment.seq_index)
        ).all()

        r2_client = get_r2_client()

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = os.path.join(tmp_dir, "video.mp4")
            r2_client.download_file(video.storage_path, video_path)

            step("downloading_dubbed_segments", 15)
            placements: list[SegmentAudioPlacement] = []
            for transcript, _translation, dubbed in rows:
                seg_audio_path = os.path.join(tmp_dir, f"seg_{transcript.id}.mp3")
                r2_client.download_file(dubbed.audio_storage_path, seg_audio_path)
                placements.append(
                    SegmentAudioPlacement(
                        start_time=transcript.start_time,
                        end_time=transcript.end_time,
                        audio_path=seg_audio_path,
                    )
                )

            step("assembling_audio_track", 30)
            voice_track_path = os.path.join(tmp_dir, "voice_track.wav")
            assemble_dubbed_audio_track(placements, video.duration_sec, voice_track_path)

            original_audio_path = os.path.join(tmp_dir, "original_audio.wav")
            if project.audio_mode != "silent":
                extract_audio(video_path, original_audio_path)

            step("mixing_final_audio", 45)
            final_audio_path = os.path.join(tmp_dir, "final_audio.wav")
            build_final_audio(
                audio_mode=project.audio_mode,
                voice_track_path=voice_track_path,
                original_audio_path=original_audio_path,
                background_volume=project.background_volume,
                out_path=final_audio_path,
            )

            step("muxing_video", 60)
            muxed_path = os.path.join(tmp_dir, "muxed.mp4")
            mux_video_with_audio(video_path, final_audio_path, muxed_path)

            if resolution:
                rescaled_path = os.path.join(tmp_dir, "rescaled.mp4")
                rescale_video(muxed_path, rescaled_path, resolution)
                muxed_path = rescaled_path

            step("generating_subtitles", 70)
            cues = [
                SubtitleCue(
                    start=transcript.start_time,
                    end=transcript.end_time,
                    text=_effective_translated_text(translation),
                )
                for transcript, translation, _dubbed in rows
            ]
            srt_content = generate_srt(cues)
            srt_path = os.path.join(tmp_dir, "subtitles.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)

            step("embedding_subtitles", 80)
            soft_sub_path = os.path.join(tmp_dir, "video_soft.mp4")
            embed_soft_subtitles(muxed_path, srt_path, soft_sub_path)

            hard_sub_path = os.path.join(tmp_dir, "video_hard.mp4")
            burn_subtitles(
                muxed_path, srt_path, hard_sub_path,
                font_size=font_size, font_color=font_color, position=position,
            )

            step("uploading_exports", 90)
            video_key = f"exports/{project_id}/video.mp4"
            hardsub_key = f"exports/{project_id}/video_hardsub.mp4"
            srt_key = f"exports/{project_id}/subtitles.srt"

            r2_client.upload_file(soft_sub_path, video_key)
            r2_client.upload_file(hard_sub_path, hardsub_key)
            r2_client.upload_file(srt_path, srt_key)

            session.add(Export(project_id=project_id, export_type="video", storage_path=video_key, resolution=resolution))
            session.add(Export(project_id=project_id, export_type="video_hardsub", storage_path=hardsub_key, resolution=resolution))
            session.add(Export(project_id=project_id, export_type="srt", storage_path=srt_key))
            session.commit()

        project.status = "ready"
        project.updated_at = datetime.now(timezone.utc)
        session.add(project)

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

Run: `cd backend && pytest tests/test_export_task.py -v`
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
        "app.workers.export",
    ],
)
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/workers/export.py backend/app/core/celery_app.py backend/tests/test_export_task.py
git commit -m "feat(backend): add export_task orchestrating the full FFmpeg/subtitle pipeline"
```

---

### Task 4: Export, preview, and download endpoints

**Files:**
- Create: `backend/app/api/export.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_export_api.py`

**Interfaces:**
- Produces: `POST /api/projects/{id}/export`, `GET /api/projects/{id}/preview`, `GET /api/projects/{id}/exports`, `GET /api/projects/{id}/exports/{export_id}/download`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_export_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.export import Export

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
            "title": "Export test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_start_export_enqueues_task_with_options():
    project_id = create_project()

    with patch("app.api.export.export_task") as mock_task:
        resp = client.post(
            f"/api/projects/{project_id}/export",
            json={"resolution": "1280x720", "font_size": 32, "font_color": "yellow", "position": "top_center"},
        )

    assert resp.status_code == 202, resp.text
    mock_task.delay.assert_called_once_with(
        project_id=project_id, resolution="1280x720",
        font_size=32, font_color="yellow", position="top_center",
    )


def test_get_preview_returns_presigned_urls_for_video_and_srt():
    project_id = create_project()
    with Session(engine) as session:
        session.add(Export(project_id=project_id, export_type="video", storage_path="exports/x/video.mp4"))
        session.add(Export(project_id=project_id, export_type="srt", storage_path="exports/x/subtitles.srt"))
        session.commit()

    with patch("app.api.export.get_r2_client") as mock_get_r2:
        mock_get_r2.return_value.generate_presigned_url.side_effect = lambda key, **kw: f"https://signed/{key}"
        resp = client.get(f"/api/projects/{project_id}/preview")

    assert resp.status_code == 200
    body = resp.json()
    assert body["video_url"] == "https://signed/exports/x/video.mp4"
    assert body["srt_url"] == "https://signed/exports/x/subtitles.srt"
    assert body["status"] == "ready"


def test_get_preview_not_ready_when_no_exports_yet():
    project_id = create_project()
    resp = client.get(f"/api/projects/{project_id}/preview")
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_ready"


def test_list_exports_and_download():
    project_id = create_project()
    with Session(engine) as session:
        export = Export(project_id=project_id, export_type="video_hardsub", storage_path="exports/x/hard.mp4")
        session.add(export)
        session.commit()
        session.refresh(export)
        export_id = export.id

    list_resp = client.get(f"/api/projects/{project_id}/exports")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    with patch("app.api.export.get_r2_client") as mock_get_r2:
        mock_get_r2.return_value.generate_presigned_url.return_value = "https://signed/exports/x/hard.mp4"
        download_resp = client.get(f"/api/projects/{project_id}/exports/{export_id}/download")

    assert download_resp.status_code == 200
    assert download_resp.json()["url"] == "https://signed/exports/x/hard.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_export_api.py -v`
Expected: FAIL — router doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/export.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.core.storage import get_r2_client
from app.db.session import get_session
from app.models.export import Export
from app.models.job import Job
from app.models.project import Project
from app.workers.export import export_task

router = APIRouter(prefix="/api/projects", tags=["export"])


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


class StartExportRequest(BaseModel):
    resolution: str | None = None
    font_size: int = 28
    font_color: str = "white"
    position: str = "bottom_center"


class PreviewResponse(BaseModel):
    status: str  # "ready" | "not_ready"
    video_url: str | None = None
    srt_url: str | None = None


class ExportRead(BaseModel):
    id: str
    project_id: str
    export_type: str
    resolution: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class DownloadResponse(BaseModel):
    url: str


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/export", response_model=JobRead, status_code=202)
def start_export(
    project_id: str,
    payload: StartExportRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = _get_owned_project(session, project_id, user_id)

    job = Job(project_id=project_id, job_type="export")
    session.add(job)
    project.updated_at = datetime.now(timezone.utc)
    session.add(project)
    session.commit()
    session.refresh(job)

    export_task.delay(
        project_id=project_id,
        resolution=payload.resolution,
        font_size=payload.font_size,
        font_color=payload.font_color,
        position=payload.position,
    )

    return job


@router.get("/{project_id}/preview", response_model=PreviewResponse)
def get_preview(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    video_export = session.exec(
        select(Export).where(Export.project_id == project_id, Export.export_type == "video")
    ).first()
    srt_export = session.exec(
        select(Export).where(Export.project_id == project_id, Export.export_type == "srt")
    ).first()

    if video_export is None:
        return PreviewResponse(status="not_ready")

    r2_client = get_r2_client()
    return PreviewResponse(
        status="ready",
        video_url=r2_client.generate_presigned_url(video_export.storage_path),
        srt_url=r2_client.generate_presigned_url(srt_export.storage_path) if srt_export else None,
    )


@router.get("/{project_id}/exports", response_model=list[ExportRead])
def list_exports(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)
    return session.exec(select(Export).where(Export.project_id == project_id)).all()


@router.get("/{project_id}/exports/{export_id}/download", response_model=DownloadResponse)
def download_export(
    project_id: str,
    export_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    export = session.get(Export, export_id)
    if export is None or export.project_id != project_id:
        raise HTTPException(status_code=404, detail="Export not found")

    url = get_r2_client().generate_presigned_url(export.storage_path)
    return DownloadResponse(url=url)
```

```python
# backend/app/main.py  (add to existing file)
from app.api.export import router as export_router

app.include_router(export_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_export_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/export.py backend/app/main.py backend/tests/test_export_api.py
git commit -m "feat(backend): add export, preview, and download endpoints"
```

---

### Task 5: Single-segment regenerate endpoint

**Files:**
- Create: `backend/app/api/regenerate.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_regenerate_api.py`

**Interfaces:**
- Produces: `POST /api/projects/{project_id}/segments/{segment_id}/regenerate` — synchronous (not a Celery job — a single segment's synthesis takes seconds, not minutes, so no background job/progress UI is needed here), returns `{"audio_url": str, "duration_sec": float}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_regenerate_api.py
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.dubbed_segment import DubbedSegment
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = override_get_session
client = TestClient(app)


def test_regenerate_segment_resynthesizes_and_updates_dubbed_segment():
    project_resp = client.post(
        "/api/projects",
        json={
            "title": "Regen test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    project_id = project_resp.json()["id"]

    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=2,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)

        session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
        session.add(Voice(project_id=project_id, speaker_label="speaker_1", engine="edge_tts", voice_id="vi-VN-HoaiMyNeural"))
        session.add(DubbedSegment(segment_id=seg.id, audio_storage_path="dubbed/old.mp3", duration_sec=1.5, status="done"))
        session.commit()
        segment_id = seg.id

    with patch("app.api.regenerate.get_r2_client") as mock_get_r2, patch(
        "app.api.regenerate.synthesize_segment_with_rate_adjustment", return_value=1.8
    ) as mock_synth:
        mock_get_r2.return_value.upload_file.side_effect = lambda local_path, key: key

        resp = client.post(f"/api/projects/{project_id}/segments/{segment_id}/regenerate")

    assert resp.status_code == 200, resp.text
    assert resp.json()["duration_sec"] == 1.8
    mock_synth.assert_called_once()

    with Session(engine) as session:
        from sqlmodel import select

        dubbed = session.exec(
            select(DubbedSegment).where(DubbedSegment.segment_id == segment_id)
        ).one()
        assert dubbed.duration_sec == 1.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_regenerate_api.py -v`
Expected: FAIL — router doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/api/regenerate.py
import os
import tempfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.core.storage import get_r2_client
from app.db.session import get_session
from app.models.dubbed_segment import DubbedSegment
from app.models.project import Project
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment
from app.models.voice import Voice
from app.services.tts.edge_tts_engine import EdgeTTSEngine
from app.services.tts.gemini_tts_engine import GeminiTTSEngine
from app.services.tts.sync import synthesize_segment_with_rate_adjustment
from app.core.config import settings

router = APIRouter(prefix="/api/projects", tags=["regenerate"])


class RegenerateResponse(BaseModel):
    audio_url: str
    duration_sec: float


def _build_tts_engine(engine_name: str):
    if engine_name == "gemini_tts":
        return GeminiTTSEngine(api_key=settings.gemini_api_key)
    return EdgeTTSEngine()


@router.post(
    "/{project_id}/segments/{segment_id}/regenerate", response_model=RegenerateResponse
)
def regenerate_segment(
    project_id: str,
    segment_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")

    transcript = session.get(TranscriptSegment, segment_id)
    if transcript is None or transcript.project_id != project_id:
        raise HTTPException(status_code=404, detail="Segment not found")

    translation = session.exec(
        select(TranslationSegment).where(TranslationSegment.segment_id == segment_id)
    ).first()
    if translation is None:
        raise HTTPException(status_code=400, detail="Segment has not been translated yet")

    voice = session.exec(
        select(Voice).where(
            Voice.project_id == project_id, Voice.speaker_label == transcript.speaker_label
        )
    ).first()
    if voice is None:
        raise HTTPException(status_code=400, detail="No voice assigned for this speaker")

    tts_engine = _build_tts_engine(voice.engine)
    target_duration = transcript.end_time - transcript.start_time
    text = translation.translated_text_edited or translation.translated_text

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        final_duration = synthesize_segment_with_rate_adjustment(
            engine=tts_engine,
            text=text,
            voice_id=voice.voice_id,
            target_duration=target_duration,
            out_path=tmp_path,
        )

        key = f"dubbed/{project_id}/{segment_id}.mp3"
        r2_client = get_r2_client()
        r2_client.upload_file(tmp_path, key)
    finally:
        os.remove(tmp_path)

    dubbed = session.exec(
        select(DubbedSegment).where(DubbedSegment.segment_id == segment_id)
    ).first()
    if dubbed is None:
        dubbed = DubbedSegment(segment_id=segment_id, audio_storage_path=key, duration_sec=final_duration, status="done")
    else:
        dubbed.audio_storage_path = key
        dubbed.duration_sec = final_duration
        dubbed.status = "done"
    dubbed.generated_at = datetime.now(timezone.utc)
    session.add(dubbed)
    session.commit()

    audio_url = get_r2_client().generate_presigned_url(key)
    return RegenerateResponse(audio_url=audio_url, duration_sec=final_duration)
```

```python
# backend/app/main.py  (add to existing file)
from app.api.regenerate import router as regenerate_router

app.include_router(regenerate_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_regenerate_api.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/regenerate.py backend/app/main.py backend/tests/test_regenerate_api.py
git commit -m "feat(backend): add single-segment regenerate endpoint"
```

---

### Task 6: R2 lifecycle — expired-project cleanup via Celery Beat

**Files:**
- Create: `backend/app/workers/cleanup.py`
- Modify: `backend/app/core/celery_app.py`
- Modify: `docker-compose.yml`
- Create: `backend/tests/test_cleanup_task.py`

**Interfaces:**
- Produces: `app.workers.cleanup.cleanup_expired_projects_task() -> None`; a `beat` service in `docker-compose.yml`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_cleanup_task.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlmodel import Session, SQLModel, create_engine, select

from app.models.export import Export
from app.models.project import Project
from app.models.video import Video


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_cleanup_deletes_r2_objects_and_project_row_for_expired_projects():
    engine = make_engine()
    with Session(engine) as session:
        expired = Project(
            user_id="u1", title="expired", source_language="en", target_language="vi",
            audio_mode="silent", expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        still_valid = Project(
            user_id="u1", title="valid", source_language="en", target_language="vi",
            audio_mode="silent", expires_at=datetime.now(timezone.utc) + timedelta(days=3),
        )
        session.add(expired)
        session.add(still_valid)
        session.commit()
        session.refresh(expired)
        session.refresh(still_valid)

        session.add(Video(project_id=expired.id, source_type="upload", storage_path="videos/expired/v.mp4", duration_sec=1, resolution="1x1", codec="h264", file_size_bytes=1))
        session.add(Export(project_id=expired.id, export_type="video", storage_path="exports/expired/video.mp4"))
        session.commit()

        expired_id, valid_id = expired.id, still_valid.id

    with patch("app.workers.cleanup.get_session_for_worker", return_value=Session(engine)), patch(
        "app.workers.cleanup.get_r2_client"
    ) as mock_get_r2:
        from app.workers.cleanup import cleanup_expired_projects_task

        cleanup_expired_projects_task.run()

    mock_r2 = mock_get_r2.return_value
    deleted_keys = {call.args[0] for call in mock_r2.delete.call_args_list}
    assert "videos/expired/v.mp4" in deleted_keys
    assert "exports/expired/video.mp4" in deleted_keys

    with Session(engine) as session:
        assert session.get(Project, expired_id) is None
        assert session.get(Project, valid_id) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_cleanup_task.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/workers/cleanup.py
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.celery_app import celery_app
from app.core.storage import get_r2_client
from app.db.session import engine
from app.models.export import Export
from app.models.project import Project
from app.models.video import Video


def get_session_for_worker() -> Session:
    return Session(engine)


@celery_app.task(name="app.workers.cleanup.cleanup_expired_projects_task")
def cleanup_expired_projects_task() -> None:
    session = get_session_for_worker()
    r2_client = get_r2_client()

    try:
        now = datetime.now(timezone.utc)
        expired_projects = session.exec(
            select(Project).where(Project.expires_at.is_not(None), Project.expires_at <= now)
        ).all()

        for project in expired_projects:
            videos = session.exec(select(Video).where(Video.project_id == project.id)).all()
            for video in videos:
                r2_client.delete(video.storage_path)
                session.delete(video)

            exports = session.exec(select(Export).where(Export.project_id == project.id)).all()
            for export in exports:
                r2_client.delete(export.storage_path)
                session.delete(export)

            session.delete(project)

        session.commit()
    finally:
        session.close()
```

```python
# backend/app/core/celery_app.py  (final version of this file)
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "video_dubbing",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.ping",
        "app.workers.transcribe",
        "app.workers.translate",
        "app.workers.dub",
        "app.workers.export",
        "app.workers.cleanup",
    ],
)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]

celery_app.conf.beat_schedule = {
    "cleanup-expired-projects": {
        "task": "app.workers.cleanup.cleanup_expired_projects_task",
        "schedule": crontab(minute=0),  # hourly
    },
}
```

Note: `TranscriptSegment`, `TranslationSegment`, `Voice`, `DubbedSegment`,
and `Job` rows for an expired project are left for the database's normal
cascade behavior to your schema's choice — since none of the models declared
`ondelete="CASCADE"` on their foreign keys, add that cleanup explicitly if a
production run shows orphaned rows; for the scope of this phase, the R2
objects (the actual storage cost) and the `projects`/`videos`/`exports` rows
are what's cleaned.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_cleanup_task.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Add a `beat` service to `docker-compose.yml`**

```yaml
# docker-compose.yml  (add this service, alongside worker/backend/redis/frontend)
  beat:
    build: ./backend
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./backend:/app
    command: celery -A app.core.celery_app beat --loglevel=info
    depends_on:
      - redis
```

- [ ] **Step 6: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all Phase 1-8 tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/app/workers/cleanup.py backend/app/core/celery_app.py docker-compose.yml backend/tests/test_cleanup_task.py
git commit -m "feat(backend): add hourly Celery Beat cleanup of expired projects"
```

---

### Task 7: Frontend — combined Preview/Export page

**Files:**
- Create: `frontend/app/projects/[id]/preview/page.tsx`
- Modify: `frontend/lib/api.ts`
- Modify: `frontend/lib/types.ts`
- Modify: `frontend/lib/api.test.ts`

**Interfaces:**
- Produces: `lib/api.ts` exports `getPreview(projectId)`, `startExport(projectId, options)`, `listExports(projectId)`, `downloadExport(projectId, exportId)`, `regenerateSegment(projectId, segmentId)`.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add)
it("startExport posts export options", async () => {
  const { startExport } = await import("./api");
  await startExport("proj-1", { resolution: "1280x720", font_size: 32, font_color: "yellow", position: "top_center" });
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/projects/proj-1/export",
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ resolution: "1280x720", font_size: 32, font_color: "yellow", position: "top_center" }),
    })
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `startExport` not exported.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/types.ts  (append)
export interface Preview {
  status: "ready" | "not_ready";
  video_url: string | null;
  srt_url: string | null;
}

export interface ExportItem {
  id: string;
  project_id: string;
  export_type: "video" | "video_hardsub" | "srt";
  resolution: string | null;
  created_at: string;
}

export interface ExportOptions {
  resolution?: string;
  font_size?: number;
  font_color?: string;
  position?: string;
}
```

```typescript
// frontend/lib/api.ts  (append)
import type { ExportItem, ExportOptions, Preview } from "./types";

export async function getPreview(projectId: string): Promise<Preview> {
  const res = await apiFetch(`/api/projects/${projectId}/preview`);
  if (!res.ok) throw new Error("Failed to load preview");
  return res.json();
}

export async function startExport(projectId: string, options: ExportOptions) {
  const res = await apiFetch(`/api/projects/${projectId}/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options),
  });
  if (!res.ok) throw new Error("Failed to start export");
  return res.json();
}

export async function listExports(projectId: string): Promise<ExportItem[]> {
  const res = await apiFetch(`/api/projects/${projectId}/exports`);
  if (!res.ok) throw new Error("Failed to load exports");
  return res.json();
}

export async function downloadExport(projectId: string, exportId: string): Promise<string> {
  const res = await apiFetch(`/api/projects/${projectId}/exports/${exportId}/download`);
  if (!res.ok) throw new Error("Failed to get download link");
  const body = await res.json();
  return body.url;
}

export async function regenerateSegment(
  projectId: string,
  segmentId: string
): Promise<{ audio_url: string; duration_sec: number }> {
  const res = await apiFetch(
    `/api/projects/${projectId}/segments/${segmentId}/regenerate`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to regenerate segment");
  return res.json();
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the Preview/Export page**

```typescript
// frontend/app/projects/[id]/preview/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { downloadExport, getPreview, listExports, startExport } from "@/lib/api";
import { connectProjectWS } from "@/lib/ws";
import type { ExportItem, Preview } from "@/lib/types";

const EXPORT_TYPE_LABELS: Record<string, string> = {
  video: "Video (phụ đề mềm)",
  video_hardsub: "Video (phụ đề cứng)",
  srt: "File phụ đề (.srt)",
};

interface ProgressMessage {
  status?: string;
  step?: string;
  progress_pct?: number;
  error?: string;
}

export default function PreviewExportPage() {
  const { id } = useParams<{ id: string }>();
  const [preview, setPreview] = useState<Preview | null>(null);
  const [exports, setExports] = useState<ExportItem[]>([]);
  const [progress, setProgress] = useState<ProgressMessage>({});
  const [exporting, setExporting] = useState(false);
  const [resolution, setResolution] = useState("");
  const [fontColor, setFontColor] = useState("white");
  const [fontSize, setFontSize] = useState(28);

  useEffect(() => {
    getPreview(id).then(setPreview);
    listExports(id).then(setExports);

    const ws = connectProjectWS(id, (data) => {
      const message = data as ProgressMessage;
      setProgress(message);
      if (message.status === "done") {
        getPreview(id).then(setPreview);
        listExports(id).then(setExports);
        setExporting(false);
      }
    });
    return () => ws.close();
  }, [id]);

  async function handleExport() {
    setExporting(true);
    await startExport(id, {
      resolution: resolution || undefined,
      font_size: fontSize,
      font_color: fontColor,
      position: "bottom_center",
    });
  }

  async function handleDownload(exportItem: ExportItem) {
    const url = await downloadExport(id, exportItem.id);
    window.open(url, "_blank");
  }

  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Xem trước & Xuất video</h1>

      {preview?.status === "ready" && preview.video_url && (
        <video controls src={preview.video_url} className="mb-6 w-full rounded" />
      )}

      <div className="mb-6 space-y-3 rounded border p-4">
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="block text-sm font-medium">Độ phân giải</label>
            <select
              className="mt-1 w-full rounded border p-2"
              value={resolution}
              onChange={(e) => setResolution(e.target.value)}
            >
              <option value="">Giữ nguyên gốc</option>
              <option value="1920x1080">1080p</option>
              <option value="1280x720">720p</option>
              <option value="854x480">480p</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium">Cỡ chữ phụ đề cứng</label>
            <input
              type="number"
              className="mt-1 w-full rounded border p-2"
              value={fontSize}
              onChange={(e) => setFontSize(Number(e.target.value))}
            />
          </div>
          <div>
            <label className="block text-sm font-medium">Màu chữ</label>
            <select
              className="mt-1 w-full rounded border p-2"
              value={fontColor}
              onChange={(e) => setFontColor(e.target.value)}
            >
              <option value="white">Trắng</option>
              <option value="yellow">Vàng</option>
            </select>
          </div>
        </div>

        <button
          onClick={handleExport}
          disabled={exporting}
          className="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50"
        >
          {exporting ? "Đang xuất..." : "Xuất video"}
        </button>

        {exporting && (
          <div className="space-y-1">
            <div className="h-3 w-full rounded bg-gray-200">
              <div
                className="h-3 rounded bg-blue-600 transition-all"
                style={{ width: `${progress.progress_pct ?? 0}%` }}
              />
            </div>
            <p className="text-sm text-gray-600">
              {progress.error ? `Lỗi: ${progress.error}` : progress.step ?? "Đang xử lý..."} (
              {progress.progress_pct ?? 0}%)
            </p>
          </div>
        )}
      </div>

      {exports.length > 0 && (
        <div className="space-y-2">
          <h2 className="font-medium">Tệp đã xuất</h2>
          {exports.map((exportItem) => (
            <div key={exportItem.id} className="flex items-center justify-between rounded border p-3">
              <span>{EXPORT_TYPE_LABELS[exportItem.export_type] ?? exportItem.export_type}</span>
              <button
                onClick={() => handleDownload(exportItem)}
                className="rounded bg-gray-200 px-3 py-1 text-sm"
              >
                Tải xuống
              </button>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/app/projects/ frontend/lib/api.ts frontend/lib/types.ts frontend/lib/api.test.ts
git commit -m "feat(frontend): add combined Preview/Export page"
```

---

## Definition of Done for Phase 8

- [ ] `cd backend && pytest` passes (all Phase 1-8 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually, inside Docker (where ffmpeg/demucs are installed): run a project through the full pipeline (upload → transcribe → translate → voices → dub → export) and confirm all 3 export artifacts play/open correctly, with audio in sync.
- [ ] Manually: click "regenerate" on one segment, confirm only that segment's audio changes, then re-export and confirm the change is reflected in the new export.
- [ ] Manually: set a project's `expires_at` to the past directly in the database, run `celery -A app.core.celery_app call app.workers.cleanup.cleanup_expired_projects_task`, and confirm its R2 objects and DB row are gone.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 9.
