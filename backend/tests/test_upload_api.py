import io
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
SQLModel.metadata.create_all(engine)


def override_get_session():
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def _use_this_modules_session_override():
    # See test_transcript_api.py for why this is needed: the shared `app`
    # singleton means the last-imported test file's module-level override
    # otherwise wins for every file's tests.
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


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
