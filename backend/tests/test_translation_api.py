from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.session import get_session
from app.main import app
from app.models.transcript_segment import TranscriptSegment
from app.models.translation_segment import TranslationSegment

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
            "title": "Translate test", "source_language": "en",
            "target_language": "vi", "audio_mode": "ducking",
        },
    )
    return resp.json()["id"]


def test_start_translate_sets_engine_and_enqueues_task():
    project_id = create_project()

    with patch("app.api.translation.translate_task") as mock_task:
        resp = client.post(
            f"/api/projects/{project_id}/translate", json={"engine": "openai"}
        )

    assert resp.status_code == 202, resp.text
    assert resp.json()["job_type"] == "translate"
    mock_task.delay.assert_called_once_with(project_id=project_id, engine_name="openai")

    project_resp = client.get(f"/api/projects/{project_id}")
    assert project_resp.json()["translate_engine"] == "openai"


def test_get_translation_joins_transcript_and_translation():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        session.add(TranslationSegment(segment_id=seg.id, translated_text="Xin chào"))
        session.commit()

    resp = client.get(f"/api/projects/{project_id}/translation")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["translated_text"] == "Xin chào"
    assert body[0]["source_text"] == "Hello"


def test_patch_translation_segment():
    project_id = create_project()
    with Session(engine) as session:
        seg = TranscriptSegment(
            project_id=project_id, seq_index=0, start_time=0, end_time=1,
            speaker_label="speaker_1", source_text="Hello",
        )
        session.add(seg)
        session.commit()
        session.refresh(seg)
        translation = TranslationSegment(segment_id=seg.id, translated_text="Xin chào")
        session.add(translation)
        session.commit()
        session.refresh(translation)
        translation_id = translation.id

    resp = client.patch(
        f"/api/projects/{project_id}/translation/{translation_id}",
        json={"translated_text_edited": "Chào bạn"},
    )
    assert resp.status_code == 200
    assert resp.json()["translated_text_edited"] == "Chào bạn"
