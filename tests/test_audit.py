"""Judge-facing robustness: own groups, chosen destinations, friendly errors."""
import httpx
from fastapi.testclient import TestClient

from app import qloo
from app.agent import plan
from app.main import SAMPLE, app

c = TestClient(app)


def _live(monkeypatch, handler):
    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setattr(qloo.time, "sleep", lambda s: None)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()


def test_chosen_destination_is_scored_not_mislabelled():
    t = [{"label": "Lena", "likes": [{"name": "Daft Punk", "type": "artist"}]},
         {"label": "Max", "likes": [{"name": "Patagonia", "type": "brand"}]}]
    r = plan(t, days=1, destination="Reykjavik")
    assert r["mode"] == "chosen" and r["destination"] == "Reykjavik"
    ch = r["chosen"]
    assert ch and ch["name"] == "Reykjavik" and set(ch["per_traveler"]) == {"Lena", "Max"}
    assert "best shared match" not in r["narrative"].split(".")[0]
    assert "Reykjavik" in r["narrative"] and r["ranking"][0]["name"] in r["narrative"]
    assert any(s["tool"] == "resolve_destination" for s in r["trace"])


def test_best_match_mode_by_default():
    r = plan(SAMPLE["travelers"], days=1)
    assert r["mode"] == "best_match" and r["chosen"] is None


def test_unknown_destination_asks_instead_of_502():
    t = [{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}]}]
    r = plan(t, days=1, destination="Atlantisxyz")
    assert r["error"] == "destination_not_found" and "Atlantisxyz" in r["ask"]


def test_duplicate_nicknames_rejected_with_friendly_message():
    body = {"days": 1, "travelers": [{"label": "Sam", "likes": [{"name": "Daft Punk"}]},
                                     {"label": "sam ", "likes": [{"name": "Patagonia"}]}]}
    r = c.post("/api/plan", json=body)
    assert r.status_code == 422 and "different nickname" in r.json()["ask"]


def test_validation_errors_are_human_readable():
    r = c.post("/api/plan", json={"travelers": []})
    assert r.status_code == 422 and r.json()["error"] == "invalid_input"
    assert "traveler" in r.json()["ask"].lower() and "{" not in r.json()["ask"]
    r = c.post("/api/plan", json={"travelers": [{"label": "A", "likes": [{"name": "   "}]}]})
    assert r.status_code == 422


def test_rate_limit_becomes_503_with_retry_hint(monkeypatch):
    _live(monkeypatch, lambda url, **kw: httpx.Response(429, text="Rate limit exceeded"))
    r = c.post("/api/plan", json=SAMPLE)
    assert r.status_code == 503 and r.json()["error"] == "rate_limited" and "try again" in r.json()["ask"].lower()


def test_timeout_becomes_504_not_500(monkeypatch):
    def boom(url, **kw):
        raise httpx.ReadTimeout("slow")

    _live(monkeypatch, boom)
    r = c.post("/api/plan", json=SAMPLE)
    assert r.status_code == 504 and r.json()["error"] == "qloo_timeout"


def test_upstream_error_is_502_without_raw_payload(monkeypatch):
    _live(monkeypatch, lambda url, **kw: httpx.Response(500, text='{"secret":"internal stack"}'))
    r = c.post("/api/plan", json=SAMPLE)
    assert r.status_code == 502 and "internal stack" not in r.json()["ask"]


def test_retry_budget_is_bounded(monkeypatch):
    slept = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(429, text="x"))
    monkeypatch.setattr(qloo.time, "sleep", slept.append)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    try:
        qloo.search("X")
        raise AssertionError
    except qloo.QlooError as e:
        assert e.kind == "rate_limited"
    assert sum(slept) <= 12


def test_unplaceable_location_falls_back_to_error(monkeypatch):
    def handler(url, **kw):
        params = dict(kw.get("params") or [])
        if url.endswith("/search"):
            return httpx.Response(200, json={"results": [{"entity_id": "E1", "name": params["query"]}]})
        if params.get("filter.type") == "urn:entity:place":
            return httpx.Response(400, json={"errors": [{"message": "filter.location.query is unable to resolve"}]})
        return httpx.Response(200, json={"results": {"entities": [
            {"entity_id": "E1", "name": "Nowhere", "query": {"affinity": 0.5}}]}})

    _live(monkeypatch, handler)
    t = [{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}]}]
    r = plan(t, days=1, destination="Nowhere")
    assert r["error"] == "destination_not_found"


def test_destination_labels_are_clean_for_city_states():
    def lab(name, region="", cc=""):
        return qloo._destination_label({"name": name, "properties": {"geocode": {
            "admin1_region": region, "country_code": cc}}})
    assert lab("Hong Kong", "Central and Western", "HK") == "Hong Kong"
    assert lab("Macao", "Macau", "MO") == "Macao"
    assert lab("Singapore", "", "SG") == "Singapore"
    assert lab("Santa Fe", "New Mexico", "US") == "Santa Fe, New Mexico"
    assert lab("Portland", "Maine", "US") == "Portland, Maine"


def test_ui_handles_chosen_mode_errors_and_destination_trace():
    html = c.get("/").text
    for needle in ("Your destination", "showErr", "resolve_destination", "different nickname", "minmax(0,1fr)"):
        assert needle in html
