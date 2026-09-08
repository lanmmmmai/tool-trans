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
    app.dependency_overrides[get_session] = override_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


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
