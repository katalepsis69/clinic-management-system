from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_root_serves_html():
    res = client.get("/")
    assert res.status_code == 200
    assert "Clinic Management System" in res.text


def test_api_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert "service" in data


def test_public_display_serves_html():
    res = client.get("/display")
    assert res.status_code == 200
    assert "NOW SERVING" in res.text or "Queue" in res.text


def test_static_files_served():
    res = client.get("/static/app.js")
    assert res.status_code == 200
