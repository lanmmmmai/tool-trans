# Phase 2: Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user create a project, upload a video file (or import one from a YouTube/TikTok URL), validate it, extract its metadata, store it in R2, and see it listed on the Dashboard.

**Architecture:** New `Project` and `Video` SQLModel tables; a `projects` FastAPI router; an `R2Client` service wrapping boto3 for Cloudflare R2; an `ffprobe`-based metadata extractor; a `yt-dlp`-based downloader. A dev-only auth stub stands in for real login until Phase 9.

**Tech Stack:** FastAPI, SQLModel, boto3 (S3-compatible client for R2), ffprobe (via subprocess), yt-dlp, Next.js.

**Spec:** `docs/superpowers/specs/2026-09-07-video-dubbing-design.md`

## Global Constraints

- Max video duration: 60 minutes. Max file size: 2 GB (spec §Đầu vào Video).
- Accept any format FFmpeg can read — validated by running `ffprobe` on the file rather than an extension whitelist (spec §Đầu vào Video).
- URL import supports YouTube and TikTok via `yt-dlp` (spec §Đầu vào Video).
- One video processed at a time per project; multiple projects queue sequentially — no parallel-upload requirement to build here (spec §Đầu vào Video).
- **Auth is not implemented until Phase 9.** Every endpoint in this phase uses a temporary stub, `app.core.auth.get_current_user_id()`, that returns a fixed constant `DEV_USER_ID`. `Project.user_id` is stored as a plain string column with **no foreign-key constraint** to `profiles` — the `profiles` table does not exist yet (it is created in Phase 9, which also backfills the constraint). This is a deliberate, documented simplification, not an oversight.
- All primary keys across every model in this project are `str` UUIDs: `id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)`.

## Established Interfaces (produced here, consumed by later phases)

- `app.core.auth.get_current_user_id() -> str` — FastAPI dependency. Stub in this phase; **Phase 9 replaces the implementation** (same signature) with real Supabase JWT verification.
- `app.core.storage.R2Client` — `upload_file(local_path: str, key: str) -> str` (returns the storage key), `download_file(key: str, local_path: str) -> None`, `delete(key: str) -> None`, `generate_presigned_url(key: str, expires_in: int = 3600) -> str`.
- `app.services.video.ffprobe.probe_video(path: str) -> VideoProbeResult` — `VideoProbeResult(duration_sec: float, resolution: str, codec: str, file_size_bytes: int)`.
- `app.services.video.ingest.ingest_video_file(project_id: str, local_path: str, source_type: str, source_url: str | None) -> Video` — validates, probes, uploads to R2, writes the `Video` row. Used by both the direct-upload and URL-import endpoints, and importable by later phases if they ever need to (re-)ingest a file.
- `app.models.project.Project`, `app.models.video.Video` — SQLModel tables (fields as in spec §5).
- Frontend: `lib/api.ts`'s `apiFetch` (Phase 1) is reused for all calls; `app/dashboard/page.tsx` lists projects; `app/projects/new/page.tsx` is the creation form.

---

### Task 1: Auth stub dependency

**Files:**
- Create: `backend/app/core/auth.py`
- Create: `backend/tests/test_auth_stub.py`

**Interfaces:**
- Produces: `app.core.auth.get_current_user_id() -> str`, `app.core.auth.DEV_USER_ID: str`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth_stub.py
from app.core.auth import DEV_USER_ID, get_current_user_id


def test_get_current_user_id_returns_dev_user():
    assert get_current_user_id() == DEV_USER_ID
    assert isinstance(DEV_USER_ID, str)
    assert len(DEV_USER_ID) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_auth_stub.py -v`
Expected: FAIL — `app.core.auth` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/auth.py
"""
TEMPORARY STUB — replaced in Phase 9 with real Supabase JWT verification.
`get_current_user_id` keeps the same name/signature so every router written
against it in Phases 2-8 needs no changes when Phase 9 lands.
"""

DEV_USER_ID = "00000000-0000-0000-0000-000000000001"


def get_current_user_id() -> str:
    return DEV_USER_ID
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_auth_stub.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/auth.py backend/tests/test_auth_stub.py
git commit -m "feat(backend): add dev auth stub (replaced in Phase 9)"
```

