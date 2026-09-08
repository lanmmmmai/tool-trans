from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_allows_cross_origin_requests_from_frontend_dev_origin():
    resp = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
