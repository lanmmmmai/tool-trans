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
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


client = TestClient(app)


def create_project():
    resp = client.post(
        "/api/projects",
        json={
            "title": "Edit test",
            "source_language": "en",
            "target_language": "vi",
            "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_patch_transcript_segment_sets_edited_text_without_touching_original():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Helo wrold",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        seg_id = seg.id

    resp = client.patch(
        f"/api/projects/{project_id}/transcript/{seg_id}",
        json={"source_text_edited": "Hello world"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source_text_edited"] == "Hello world"
    assert body["source_text"] == "Helo wrold"


def test_patch_transcript_segment_404_for_wrong_project():
    project_id = create_project()
    resp = client.patch(
        f"/api/projects/{project_id}/transcript/does-not-exist",
        json={"source_text_edited": "x"},
    )
    assert resp.status_code == 404
