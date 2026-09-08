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
