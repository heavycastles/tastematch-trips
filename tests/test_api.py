from fastapi.testclient import TestClient

from app.main import SAMPLE, app

c = TestClient(app)


def test_health_index_sample():
    assert c.get("/healthz").json()["qloo"] == "mock"
    assert "TasteMatch" in c.get("/").text
    assert c.get("/api/sample").json()["travelers"]


def test_plan_endpoint():
    r = c.post("/api/plan", json=SAMPLE)
    assert r.status_code == 200 and r.json()["itinerary"]


def test_validation():
    assert c.post("/api/plan", json={"travelers": []}).status_code == 422
    assert c.post("/api/plan", json={**SAMPLE, "days": 9}).status_code == 422


def test_index_does_not_depend_on_cwd(tmp_path, monkeypatch):
    # Serverless hosts may start the app from a different working directory.
    monkeypatch.chdir(tmp_path)
    r = c.get("/")
    assert r.status_code == 200 and "TasteMatch" in r.text
