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
    group = [{"name": "X", "affinity": 0.45}, {"name": "Y", "affinity": 0.6}]
    rank = fairness(per, group)
    assert rank[0]["name"] == "Y" and rank[1]["least_happy"] == "b"


def test_fairness_excludes_missing_destination_scores_but_keeps_real_zero():
    per = {"A": {"Rome": 0.8, "Paris": 0.7}, "B": {"Paris": 0.0}}
    group = [{"name": "Rome", "affinity": 0.9}, {"name": "Paris", "affinity": 0.8}]
    rank = fairness(per, group)
    assert [city["name"] for city in rank] == ["Paris"]
    assert rank[0]["per_traveler"]["B"] == 0.0 and rank[0]["group_fit"] == 30.0


def test_fairness_never_invents_a_missing_group_affinity():
    per = {"A": {"Rome": 0.9}, "B": {"Rome": 0.1}}
    assert fairness(per, []) == []
    ranked = fairness(per, [{"name": "Rome", "affinity": 0.0}])
    assert ranked[0]["group_fit"] == 24.0


def test_fairness_keeps_distinct_destination_ids_with_the_same_display_name():
    group = [{"id": "D1", "name": "Springfield", "affinity": 0.8},
             {"id": "D2", "name": "Springfield", "affinity": 0.7}]
    per = {"A": {"D1": 0.9, "D2": 0.1}, "B": {"D1": 0.2, "D2": 0.8}}
    ranked = {city["id"]: city for city in fairness(per, group)}
    assert set(ranked) == {"D1", "D2"}
    assert ranked["D1"]["per_traveler"] == {"A": 0.9, "B": 0.2}
    assert ranked["D2"]["per_traveler"] == {"A": 0.1, "B": 0.8}


def test_fairness_breaks_equal_same_name_ties_by_destination_id():
    group = [{"id": "D2", "name": "Springfield", "affinity": 0.8},
             {"id": "D1", "name": "Springfield", "affinity": 0.8}]
    per = {"A": {"D1": 0.8, "D2": 0.8}}
    assert [city["id"] for city in fairness(per, group)] == ["D1", "D2"]


