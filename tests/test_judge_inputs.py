"""Second judge audit: inputs a judge actually types (odd casing, long text, big groups, short trips, cities
Qloo can't score) must give honest, polished results instead of 502s or misleading numbers."""
import re

import httpx
from fastapi.testclient import TestClient

from app import agent, qloo
from app.agent import build_itinerary, plan
from app.main import app

c = TestClient(app)


def _live(monkeypatch, handler):
    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setattr(qloo.time, "sleep", lambda s: None)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()


def _cat(c):
    return [{"id": f"urn:tag:category:place:{c}", "name": c}]


def _graph(dest_scores=True, bad_query=None):
    """Minimal live Qloo: two travelers, a 'Seoul' Qloo can't score, venues with categories."""
    venues = [("V1", "Museo", "museum", 0.9), ("V2", "Cafe", "cafe", 0.88), ("V3", "Bar", "bar", 0.87),
              ("V4", "Park", "park", 0.86), ("V5", "Bistro", "restaurant", 0.85), ("V6", "Pub", "pub", 0.84)]

    def handler(url, **kw):
        p = dict(kw.get("params") or [])
        if url.endswith("/search"):
            if bad_query and p["query"] == bad_query:
                return httpx.Response(400, json={"error": {"message": "query: query must be at most 100 characters"}})
            if p.get("types") == "urn:entity:destination":
                return httpx.Response(200, json={"results": [{"entity_id": "SEOUL", "name": "Seoul"}]})
            return httpx.Response(200, json={"results": [{"entity_id": "E-" + p["query"], "name": p["query"]}]})
        if p.get("filter.type") == "urn:entity:destination":
            ents = [{"entity_id": "D1", "name": "Lisbon", "query": {"affinity": 0.8}}]
            if dest_scores:
                ents.append({"entity_id": "SEOUL", "name": "Seoul", "query": {"affinity": 0.7}})
            return httpx.Response(200, json={"results": {"entities": ents}})
        ents = [{"entity_id": i, "name": n, "tags": _cat(k), "query": {"affinity": a}} for i, n, k, a in venues]
        if "filter.entities" in p:
            ids = p["filter.entities"].split(",")
            ents = [e for e in ents if e["entity_id"] in ids]
        return httpx.Response(200, json={"results": {"entities": ents}})
    return handler


T2 = [{"label": "A", "likes": [{"name": "x", "type": "movie"}]},
      {"label": "B", "likes": [{"name": "y", "type": "artist"}]}]


def test_overlong_favourite_gets_friendly_422_not_502():
    body = {"days": 1, "travelers": [{"label": "A", "likes": [{"name": "x" * 101}]}]}
    r = c.post("/api/plan", json=body)
    assert r.status_code == 422 and "100 characters" in r.json()["ask"]
    assert 'maxlength="100"' in c.get("/").text


def test_one_rejected_favourite_is_skipped_not_a_502(monkeypatch):
    _live(monkeypatch, _graph(bad_query="weird"))
    t = [{"label": "A", "likes": [{"name": "weird", "type": "movie"}, {"name": "x", "type": "movie"}]},
         T2[1]]
    try:
        r = plan(t, days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert "error" not in r and r["unresolved"] == ["A: weird"] and r["itinerary"]


def test_trace_shows_what_each_favourite_matched_in_qloo():
    r = plan([{"label": "A", "likes": [{"name": "daft punk", "type": "artist"}]}], days=1)
    step = next(s for s in r["trace"] if s["tool"] == "resolve_entity")
    assert step["matched"] == "daft punk"
    assert "s.matched" in c.get("/").text


def test_destination_is_shown_with_qloos_spelling():
    r = plan([{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}]}], days=1, destination="  lisbon ")
    assert r["destination"] == "Lisbon" and r["chosen"]["name"] == "Lisbon"


def test_city_qloo_cannot_score_is_not_shown_as_zero_fit(monkeypatch):
    _live(monkeypatch, _graph(dest_scores=False))
    try:
        r = plan(T2, days=1, destination="Seoul")
    finally:
        qloo._cached_get.cache_clear()
    ch = r["chosen"]
    assert ch["scored"] is False and r["itinerary"]
    assert not any(d["step"] == "compensate" for d in r["decisions"])  # no "A is least-matched (0%)"
    text = r["narrative"]
    assert "fit of 0.0" not in text and "(0%)" not in text and "doesn't score Seoul" in text
    html = c.get("/").text
    assert "scored===false" in html and "not scored" in html


def test_scored_city_is_marked_scored(monkeypatch):
    _live(monkeypatch, _graph())
    try:
        r = plan(T2, days=1, destination="Seoul")
    finally:
        qloo._cached_get.cache_clear()
    assert r["chosen"]["scored"] is True and r["chosen"]["group_fit"] > 0


def test_campuses_gyms_wedding_venues_and_tattoo_shops_are_not_stops():
    p = lambda *cats: {"name": "x", "categories": list(cats)}  # noqa: E731
    for cats in (["private_university", "university"], ["gym"], ["fitness_center"], ["wedding_venue"],
                 ["wedding_venue", "event_venue"], ["tattoo_shop"], ["school"],
                 ["emdr_psychotherapist", "family_counselor"], ["make_up_artist"], ["beauty_salon"],
                 ["subway_station"], ["entertainer"], ["film_production_company"], ["record_company"],
                 ["recording_studio"], ["restaurant", "event_planner"]):
        assert not agent.visitable(p(*cats)), cats
    # a campus that is also a sight (e.g. a historic college) stays
    assert agent.visitable(p("university", "tourist_attraction"))
    assert agent.visitable(p("stadium", "tourist_attraction"))
    assert agent.visitable(p("event_venue", "tourist_attraction", "observation_deck"))  # Top of the Rock
    assert agent.visitable(p("live_music_venue")) and agent.visitable(p("day_spa"))


