"""Fourth judge audit: a slow or rate-limiting Qloo must get a clear answer before the host's 60 s limit, duplicate
favourites count once, cache stats are per request, and emoji/Cyrillic nicknames render whole in the UI."""
import httpx
from fastapi.testclient import TestClient

from app import qloo
from app.agent import plan
from app.main import app
from tests.test_judge_audit3 import _graph, _live

c = TestClient(app)
SA = [{"entity_id": "SA", "name": "Spirited Away", "types": ["urn:entity:movie"]}]


def test_whole_plan_shares_one_time_budget(monkeypatch):
    """Each 429 alone stays inside its own retry budget, but together they would outlast Vercel's 60 s."""
    clock = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        clock[0] += s

    def handler(url, **kw):
        clock[0] += 0.5
        return httpx.Response(429, headers={"retry-after": "5"}, text="slow down")
    _live(monkeypatch, handler)
    monkeypatch.setattr(qloo.time, "sleep", sleep)
    monkeypatch.setattr(qloo.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("QLOO_REQUEST_BUDGET", "8")
    try:
        r = c.post("/api/plan", json={"travelers": [{"label": "A", "likes": [{"name": "x"}]}]})
    finally:
        qloo._cached_get.cache_clear()
    assert r.status_code == 503 and r.json()["error"] == "rate_limited"
    assert clock[0] <= 9  # stopped at the plan's 8 s budget, not after a 12 s back-off


def test_budget_used_up_reads_as_slow_qloo(monkeypatch):
    clock = [0.0]

    def handler(url, **kw):
        clock[0] += 30  # every Qloo answer takes 30 s
        return _graph(lambda p: SA)(url, **kw)
    _live(monkeypatch, handler)
    monkeypatch.setattr(qloo.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("QLOO_REQUEST_BUDGET", "45")
    try:
        r = c.post("/api/plan", json={"travelers": [{"label": "A", "likes": [{"name": "x"}]},
                                                    {"label": "B", "likes": [{"name": "y"}]}]})
    finally:
        qloo._cached_get.cache_clear()
    assert r.status_code == 504 and r.json()["error"] == "qloo_timeout"
    assert "too long" in r.json()["ask"]


def test_per_call_timeout_never_exceeds_what_is_left(monkeypatch):
    clock, seen = [0.0], []

    def handler(url, **kw):
        seen.append(kw["timeout"])
        clock[0] += 10
        return _graph(lambda p: SA)(url, **kw)
    _live(monkeypatch, handler)
    monkeypatch.setattr(qloo.time, "monotonic", lambda: clock[0])
    monkeypatch.setenv("QLOO_REQUEST_BUDGET", "25")
    try:
        c.post("/api/plan", json={"travelers": [{"label": "A", "likes": [{"name": "x"}]}]})
    finally:
        qloo._cached_get.cache_clear()
    assert seen[0] == 20 and seen[1] == 15 and all(t <= 20 for t in seen)


def test_duplicate_favourites_are_one_signal(monkeypatch):
    calls = []
    _live(monkeypatch, _graph(lambda p: SA, calls=calls))
    try:
        r = plan([{"label": "A", "likes": [{"name": "Spirited Away", "type": "movie"},
                                           {"name": "spirited away", "type": "movie"}]},
                  {"label": "B", "likes": [{"name": "Spirited Away", "type": "movie"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert r["travelers"][0]["matched"] == ["Spirited Away"]
    assert [s.get("duplicate") for s in r["trace"] if s["tool"] == "resolve_entity"] == [None, True, None]
    sig = [p["signal.interests.entities"] for k, p in calls if k == "insights" and "filter.entities" not in p]
    assert sig[0] == "SA"  # group query: shared favourite sent once, not "SA,SA,SA"
    assert "counted once" in c.get("/").text


def test_cached_count_is_per_request(monkeypatch):
    _live(monkeypatch, _graph(lambda p: SA))
    body = [{"label": "A", "likes": [{"name": "Spirited Away", "type": "movie"}]}]
    try:
        first = plan(body, days=1)["stats"]
        qloo._cached_get(  # another visitor's request in between must not shrink this plan's "cached" count
            "/search", (("query", "other"),), "k")
        again = plan(body, days=1)["stats"]
    finally:
        qloo._cached_get.cache_clear()
    assert first["cached"] == 0 and again["cached"] == again["qloo_calls"]


def test_ui_initials_and_enter_key():
    html = c.get("/").text
    assert "Intl.Segmenter" in html and "[...s][0]" in html  # '🐻 Bear' -> 🐻, not half a surrogate pair
    assert "charAt(0)" not in html
    assert "e.key==='Enter'" in html


def test_too_long_favourite_hint_names_the_limit():
    r = c.post("/api/plan", json={"travelers": [{"label": "A", "likes": [{"name": "x" * 101}]}]})
    assert r.status_code == 422 and "1–100 characters" in r.json()["ask"]