---

### Task 2: `Project` and `Video` models + migration

**Files:**
- Create: `backend/app/models/project.py`
- Create: `backend/app/models/video.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/tests/test_project_model.py`

**Interfaces:**
- Produces: `app.models.project.Project`, `app.models.video.Video`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_project_model.py
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.project import Project
from app.models.video import Video


def make_engine():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    return engine


def test_create_project_and_video():
    engine = make_engine()
    with Session(engine) as session:
        project = Project(
            user_id="user-1",
            title="My video",
            source_language="en",
            target_language="vi",
            audio_mode="ducking",
        )
        session.add(project)
        session.commit()
        session.refresh(project)

        assert project.status == "draft"
        assert project.id is not None

        video = Video(
            project_id=project.id,
            source_type="upload",
            storage_path="videos/abc.mp4",
            duration_sec=120.5,
            resolution="1920x1080",
            codec="h264",
            file_size_bytes=1024,
        )
        session.add(video)
        session.commit()

        fetched = session.exec(select(Video).where(Video.project_id == project.id)).one()
        assert fetched.storage_path == "videos/abc.mp4"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_project_model.py -v`
Expected: FAIL — `app.models.project` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/models/project.py
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Project(SQLModel, table=True):
    __tablename__ = "projects"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    title: str
    source_language: str
    target_language: str
    status: str = Field(default="draft")
    audio_mode: str
    translate_engine: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    warn_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
```

```python
# backend/app/models/video.py
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


class Video(SQLModel, table=True):
    __tablename__ = "videos"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    source_type: str  # "upload" | "youtube" | "tiktok"
    source_url: Optional[str] = None
    storage_path: str
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

```python
# backend/app/models/__init__.py
from app.models.project import Project  # noqa: F401
from app.models.video import Video  # noqa: F401
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_project_model.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Generate the Alembic migration (manual, requires real `.env`)**

Run: `cd backend && alembic revision -m "add projects and videos tables" --autogenerate`
Expected: a new file under `alembic/versions/` with `op.create_table("projects", ...)` and `op.create_table("videos", ...)`. Review the generated file, then:
Run: `alembic upgrade head`

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/project.py backend/app/models/video.py backend/app/models/__init__.py backend/tests/test_project_model.py backend/alembic/versions/
git commit -m "feat(backend): add Project and Video models + migration"
```

---

### Task 3: R2 storage client

**Files:**
- Create: `backend/app/core/storage.py`
- Create: `backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `app.core.config.settings` (r2_account_id, r2_access_key_id, r2_secret_access_key, r2_bucket_name).
- Produces: `app.core.storage.R2Client` class as described in "Established Interfaces".

- [ ] **Step 1: Write the failing test**

The test uses `unittest.mock` to avoid hitting real R2 in CI; it asserts the
client builds the correct boto3 calls.

```python
# backend/tests/test_storage.py
from unittest.mock import MagicMock, patch

from app.core.storage import R2Client


def test_upload_file_calls_boto3_upload_file():
    with patch("app.core.storage.boto3.client") as mock_boto_client:
        mock_s3 = MagicMock()
        mock_boto_client.return_value = mock_s3

        client = R2Client(
            account_id="acc",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="my-bucket",
        )
        key = client.upload_file("/tmp/local.mp4", "videos/local.mp4")

        mock_s3.upload_file.assert_called_once_with(
            "/tmp/local.mp4", "my-bucket", "videos/local.mp4"
        )
        assert key == "videos/local.mp4"


def test_generate_presigned_url_calls_boto3():
    with patch("app.core.storage.boto3.client") as mock_boto_client:
        mock_s3 = MagicMock()
        mock_s3.generate_presigned_url.return_value = "https://signed.example/url"
        mock_boto_client.return_value = mock_s3

        client = R2Client(
            account_id="acc",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="my-bucket",
        )
        url = client.generate_presigned_url("videos/local.mp4", expires_in=600)

        assert url == "https://signed.example/url"
        mock_s3.generate_presigned_url.assert_called_once_with(
            "get_object",
            Params={"Bucket": "my-bucket", "Key": "videos/local.mp4"},
            ExpiresIn=600,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_storage.py -v`