def test_far_away_venues_are_dropped_from_a_city_trip():
    nyc = [{"id": f"N{i}", "name": f"N{i}", "categories": ["museum"], "affinity": 0.9, "lat": 40.75 + i / 100,
            "lon": -73.98} for i in range(6)]
    niagara = {"id": "F", "name": "Niagara Falls State Park", "categories": ["park"], "affinity": 0.95,
               "lat": 43.08, "lon": -79.07}
    pool = agent._stops([niagara] + nyc)
    assert "F" not in [p["id"] for p in pool] and pool.far == 1
    # venues without coordinates are kept
    assert agent._stops([{"id": "x", "name": "x", "categories": ["museum"], "affinity": 0.9}])


def _stop(n, cat, day, slot, who):
    return {"id": n, "place": n, "categories": [cat], "day": day, "slot": slot, "for": who, "affinity": 0.8}


def test_bars_never_land_in_the_morning_when_another_day_can_swap():
    it = [_stop("Bar1", "bar", 1, "morning", "A"), _stop("Bar2", "bar", 1, "afternoon", "B"),
          _stop("Bistro", "restaurant", 1, "evening", "A"),
          _stop("Museum", "museum", 2, "morning", "B"), _stop("Cafe", "cafe", 2, "afternoon", "A"),
          _stop("Park", "park", 2, "evening", "B")]
    out, moved = agent.arrange_trip(it)
    assert moved
    for x in out:
        if x["place"].startswith("Bar"):
            assert x["slot"] == "evening", x
    assert sorted(x["place"] for x in out) == sorted(x["place"] for x in it)
    assert sorted((x["day"], x["slot"]) for x in out) == sorted((x["day"], x["slot"]) for x in it)
    assert sorted(x["for"] for x in out) == sorted(x["for"] for x in it)


def test_more_nightlife_than_evenings_overflows_to_the_afternoon_not_the_morning():
    # live Hong Kong plan (4 travelers, 3 days): 4 clubs/bars + restaurants, only 3 evenings
    it = [_stop("Club1", "night_club", 1, "morning", "A"), _stop("Grill", "american_restaurant", 1, "afternoon", "B"),
          _stop("Club2", "night_club", 1, "evening", "C"), _stop("Bistro", "french_restaurant", 2, "morning", "A"),
          _stop("Canteen", "chinese_restaurant", 2, "afternoon", "C"), _stop("Bar1", "cocktail_bar", 2, "evening", "D"),
          _stop("Peak", "scenic_spot", 3, "morning", "D"), _stop("Tapas", "spanish_restaurant", 3, "afternoon", "A"),
          _stop("Bar2", "bar", 3, "evening", "B")]
    out, _ = agent.arrange_trip(it)
    night = {"Club1", "Club2", "Bar1", "Bar2"}
    assert not [x["place"] for x in out if x["place"] in night and x["slot"] == "morning"]
    assert sum(1 for x in out if x["place"] in night and x["slot"] == "evening") == 3
    assert sorted((x["day"], x["slot"]) for x in out) == sorted((x["day"], x["slot"]) for x in it)


def test_landmarks_and_viewpoints_are_daytime_stops():
    assert agent._slot_fit({"categories": ["natural_feature"]}, "evening") < 0
    assert agent._slot_fit({"categories": ["tower"]}, "morning") == 2


def test_bar_is_worse_than_lunch_spot_in_the_afternoon():
    bar = {"categories": ["bar"]}
    lunch = {"categories": ["restaurant"]}
    assert agent._slot_fit(bar, "afternoon") < agent._slot_fit(lunch, "afternoon")
    assert agent._slot_fit(bar, "morning") < agent._slot_fit(lunch, "morning")


def test_narrative_is_honest_when_the_group_outnumbers_the_stops():
    t = [{"label": n, "likes": [{"name": "Daft Punk", "type": "artist"}]} for n in "ABCDEF"]
    r = plan(t, days=1)
    zero = [k for k, v in r["fair_share"].items() if v == 0]
    assert len(r["itinerary"]) == 3 and len(zero) == 3
    assert "Everyone gets their own picks" not in r["narrative"]
    assert "×0" not in r["narrative"]
    assert all(z in r["narrative"] for z in zero) and "more days" in r["narrative"]


def test_narrative_rounding_reads_naturally():
    pools = {"A": [{"id": "a", "name": "a", "affinity": 0.9}], "B": [{"id": "b", "name": "b", "affinity": 0.9}]}
    matrix = {"A": {"a": 0.9, "b": 0.9}, "B": {"a": 0.9, "b": 0.9}}
    _, _, dec = build_itinerary(["A", "B"], pools, matrix, {}, 1, {})
    text = " ".join(d["text"] for d in dec)
    assert "within 0 pts" not in text and "under 1 pt" in text
    twins = [{"label": n, "likes": [{"name": "Daft Punk", "type": "artist"}]} for n in "AB"]
    r = plan(twins, days=1)
    assert not re.search(r"(\d+)–\1%", r["narrative"]) and "about " in r["narrative"]
    assert "under 1 pt" in c.get("/").text


def test_solo_and_unmatched_traveler_wording():
    r = plan([{"label": "Solo", "likes": [{"name": "Daft Punk", "type": "artist"}]}], days=1)
    assert "least-matched" not in r["narrative"] and "shared" not in r["narrative"]
    r = plan([{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}]},
              {"label": "B", "likes": [{"name": "zzqx", "type": "movie"}]}], days=1)
    assert "B" in r["narrative"] and "weren't found" in r["narrative"]
    assert "Everyone gets" not in r["narrative"]
