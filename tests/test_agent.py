import httpx
import pytest

from app import qloo
from app.agent import fairness, plan
from app.main import SAMPLE


def test_plan_mock_is_fair():
    r = plan(SAMPLE["travelers"], days=2)
    assert r["source"] == "mock" and r["destination"]
    assert set(r["fair_share"]) == {"Aziz", "Malika", "Rustam"}
    assert all(v >= 1 for v in r["fair_share"].values())
    assert len({x["place"] for x in r["itinerary"]}) == len(r["itinerary"])
    tools = [s["tool"] for s in r["trace"]]
    assert tools.count("resolve_entity") == 6 and "local_places" in tools
    assert r["ranking"][0]["group_fit"] >= r["ranking"][-1]["group_fit"]


def test_fixed_destination_and_unresolved():
    t = [{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}, {"name": "zzqx", "type": "movie"}]}]
    r = plan(t, days=1, destination="Berlin")
    assert r["destination"] == "Berlin" and r["unresolved"] == ["A: zzqx"]


def test_nothing_resolved_asks():
    r = plan([{"label": "A", "likes": [{"name": "qqqq"}]}])
    assert r["error"] == "none_resolved" and "ask" in r


def test_fairness_penalises_leaving_someone_out():
    per = {"a": {"X": 0.9, "Y": 0.6}, "b": {"X": 0.0, "Y": 0.6}}
    rank = fairness(per, [])
    assert rank[0]["name"] == "Y" and rank[1]["least_happy"] == "b"


