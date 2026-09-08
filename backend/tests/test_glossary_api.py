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


def test_create_and_list_glossary_terms():
    create_resp = client.post(
        "/api/glossary", json={"source_term": "Claude", "target_term": "Claude"}
    )
    assert create_resp.status_code == 201

    list_resp = client.get("/api/glossary")
    assert list_resp.status_code == 200
    terms = list_resp.json()
    assert any(t["source_term"] == "Claude" for t in terms)
