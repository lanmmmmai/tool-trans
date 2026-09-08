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
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


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
