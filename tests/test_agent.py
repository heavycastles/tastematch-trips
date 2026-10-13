import httpx

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
            {"entity_id": "D1", "name": "Paris", "query": {"affinity": 0.8}, "tags": [{"name": "nightlife"}]}]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: client.get(url, **kw))
    monkeypatch.setenv("QLOO_API_KEY", "k")
    qloo._cached_get.cache_clear()
    assert qloo.search("Daft Punk", "urn:entity:artist")[0]["id"] == "E1"
    ins = qloo.insights("urn:entity:destination", ["E1"], 5)
    assert ins[0]["name"] == "Paris" and ins[0]["affinity"] == 0.8
    assert str(seen[0].url).startswith("https://hackathon.api.qloo.com/search")
    assert "filter.type=urn%3Aentity%3Adestination" in str(seen[1].url)
    assert "signal.interests.entities=E1" in str(seen[1].url)


def test_live_error_raises(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, **kw: httpx.Response(401, text="No API key"))
    monkeypatch.setenv("QLOO_API_KEY", "bad")
    qloo._cached_get.cache_clear()
    try:
        qloo.search("x")
        raise AssertionError
    except qloo.QlooError as e:
        assert "401" in str(e)