def test_chosen_city_without_group_affinity_is_unscored(monkeypatch):
    def search(name, etype=None, take=1):
        eid = "D1" if etype == "urn:entity:destination" else "E:" + name
        return [{"id": eid, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype == "urn:entity:destination" and len(ids) == 1:
            return [{"id": "D1", "name": "Rome", "affinity": 0.8, "location_query": "Rome"}]
        return []

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)
    travelers = [{"label": "A", "likes": [{"name": "Alpha"}]},
                 {"label": "B", "likes": [{"name": "Beta"}]}]
    result = plan(travelers, days=1, destination="Rome")
    assert result["chosen"]["scored"] is False and result["chosen"]["group_fit"] is None
    assert "complete" in result["narrative"].lower()


def test_destination_scores_match_entity_id_when_display_names_differ(monkeypatch):
    def search(name, etype=None, take=1):
        return [{"id": "E:" + name, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype != "urn:entity:destination":
            return []
        name = "Paris" if ids == ["E:Beta"] else "Paris, Ile-de-France"
        value = 0.7 if ids == ["E:Beta"] else 0.8
        return [{"id": "D1", "name": name, "affinity": value, "location_query": name}]

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)
    travelers = [{"label": "A", "likes": [{"name": "Alpha"}]},
                 {"label": "B", "likes": [{"name": "Beta"}]}]
    result = plan(travelers, days=1)
    assert result["ranking"][0]["name"] == "Paris, Ile-de-France"
    assert result["ranking"][0]["per_traveler"] == {"A": 0.8, "B": 0.7}


def test_distinct_same_named_destinations_keep_their_scores_and_locations(monkeypatch):
    locations = []

    def search(name, etype=None, take=1):
        return [{"id": "E:" + name, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype != "urn:entity:destination":
            locations.append(kwargs.get("location"))
            return []
        values = {"D1": 0.9, "D2": 0.1} if ids == ["E:Alpha"] else (
            {"D1": 0.2, "D2": 0.8} if ids == ["E:Beta"] else {"D1": 0.8, "D2": 0.7})
        return [{"id": "D1", "name": "Springfield", "affinity": values["D1"],
                 "location_query": "Springfield, Illinois", "lat": 39.78, "lon": -89.65},
                {"id": "D2", "name": "Springfield", "affinity": values["D2"],
                 "location_query": "Springfield, Oregon", "lat": 44.05, "lon": -123.02}]

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)
    travelers = [{"label": "A", "likes": [{"name": "Alpha"}]},
                 {"label": "B", "likes": [{"name": "Beta"}]}]
    result = plan(travelers, days=1)
    assert [city["id"] for city in result["ranking"]] == ["D1", "D2"]
    assert result["ranking"][0]["per_traveler"] == {"A": 0.9, "B": 0.2}
    assert locations == ["Springfield, Illinois", "Springfield, Illinois"]


def test_chosen_city_uses_resolved_location_when_name_is_ambiguous(monkeypatch):
    locations = []

    def search(name, etype=None, take=1):
        eid = "D1" if etype == "urn:entity:destination" else "E:" + name
        return [{"id": eid, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype == "urn:entity:destination":
            return [{"id": "D1", "name": "Paris, Texas", "affinity": 0.8,
                     "location_query": "Paris, Texas"}]
        locations.append(kwargs.get("location"))
        return []

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)
    result = plan([{"label": "A", "likes": [{"name": "Alpha"}]}], days=1, destination="Paris")
    assert result["chosen"]["id"] == "D1"
    assert result["destination"] == "Paris, Texas"
    assert locations == ["Paris, Texas"]


@pytest.mark.parametrize("missing_id", [None, "", "  ", 42])
def test_chosen_destination_without_id_does_not_plan_a_different_city(monkeypatch, missing_id):
    def search(name, etype=None, take=1):
        eid = missing_id if etype == "urn:entity:destination" else "E:" + name
        return [{"id": eid, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype == "urn:entity:destination":
            return [{"id": "D2", "name": "Rome", "affinity": 0.8, "location_query": "Rome, Italy"}]
        return []

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)
    result = plan([{"label": "A", "likes": [{"name": "Alpha"}]}], days=1, destination="Paris")
    assert result["error"] == "destination_not_found"
    assert "identify" in result["ask"].lower()


@pytest.mark.parametrize("missing_id", [None, "", "  ", 42])
def test_favourite_without_valid_id_is_unresolved(monkeypatch, missing_id):
    monkeypatch.setattr(qloo, "search", lambda name, etype=None, take=1:
                        [{"id": missing_id, "name": name, "type": etype}])

    def no_insights(*args, **kwargs):
        pytest.fail("A favourite without an entity ID must not be sent to Qloo insights")

    monkeypatch.setattr(qloo, "insights", no_insights)
    result = plan([{"label": "A", "likes": [{"name": "Alpha"}]}], days=1)
    assert result["error"] == "none_resolved"
    assert result["unresolved"] == ["A: Alpha"]


def _incomplete_destination_scores(monkeypatch):
    def search(name, etype=None, take=1):
        eid = "D1" if etype == "urn:entity:destination" else "E:" + name
        return [{"id": eid, "name": name, "type": etype}]

    def insights(ftype, ids, *args, **kwargs):
        if ftype == "urn:entity:destination" and ids != ["E:Beta"]:
            return [{"id": "D1", "name": "Rome", "affinity": 0.8, "location_query": "Rome"}]
        return []

    monkeypatch.setattr(qloo, "search", search)
    monkeypatch.setattr(qloo, "insights", insights)


def test_plan_does_not_choose_a_city_missing_one_travelers_score(monkeypatch):
    _incomplete_destination_scores(monkeypatch)
    travelers = [{"label": "A", "likes": [{"name": "Alpha"}]},
                 {"label": "B", "likes": [{"name": "Beta"}]}]
    result = plan(travelers, days=1)
    assert result["error"] == "no_destinations"
    assert "every traveler" in result["ask"]


def test_partially_scored_chosen_city_is_shown_as_unscored(monkeypatch):
    _incomplete_destination_scores(monkeypatch)
    travelers = [{"label": "A", "likes": [{"name": "Alpha"}]},
                 {"label": "B", "likes": [{"name": "Beta"}]}]
    result = plan(travelers, days=1, destination="Rome")
    assert result["chosen"]["scored"] is False
    assert result["chosen"]["group_fit"] is None
    assert all(value is None for value in result["chosen"]["per_traveler"].values())
    assert not any(decision["step"] == "compensate" for decision in result["decisions"])


def test_insights_skips_entities_without_an_affinity_but_keeps_zero(monkeypatch):
    payload = {"results": {"entities": [{"entity_id": "missing", "name": "Missing"},
                                         {"entity_id": "popular", "name": "Popular", "popularity": 0.99},
                                         {"entity_id": "ranked", "name": "Ranked", "query": {"rank": 1}},
                                         {"entity_id": "zero", "name": "Zero", "query": {"affinity": 0.0}}]}}
    monkeypatch.setattr(qloo, "live", lambda: True)
    monkeypatch.setattr(qloo, "_get", lambda path, params: payload)
    result = qloo.insights("urn:entity:destination", ["taste"])
    assert [entity["id"] for entity in result] == ["zero"]
    assert result[0]["affinity"] == 0.0


def test_insights_rejects_invalid_affinities_and_accepts_a_valid_fallback(monkeypatch):
    entities = [{"entity_id": name, "name": name, "query": {"affinity": value}}
                for name, value in (("nan", "NaN"), ("inf", "Infinity"), ("negative", -0.1),
                                    ("large", 1.1), ("bool", True), ("zero", 0.0), ("one", 1.0))]
    entities.append({"entity_id": "fallback", "name": "Fallback", "query": {"affinity": "NaN", "score": 0.75}})
    monkeypatch.setattr(qloo, "live", lambda: True)
    monkeypatch.setattr(qloo, "_get", lambda path, params: {"results": {"entities": entities}})
    result = qloo.insights("urn:entity:destination", ["taste"])
    assert [(e["id"], e["affinity"]) for e in result] == [("zero", 0.0), ("one", 1.0), ("fallback", 0.75)]


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


def test_stats_count_http_attempts_and_cache_hits_separately_from_steps(monkeypatch):
    seen = []

    def handler(url, **kw):
        seen.append(url)
        params = dict(kw.get("params") or [])
        if len(seen) == 1:
            return httpx.Response(429, text="retry")
        if url.endswith("/search"):
            hit = ({"entity_id": "wrong", "name": "Unrelated"} if "types" in params else
                   {"entity_id": "E1", "name": "Alpha", "types": ["urn:entity:movie"]})
            return httpx.Response(200, json={"results": [hit]})
        entities = ([{"entity_id": "D1", "name": "Rome", "query": {"affinity": 0.7}}]
                    if params.get("filter.type") == "urn:entity:destination" else [])
        return httpx.Response(200, json={"results": {"entities": entities}})

    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setattr(qloo.time, "sleep", lambda _: None)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    travelers = [{"label": "A", "likes": [{"name": "Alpha", "type": "movie"}]}]
    try:
        first = plan(travelers, days=1)
        again = plan(travelers, days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert first["stats"]["tool_steps"] == len(first["trace"]) == 4
    assert first["stats"]["qloo_calls"] == len(seen) == 6
    assert first["stats"]["cached"] == 0
    assert again["stats"]["qloo_calls"] == 0 and again["stats"]["cached"] == 5


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
    assert r["stats"]["tool_steps"] == len(r["trace"]) > 0
    assert r["stats"]["qloo_calls"] == 0
    assert r["stats"]["elapsed_ms"] >= 0
    aziz = next(t for t in r["travelers"] if t["label"] == "Aziz")
    assert [m["name"] for m in aziz["matched_detail"]] == aziz["matched"]
    assert {m["type"] for m in aziz["matched_detail"]} <= {"movie", "brand"}
    for item in r["itinerary"]:
        assert {"image", "description", "lat", "lon"} <= set(item)


def test_base_url_read_from_env_at_call_time(monkeypatch):
    seen = []

    def handler(req: httpx.Request):
        seen.append(str(req.url))
        return httpx.Response(200, json={"results": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(httpx, "get", lambda url, **kw: client.get(url, **kw))
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.setenv("QLOO_BASE_URL", "https://qloo.example.test/")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    qloo.search("Daft Punk", "urn:entity:artist")
    assert seen and seen[0].startswith("https://qloo.example.test/search")


def test_video_game_uses_qloo_videogame_urn(monkeypatch):
    from app import agent

    seen = []
    monkeypatch.setattr(agent.qloo, "search", lambda q, t, n: seen.append(t) or [{"id": "x", "name": q, "type": t}])
    agent.resolve([{"label": "Max", "likes": [{"name": "The Witcher 3", "type": "video_game"},
                                              {"name": "Dune", "type": "book"}]}], agent.Trace())
    assert seen == ["urn:entity:videogame", "urn:entity:book"]