def test_live_client_uses_hackathon_contract(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        assert req.method == "GET" and req.headers["x-api-key"] == "k"
        if req.url.path == "/search":
            return httpx.Response(200, json={"results": [{"entity_id": "E1", "name": "Daft Punk"}]})
        return httpx.Response(200, json={"results": {"entities": [
            {"entity_id": "D1", "name": "Paris", "query": {"affinity": 0.8},
             "properties": {"geocode": {"name": "Paris", "admin1_region": "Île-de-France", "country_code": "FR"}},
             "tags": [{"name": "nightlife"}]}]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: client.get(url, **kw))
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    assert qloo.search("Daft Punk", "urn:entity:artist")[0]["id"] == "E1"
    ins = qloo.insights("urn:entity:destination", ["E1"], 5)
    assert ins[0]["name"] == "Paris, Île-de-France" and ins[0]["affinity"] == 0.8
    assert ins[0]["location_query"] == "Paris, Île-de-France"
    assert str(seen[0].url).startswith("https://hackathon.api.qloo.com/search")
    assert "filter.type=urn%3Aentity%3Adestination" in str(seen[1].url)
    assert "signal.interests.entities=E1" in str(seen[1].url)


def test_live_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(401, text="No API key"))
    monkeypatch.setenv("QLOO_API_KEY", "bad")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    try:
        qloo.search("x")
        raise AssertionError
    except qloo.QlooError as e:
        assert "401" in str(e)


def test_parse_entity_shapes_offline():
    """Recorded-shape fixtures (no API key): affinity, geocode label, place address."""
    dest = qloo._parse_entity({
        "entity_id": "D1",
        "name": "Shinjuku",
        "query": {"affinity": 0.87},
        "popularity": 0.9,
        "properties": {"geocode": {"name": "Tokyo", "admin1_region": "Tokyo", "country_code": "JP"}},
        "tags": [{"name": "Great Nightlife"}, "urban"],
    }, as_destination=True)
    assert dest["id"] == "D1"
    # admin1_region "Tokyo" is not in "Shinjuku" -> "Shinjuku, Tokyo"
    assert dest["name"] == "Shinjuku, Tokyo"
    assert dest["location_query"] == "Shinjuku, Tokyo"
    assert dest["affinity"] == 0.87
    assert "Great Nightlife" in dest["tags"]

    place = qloo._parse_entity({
        "entity_id": "P1",
        "name": "Listening Bar",
        "query": {"affinity": 0.7},
        "properties": {"address": "1-2-3 Shibuya", "description": "Vinyl and cocktails."},
        "tags": [{"name": "Nightlife"}],
    })
    assert place["address"] == "1-2-3 Shibuya"
    assert place["affinity"] == 0.7
    assert place["location_query"] is None


def test_rate_limit_retries(monkeypatch):
    calls = {"n": 0}

    def flaky(url, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, text='{"error_msg":"Rate limit exceeded"}')
        return httpx.Response(200, json={"results": [{"entity_id": "E1", "name": "X"}]})

    monkeypatch.setattr(httpx, "get", flaky)
    monkeypatch.setattr(qloo.time, "sleep", lambda s: None)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    assert qloo.search("X")[0]["id"] == "E1"
    assert calls["n"] == 3


def test_live_smoke_search_and_insights(monkeypatch):
    """Optional live smoke: skipped unless .env (or env) provides QLOO_API_KEY."""
    import os
    # Temporarily undo offline guards so load_dotenv can pick up the key.
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    monkeypatch.delenv("QLOO_API_KEY", raising=False)
    qloo._ENV_LOADED = False
    qloo.load_dotenv()
    if not os.getenv("QLOO_API_KEY"):
        pytest.skip("QLOO_API_KEY not set")
    qloo._cached_get.cache_clear()
    hits = qloo.search("Spirited Away", "urn:entity:movie", 1)
    assert hits and hits[0]["id"]
    dests = qloo.insights("urn:entity:destination", [hits[0]["id"]], 3, popularity_min=0.5)
    assert dests and dests[0]["affinity"] > 0


def test_filter_entities_mock():
    hits = qloo.search("Daft Punk", "urn:entity:artist")
    all_dest = qloo.insights("urn:entity:destination", [hits[0]["id"]], 8)
    only = qloo.insights("urn:entity:destination", [hits[0]["id"]], 8,
                         filter_entities=[all_dest[0]["id"]])
    assert len(only) == 1 and only[0]["id"] == all_dest[0]["id"]


def test_parse_entity_image_and_coords():
    """Live place shape: properties.images[] + location{lat,lon}; only https image URLs are kept."""
    place = qloo._parse_entity({
        "entity_id": "P2", "name": "Playa", "query": {"affinity": 0.8},
        "location": {"lat": 20.87, "lon": -105.44, "geohash": "9etn8"},
        "properties": {"images": [{"url": "https://images.qloo.com/i/p2.jpg", "type": "urn:image:place:unknown"}]},
    })
    assert place["image"] == "https://images.qloo.com/i/p2.jpg"
    assert (place["lat"], place["lon"]) == (20.87, -105.44)
    artist = qloo._parse_entity({"entity_id": "A1", "name": "Band",
                                 "properties": {"image": {"url": "https://images.qloo.com/i/a1.jpg"}}})
    assert artist["image"] == "https://images.qloo.com/i/a1.jpg"
    bare = qloo._parse_entity({"entity_id": "X", "name": "X", "location": {"lat": "bad"},
                               "properties": {"image": {"url": "javascript:alert(1)"}}})
    assert bare["image"] is None and bare["lat"] is None and bare["lon"] is None


def test_plan_reports_stats_and_matched_detail():
    r = plan(SAMPLE["travelers"], days=2)
    assert r["stats"]["qloo_calls"] == len(r["trace"]) > 0
    assert r["stats"]["elapsed_ms"] >= 0
    aziz = next(t for t in r["travelers"] if t["label"] == "Aziz")
    assert [m["name"] for m in aziz["matched_detail"]] == aziz["matched"]
    assert {m["type"] for m in aziz["matched_detail"]} <= {"movie", "brand"}
    for item in r["itinerary"]:
        assert {"image", "description", "lat", "lon"} <= set(item)
