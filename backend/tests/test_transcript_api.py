from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.transcript_segment import TranscriptSegment

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
    # Every test file that overrides get_session shares the same `app`
    # singleton, so whichever file pytest imports LAST during collection
    # "wins" the module-level assignment for the whole run — reasserting
    # it here, per-test, makes each file's tests correct regardless of
    # import/collection order.
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


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
