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


def test_plan_button_waits_for_a_pending_sample_load():
    # A quick "Load sample" → "Plan our trip" used to plan an empty group while /api/sample was in flight.
    html = c.get("/").text
    assert "if(sampleLoading)await sampleLoading;" in html
    assert "Could not load the sample group" in html


def test_version_reports_short_commit(monkeypatch):
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA", raising=False)
    body = c.get("/version").json()
    assert body["commit"] == "unknown" and body["qloo"] == "mock" and body["version"]
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "0123456789abcdef0123456789abcdef01234567")
    assert c.get("/version").json()["commit"] == "0123456"
    monkeypatch.setenv("GIT_COMMIT", "abc1234")  # set at deploy time, wins over Vercel's value
    assert c.get("/version").json()["commit"] == "abc1234"
    monkeypatch.setenv("GIT_COMMIT", "<script>")  # never echo arbitrary text
    monkeypatch.delenv("VERCEL_GIT_COMMIT_SHA")
    assert c.get("/version").json()["commit"] == "unknown"
    assert c.head("/version").status_code == 200