Expected: FAIL — `app.core.storage` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/core/storage.py
import boto3

from app.core.config import settings


class R2Client:
    def __init__(
        self,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket_name: str,
    ):
        self.bucket_name = bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
        )

    def upload_file(self, local_path: str, key: str) -> str:
        self._s3.upload_file(local_path, self.bucket_name, key)
        return key

    def download_file(self, key: str, local_path: str) -> None:
        self._s3.download_file(self.bucket_name, key, local_path)

    def delete(self, key: str) -> None:
        self._s3.delete_object(Bucket=self.bucket_name, Key=key)

    def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket_name, "Key": key},
            ExpiresIn=expires_in,
        )


def get_r2_client() -> R2Client:
    return R2Client(
        account_id=settings.r2_account_id,
        access_key_id=settings.r2_access_key_id,
        secret_access_key=settings.r2_secret_access_key,
        bucket_name=settings.r2_bucket_name,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_storage.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/storage.py backend/tests/test_storage.py
git commit -m "feat(backend): add Cloudflare R2 storage client"
```

---

### Task 4: `ffprobe`-based video metadata extraction

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/video/__init__.py`
- Create: `backend/app/services/video/ffprobe.py`
- Create: `backend/tests/test_ffprobe.py`
- Create: `backend/tests/fixtures/make_test_video.py`

**Interfaces:**
- Produces: `app.services.video.ffprobe.probe_video(path: str) -> VideoProbeResult`, `app.services.video.ffprobe.VideoProbeResult` (dataclass: `duration_sec: float`, `resolution: str`, `codec: str`, `file_size_bytes: int`), and `app.services.video.ffprobe.ProbeError(Exception)` raised when `ffprobe` fails or the file has no usable video/audio stream.

- [ ] **Step 1: Add a tiny fixture generator (needs local `ffmpeg`, dev-machine only, not run in CI without ffmpeg present)**

```python
# backend/tests/fixtures/make_test_video.py
"""Run manually to (re)generate the 2-second test fixture used by
test_ffprobe.py: `python tests/fixtures/make_test_video.py`"""
import subprocess
from pathlib import Path

OUT = Path(__file__).parent / "tiny.mp4"


def main() -> None:
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=2",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
            "-shortest",
            str(OUT),
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the failing test**

```python
# backend/tests/test_ffprobe.py
import subprocess
from pathlib import Path

import pytest

from app.services.video.ffprobe import ProbeError, probe_video

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


@pytest.fixture(scope="module", autouse=True)
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


def test_probe_video_returns_metadata():
    result = probe_video(str(FIXTURE))
    assert 1.5 <= result.duration_sec <= 2.5
    assert result.resolution == "320x240"
    assert result.codec  # e.g. "h264"
    assert result.file_size_bytes > 0


def test_probe_video_raises_on_missing_file():
    with pytest.raises(ProbeError):
        probe_video("/nonexistent/path.mp4")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ffprobe.py -v`
Expected: FAIL — `app.services.video.ffprobe` does not exist. (Requires `ffmpeg`/`ffprobe` on PATH — inside the backend Docker image this is already installed per Phase 1's Dockerfile; on a bare host without ffmpeg, skip local runs and rely on the Docker container.)

- [ ] **Step 4: Write minimal implementation**

```python
# backend/app/services/__init__.py
```

```python
# backend/app/services/video/__init__.py
```

```python
# backend/app/services/video/ffprobe.py
import json
import os
import subprocess
from dataclasses import dataclass


class ProbeError(Exception):
    pass


@dataclass
class VideoProbeResult:
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int


def probe_video(path: str) -> VideoProbeResult:
    if not os.path.exists(path):
        raise ProbeError(f"File not found: {path}")

    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ProbeError(f"ffprobe failed for {path}: {exc}") from exc

    data = json.loads(proc.stdout)
    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise ProbeError(f"No video stream found in {path}")

    duration_sec = float(data["format"]["duration"])
    resolution = f"{video_stream['width']}x{video_stream['height']}"
    codec = video_stream["codec_name"]
    file_size_bytes = os.path.getsize(path)

    return VideoProbeResult(
        duration_sec=duration_sec,
        resolution=resolution,
        codec=codec,
        file_size_bytes=file_size_bytes,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ffprobe.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/__init__.py backend/app/services/video/ backend/tests/test_ffprobe.py backend/tests/fixtures/make_test_video.py
git commit -m "feat(backend): add ffprobe-based video metadata extraction"
```

---

### Task 5: `ingest_video_file` — validate, probe, upload, persist

**Files:**
- Create: `backend/app/services/video/ingest.py`
- Create: `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `app.services.video.ffprobe.probe_video`, `app.core.storage.R2Client`, `app.models.video.Video`, `app.models.project.Project`.
- Produces: `app.services.video.ingest.ingest_video_file(session, r2_client, project_id, local_path, source_type, source_url=None) -> Video`, `app.services.video.ingest.VideoValidationError(Exception)` (raised for duration/size violations).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ingest.py
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.project import Project
from app.services.video.ingest import VideoValidationError, ingest_video_file

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


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def project(session):
    p = Project(
        user_id="user-1",
        title="t",
        source_language="en",
        target_language="vi",
        audio_mode="ducking",
    )
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_ingest_video_file_creates_video_row(session, project):
    mock_r2 = MagicMock()
    mock_r2.upload_file.side_effect = lambda local_path, key: key

    video = ingest_video_file(
        session=session,
        r2_client=mock_r2,
        project_id=project.id,
        local_path=str(FIXTURE),
        source_type="upload",
    )

    assert video.project_id == project.id
    assert video.resolution == "320x240"
    assert video.storage_path.startswith(f"videos/{project.id}/")
    mock_r2.upload_file.assert_called_once()


def test_ingest_video_file_rejects_video_over_60_minutes(session, project, monkeypatch):
    from app.services.video import ingest as ingest_module
    from app.services.video.ffprobe import VideoProbeResult

    monkeypatch.setattr(
        ingest_module,
        "probe_video",
        lambda path: VideoProbeResult(
            duration_sec=3601, resolution="1920x1080", codec="h264", file_size_bytes=100
        ),
    )
    mock_r2 = MagicMock()

    with pytest.raises(VideoValidationError, match="60"):
        ingest_video_file(
            session=session,
            r2_client=mock_r2,
            project_id=project.id,
            local_path=str(FIXTURE),
            source_type="upload",
        )
    mock_r2.upload_file.assert_not_called()


def test_ingest_video_file_rejects_file_over_2gb(session, project, monkeypatch):
    from app.services.video import ingest as ingest_module
    from app.services.video.ffprobe import VideoProbeResult

    monkeypatch.setattr(
        ingest_module,
        "probe_video",
        lambda path: VideoProbeResult(
            duration_sec=60,
            resolution="1920x1080",
            codec="h264",
            file_size_bytes=2 * 1024 * 1024 * 1024 + 1,
        ),
    )
    mock_r2 = MagicMock()

    with pytest.raises(VideoValidationError, match="2 ?GB|size"):
        ingest_video_file(
            session=session,
            r2_client=mock_r2,
            project_id=project.id,
            local_path=str(FIXTURE),
            source_type="upload",
        )
    mock_r2.upload_file.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ingest.py -v`
Expected: FAIL — `app.services.video.ingest` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/video/ingest.py
import os

from sqlmodel import Session

from app.core.storage import R2Client
from app.models.video import Video
from app.services.video.ffprobe import probe_video

MAX_DURATION_SEC = 60 * 60
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024


class VideoValidationError(Exception):
    pass


def ingest_video_file(
    session: Session,
    r2_client: R2Client,
    project_id: str,
    local_path: str,
    source_type: str,
    source_url: str | None = None,
) -> Video:
    metadata = probe_video(local_path)

    if metadata.duration_sec > MAX_DURATION_SEC:
        raise VideoValidationError(
            f"Video is {metadata.duration_sec / 60:.1f} minutes; max is 60 minutes."
        )
    if metadata.file_size_bytes > MAX_FILE_SIZE_BYTES:
        raise VideoValidationError(
            f"Video is {metadata.file_size_bytes / (1024**3):.2f} GB; max size is 2 GB."
        )

    key = f"videos/{project_id}/{os.path.basename(local_path)}"
    r2_client.upload_file(local_path, key)

    video = Video(
        project_id=project_id,
        source_type=source_type,
        source_url=source_url,
        storage_path=key,
        duration_sec=metadata.duration_sec,
        resolution=metadata.resolution,
        codec=metadata.codec,
        file_size_bytes=metadata.file_size_bytes,
    )
    session.add(video)
    session.commit()
    session.refresh(video)
    return video
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ingest.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/video/ingest.py backend/tests/test_ingest.py
git commit -m "feat(backend): add ingest_video_file (validate + probe + upload + persist)"
```

---

### Task 6: Project CRUD endpoints

**Files:**
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/project.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/projects.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_projects_api.py`

**Interfaces:**
- Produces: `app.schemas.project.ProjectCreate`, `ProjectRead`, `ProjectUpdate`; router mounted at `/api/projects` exposing `POST /`, `GET /`, `GET /{id}`, `PATCH /{id}`, `DELETE /{id}`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_projects_api.py
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


def test_create_and_get_project():
    create_resp = client.post(
        "/api/projects",
        json={
            "title": "Video của tôi",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "ducking",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["status"] == "draft"
    assert created["title"] == "Video của tôi"

    get_resp = client.get(f"/api/projects/{created['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == created["id"]


def test_list_projects_only_returns_current_user_projects():
    client.post(
        "/api/projects",
        json={
            "title": "P1",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "silent",
        },
    )
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert all(p["user_id"] == "00000000-0000-0000-0000-000000000001" for p in body)


def test_update_project_title():
    create_resp = client.post(
        "/api/projects",
        json={
            "title": "Old title",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "silent",
        },
    )
    project_id = create_resp.json()["id"]

    patch_resp = client.patch(f"/api/projects/{project_id}", json={"title": "New title"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "New title"


def test_delete_project():
    create_resp = client.post(
        "/api/projects",
        json={
            "title": "To delete",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "silent",
        },
    )
    project_id = create_resp.json()["id"]

    delete_resp = client.delete(f"/api/projects/{project_id}")
    assert delete_resp.status_code == 204

    get_resp = client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 404


def test_get_nonexistent_project_returns_404():
    resp = client.get("/api/projects/does-not-exist")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_projects_api.py -v`
Expected: FAIL — `app.api.projects` / `app.schemas.project` do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/schemas/__init__.py
```

```python
# backend/app/schemas/project.py
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    title: str
    source_language: str
    target_language: str
    audio_mode: str
    translate_engine: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    audio_mode: Optional[str] = None
    translate_engine: Optional[str] = None
    status: Optional[str] = None


class ProjectRead(BaseModel):
    id: str
    user_id: str
    title: str
    source_language: str
    target_language: str
    status: str
    audio_mode: str
    translate_engine: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
```

```python
# backend/app/api/__init__.py
```

```python
# backend/app/api/projects.py
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_user_id
from app.db.session import get_session
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=201)
def create_project(
    payload: ProjectCreate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = Project(user_id=user_id, **payload.model_dump())
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    return session.exec(select(Project).where(Project.user_id == user_id)).all()


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(project, field, value)
    project.updated_at = datetime.now(timezone.utc)

    session.add(project)
    session.commit()
    session.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
def delete_project(
    project_id: str,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    session.delete(project)
    session.commit()
```

```python
# backend/app/main.py
from fastapi import FastAPI

from app.api.projects import router as projects_router

app = FastAPI(title="AI Video Dubbing API")
app.include_router(projects_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_projects_api.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && pytest -v`
Expected: all tests from Phases 1-2 pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/ backend/app/api/ backend/app/main.py backend/tests/test_projects_api.py
git commit -m "feat(backend): add project CRUD endpoints"
```

---

### Task 7: Upload + URL-import endpoints

**Files:**
- Modify: `backend/app/api/projects.py`
- Create: `backend/app/services/video/downloader.py`
- Create: `backend/tests/test_upload_api.py`
- Create: `backend/tests/test_downloader.py`

**Interfaces:**
- Produces: `POST /api/projects/{id}/upload` (multipart), `POST /api/projects/{id}/import-url` (`{"url": str}`), both returning `VideoRead`; `app.services.video.downloader.download_from_url(url: str, dest_dir: str) -> str` (returns the downloaded file's local path).
- Consumes: `app.services.video.ingest.ingest_video_file`, `app.core.storage.get_r2_client`.

- [ ] **Step 1: Write the failing test for upload**

```python
# backend/tests/test_upload_api.py
import io
import subprocess
from pathlib import Path
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

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.mp4"


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


def create_project():
    resp = client.post(
        "/api/projects",
        json={
            "title": "Upload test",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_upload_video_creates_video_row():
    ensure_fixture()
    project_id = create_project()

    with patch("app.api.projects.get_r2_client") as mock_get_r2:
        mock_r2 = mock_get_r2.return_value
        mock_r2.upload_file.side_effect = lambda local_path, key: key

        with open(FIXTURE, "rb") as f:
            resp = client.post(
                f"/api/projects/{project_id}/upload",
                files={"file": ("tiny.mp4", f, "video/mp4")},
            )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["resolution"] == "320x240"


def test_upload_rejects_non_video_file():
    project_id = create_project()

    with patch("app.api.projects.get_r2_client"):
        resp = client.post(
            f"/api/projects/{project_id}/upload",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        )

    assert resp.status_code == 400
```

- [ ] **Step 2: Write the failing test for URL import**

```python
# backend/tests/test_downloader.py
from unittest.mock import MagicMock, patch

from app.services.video.downloader import download_from_url


def test_download_from_url_invokes_yt_dlp_and_returns_path():
    with patch("app.services.video.downloader.yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl = MagicMock()
        mock_ydl.__enter__.return_value = mock_ydl
        mock_ydl.extract_info.return_value = {"id": "abc123", "ext": "mp4"}
        mock_ydl.prepare_filename.return_value = "/tmp/dest/abc123.mp4"
        mock_ydl_cls.return_value = mock_ydl

        path = download_from_url("https://www.youtube.com/watch?v=abc123", "/tmp/dest")

        assert path == "/tmp/dest/abc123.mp4"
        mock_ydl.extract_info.assert_called_once_with(
            "https://www.youtube.com/watch?v=abc123", download=True
        )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_upload_api.py tests/test_downloader.py -v`
Expected: FAIL — upload/import-url routes and `app.services.video.downloader` don't exist yet.

- [ ] **Step 4: Add `yt-dlp` dependency**

Add `"yt-dlp>=2024.8"` to `backend/pyproject.toml`'s `dependencies` list, then run `pip install -e ".[dev]"`.

- [ ] **Step 5: Write minimal implementation — downloader**

```python
# backend/app/services/video/downloader.py
import os

import yt_dlp


def download_from_url(url: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    opts = {
        "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
        "format": "bv*[filesize<2G]+ba/b[filesize<2G]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.extract_info(url, download=True)
        return ydl.prepare_filename({"id": "abc123", "ext": "mp4"}) if False else _resolved_path(ydl, dest_dir)


def _resolved_path(ydl: "yt_dlp.YoutubeDL", dest_dir: str) -> str:
    # yt_dlp.prepare_filename needs the info dict; call it the normal way in
    # production code paths (kept simple here since the unit test mocks
    # extract_info's return value directly).
    return ydl.prepare_filename(ydl.extract_info.return_value if hasattr(ydl.extract_info, "return_value") else {})
```

- [ ] **Step 6: Run the downloader test, notice the implementation above is awkward, and simplify**

The mocked-`return_value` approach above is a smell — real `yt_dlp.YoutubeDL.extract_info` returns the info dict directly, so just use that return value instead of re-deriving it:

```python
# backend/app/services/video/downloader.py
import os

import yt_dlp


def download_from_url(url: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    opts = {
        "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
        "format": "bv*[filesize<2G]+ba/b[filesize<2G]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)
```

Run: `cd backend && pytest tests/test_downloader.py -v`
Expected: PASS (1 passed)

- [ ] **Step 7: Write minimal implementation — upload/import-url endpoints**

```python
# backend/app/api/projects.py  (append to the existing file, after the imports)
import tempfile

from fastapi import File, UploadFile
from pydantic import BaseModel

from app.core.storage import get_r2_client
from app.models.video import Video
from app.services.video.downloader import download_from_url
from app.services.video.ingest import VideoValidationError, ingest_video_file


class ImportUrlRequest(BaseModel):
    url: str


class VideoRead(BaseModel):
    id: str
    project_id: str
    source_type: str
    source_url: str | None
    storage_path: str
    duration_sec: float
    resolution: str
    codec: str
    file_size_bytes: int

    class Config:
        from_attributes = True


def _get_owned_project(session: Session, project_id: str, user_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.user_id != user_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.post("/{project_id}/upload", response_model=VideoRead, status_code=201)
def upload_video(
    project_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    if not (file.content_type or "").startswith("video/"):
        raise HTTPException(status_code=400, detail="File must be a video")

    with tempfile.NamedTemporaryFile(delete=False, suffix=f"_{file.filename}") as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        video = ingest_video_file(
            session=session,
            r2_client=get_r2_client(),
            project_id=project_id,
            local_path=tmp_path,
            source_type="upload",
        )
    except VideoValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        os.remove(tmp_path)

    return video


@router.post("/{project_id}/import-url", response_model=VideoRead, status_code=201)
def import_video_from_url(
    project_id: str,
    payload: ImportUrlRequest,
    session: Session = Depends(get_session),
    user_id: str = Depends(get_current_user_id),
):
    _get_owned_project(session, project_id, user_id)

    with tempfile.TemporaryDirectory() as dest_dir:
        local_path = download_from_url(payload.url, dest_dir)
        try:
            video = ingest_video_file(
                session=session,
                r2_client=get_r2_client(),
                project_id=project_id,
                local_path=local_path,
                source_type="youtube" if "youtube" in payload.url or "youtu.be" in payload.url else "tiktok",
                source_url=payload.url,
            )
        except VideoValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return video
```

Also add `import os` to the top of `backend/app/api/projects.py` if not already present.

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_upload_api.py tests/test_downloader.py -v`
Expected: PASS (3 passed)

- [ ] **Step 9: Run the full backend suite**

Run: `cd backend && pytest -v`
Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/app/api/projects.py backend/app/services/video/downloader.py backend/tests/test_upload_api.py backend/tests/test_downloader.py backend/pyproject.toml
git commit -m "feat(backend): add video upload and YouTube/TikTok URL import endpoints"
```

---

### Task 8: Frontend — Dashboard + New Project page

**Files:**
- Create: `frontend/app/dashboard/page.tsx`
- Create: `frontend/app/projects/new/page.tsx`
- Create: `frontend/lib/types.ts`
- Create: `frontend/lib/api.test.ts` (extend — new test cases)

**Interfaces:**
- Consumes: `apiFetch` (Phase 1).
- Produces: `lib/types.ts` exports `Project` type mirroring `ProjectRead`; `/dashboard` route; `/projects/new` route.

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/lib/api.test.ts  (add this test case to the existing describe block)
it("listProjects fetches from /api/projects", async () => {
  const { listProjects } = await import("./api");
  await listProjects();
  expect(fetch).toHaveBeenCalledWith(
    "http://localhost:8000/api/projects",
    undefined
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `listProjects` is not exported from `lib/api.ts`.

- [ ] **Step 3: Write minimal implementation**

```typescript
// frontend/lib/types.ts
export interface Project {
  id: string;
  user_id: string;
  title: string;
  source_language: string;
  target_language: string;
  status: string;
  audio_mode: string;
  translate_engine: string | null;
  created_at: string;
  updated_at: string;
}
```

```typescript
// frontend/lib/api.ts  (append to the existing file)
import type { Project } from "./types";

export async function listProjects(): Promise<Project[]> {
  const res = await apiFetch("/api/projects");
  if (!res.ok) throw new Error("Failed to load projects");
  return res.json();
}

export async function createProject(input: {
  title: string;
  source_language: string;
  target_language: string;
  audio_mode: string;
}): Promise<Project> {
  const res = await apiFetch("/api/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function uploadVideo(projectId: string, file: File): Promise<void> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await apiFetch(`/api/projects/${projectId}/upload`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to upload video");
}

export async function importVideoFromUrl(projectId: string, url: string): Promise<void> {
  const res = await apiFetch(`/api/projects/${projectId}/import-url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error("Failed to import video");
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS

- [ ] **Step 5: Build the Dashboard page**

```typescript
// frontend/app/dashboard/page.tsx
import Link from "next/link";
import { listProjects } from "@/lib/api";

export default async function DashboardPage() {
  const projects = await listProjects();

  return (
    <main className="mx-auto max-w-3xl p-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Dự án của tôi</h1>
        <Link href="/projects/new" className="rounded bg-blue-600 px-4 py-2 text-white">
          + Dự án mới
        </Link>
      </div>

      {projects.length === 0 ? (
        <p className="text-gray-500">Chưa có dự án nào. Bắt đầu bằng cách tạo dự án mới.</p>
      ) : (
        <ul className="space-y-3">
          {projects.map((project) => (
            <li key={project.id} className="rounded border p-4">
              <div className="font-medium">{project.title}</div>
              <div className="text-sm text-gray-500">
                {project.source_language} → {project.target_language} · {project.status}
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
```

- [ ] **Step 6: Build the New Project page**

```typescript
// frontend/app/projects/new/page.tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createProject, importVideoFromUrl, uploadVideo } from "@/lib/api";

const SOURCE_LANGUAGES = [
  { value: "en", label: "Tiếng Anh" },
  { value: "zh", label: "Tiếng Trung" },
  { value: "ja", label: "Tiếng Nhật" },
];

const AUDIO_MODES = [
  { value: "silent", label: "Chỉ giọng mới (im lặng nền)" },
  { value: "music_separated", label: "Giữ nhạc nền (tách bằng Demucs)" },
  { value: "ducking", label: "Giảm âm nền (ducking)" },
];

export default function NewProjectPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [sourceLanguage, setSourceLanguage] = useState("en");
  const [audioMode, setAudioMode] = useState("ducking");
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const project = await createProject({
        title,
        source_language: sourceLanguage,
        target_language: "vi",
        audio_mode: audioMode,
      });

      if (file) {
        await uploadVideo(project.id, file);
      } else if (url) {
        await importVideoFromUrl(project.id, url);
      } else {
        throw new Error("Vui lòng chọn file hoặc dán link");
      }

      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Có lỗi xảy ra");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto max-w-xl p-8">
      <h1 className="mb-6 text-2xl font-semibold">Tạo dự án mới</h1>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium">Tên dự án</label>
          <input
            className="mt-1 w-full rounded border p-2"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>

        <div>
          <label className="block text-sm font-medium">Ngôn ngữ nguồn</label>
          <select
            className="mt-1 w-full rounded border p-2"
            value={sourceLanguage}
            onChange={(e) => setSourceLanguage(e.target.value)}
          >
            {SOURCE_LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>{l.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium">Chế độ âm thanh</label>
          <select
            className="mt-1 w-full rounded border p-2"
            value={audioMode}
            onChange={(e) => setAudioMode(e.target.value)}
          >
            {AUDIO_MODES.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium">Tải file video lên</label>
          <input
            type="file"
            accept="video/*"
            className="mt-1 w-full"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <div className="text-center text-sm text-gray-400">— hoặc —</div>

        <div>
          <label className="block text-sm font-medium">Dán link YouTube/TikTok</label>
          <input
            type="url"
            className="mt-1 w-full rounded border p-2"
            placeholder="https://..."
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded bg-blue-600 py-2 text-white disabled:opacity-50"
        >
          {submitting ? "Đang tạo..." : "Tạo dự án"}
        </button>
      </form>
    </main>
  );
}
```

- [ ] **Step 7: Commit**

```bash
git add frontend/app/dashboard/ frontend/app/projects/new/ frontend/lib/types.ts frontend/lib/api.ts frontend/lib/api.test.ts
git commit -m "feat(frontend): add Dashboard and New Project pages"
```

---

## Definition of Done for Phase 2

- [ ] `cd backend && pytest` passes (all Phase 1 + Phase 2 tests).
- [ ] `cd frontend && npm test` passes.
- [ ] Manually: create a project via `/projects/new`, upload a short real video, confirm it appears on `/dashboard` and a row exists in `videos` (check via Supabase table editor or `psql`).
- [ ] Manually: import a short YouTube video by URL and confirm the same.
- [ ] Report back to the user with what was built, test output, and any deviations before starting Phase 3.
