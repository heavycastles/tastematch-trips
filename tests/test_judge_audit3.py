"""Third judge audit: international and typo'd favourites, wrong types, solo 5-day trips, six travelers, and
error paths (Qloo empty, slow, down, garbled) must read honestly; the page must be accessible."""
import re

import httpx
from fastapi.testclient import TestClient

from app import agent, qloo
from app.agent import build_itinerary, name_fit, plan
from app.main import app

c = TestClient(app)


def _live(monkeypatch, handler):
    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setattr(qloo.time, "sleep", lambda s: None)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()


def _venues(n, cat="museum", prefix="V"):
    return [{"entity_id": f"{prefix}{i}", "name": f"{prefix}{i} place", "query": {"affinity": 0.9 - i / 100},
             "tags": [{"id": f"urn:tag:category:place:{cat}", "name": cat}]} for i in range(n)]


def _graph(search=None, dests=True, venues=None, calls=None, per_taster=False):
    venues = venues if venues is not None else _venues(30)

    def handler(url, **kw):
        p = dict(kw.get("params") or [])
        if calls is not None:
            calls.append((url.rsplit("/", 1)[-1], p))
        if url.endswith("/search"):
            res = search(p) if search else [{"entity_id": "E-" + p["query"], "name": p["query"]}]
            return httpx.Response(200, json={"results": res})
        if p.get("filter.type") == "urn:entity:destination":
            ents = [{"entity_id": "D1", "name": "Lisbon", "query": {"affinity": 0.8}}] if dests else []
            return httpx.Response(200, json={"results": {"entities": ents}})
        ents = venues
        if per_taster and "signal.interests.entities" in p:
            ents = _venues(30, prefix=p["signal.interests.entities"][-1])
        if "filter.entities" in p:
            ids = p["filter.entities"].split(",")
            ents = [e for t in "ABCDEFV" for e in _venues(30, prefix=t) if e["entity_id"] in ids]
        return httpx.Response(200, json={"results": {"entities": ents}})
    return handler


def test_name_fit_handles_typos_accents_and_translations():
    assert name_fit("Spirted Away", "Spirited Away") > 0.9
    assert name_fit("amelie", "Amélie") == 1.0
    assert name_fit("Amélie", "Le Fabuleux Destin d'Amélie Poulain") == 0.9
    assert name_fit("Studio Ghibli", "Picsart Photo Studio") < agent.LOOSE


def test_wrong_type_is_retried_across_types(monkeypatch):
    """'Studio Ghibli' picked as a Brand matched a photo app; Qloo knows it as an artist."""
    def search(p):
        if p.get("types") == "urn:entity:brand":
            return [{"entity_id": "PICS", "name": "Picsart Photo Studio", "types": ["urn:entity:brand"]}]
        return [{"entity_id": "GH-L", "name": "Studio Ghibli", "types": ["urn:entity:locality"]},
                {"entity_id": "GH", "name": "Studio Ghibli", "types": ["urn:entity:artist"]}]
    _live(monkeypatch, _graph(search))
    try:
        r = plan([{"label": "A", "likes": [{"name": "Studio Ghibli", "type": "brand"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert r["travelers"][0]["matched"] == ["Studio Ghibli"]
    step = r["trace"][0]
    assert step["matched"] == "Studio Ghibli" and step["retyped"] == "artist"
    assert not r["loose_matches"]
    assert "found as" in c.get("/").text


def test_translated_title_is_kept_and_flagged_not_swapped_for_a_place(monkeypatch):
    def search(p):
        if p.get("types") == "urn:entity:movie":
            return [{"entity_id": "COG", "name": "City of God", "types": ["urn:entity:movie"]}]
        return [{"entity_id": "LOC", "name": "Cidade de Deus", "types": ["urn:entity:locality"]}]
    _live(monkeypatch, _graph(search))
    try:
        r = plan([{"label": "João", "likes": [{"name": "Cidade de Deus", "type": "movie"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert r["travelers"][0]["matched"] == ["City of God"]
    assert r["loose_matches"] == ["João: “Cidade de Deus” → City of God"]
    assert "loose_matches" in c.get("/").text


def test_non_latin_favourites_do_not_trigger_extra_lookups(monkeypatch):
    calls = []

    def search(p):
        return [{"entity_id": "SA", "name": "Spirited Away", "types": ["urn:entity:movie"]}]
    _live(monkeypatch, _graph(search, calls=calls))
    try:
        r = plan([{"label": "Yūki", "likes": [{"name": "千と千尋の神隠し", "type": "movie"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert r["travelers"][0]["matched"] == ["Spirited Away"] and not r["loose_matches"]
    assert sum(1 for k, _ in calls if k == "search") == 1


def test_solo_five_day_trip_fills_all_five_days(monkeypatch):
    _live(monkeypatch, _graph())
    try:
        r = plan([{"label": "Nodira", "likes": [{"name": "x", "type": "movie"}]}], days=5)
    finally:
        qloo._cached_get.cache_clear()
    assert len(r["itinerary"]) == 15 and {x["day"] for x in r["itinerary"]} == {1, 2, 3, 4, 5}


def test_short_itinerary_is_explained_in_the_ui():
    assert "enough for ${got} of ${want} days" in c.get("/").text


def test_global_chains_and_bare_addresses_are_not_picked_when_better_stops_exist():
    starbucks = {"id": "S", "name": "Starbucks Coffee - Kyoto Porta", "categories": ["cafe"], "affinity": 0.99}
    addr = {"id": "B", "name": "239 Queen's Rd W", "categories": ["building"], "affinity": 0.98}
    rest = [{"id": f"r{i}", "name": f"Temple {i}", "categories": ["temple"], "affinity": 0.9} for i in range(8)]
    pool = agent._stops([starbucks, addr] + rest)
    ids = [p["id"] for p in pool]
    assert "S" not in ids and "B" not in ids and len(pool) == 8
    # a chain still fills in when it's all a small town has
    assert [p["id"] for p in agent._stops([starbucks])] == ["S"]
    assert agent.visitable({"name": "Empire State Building", "categories": ["building", "observation_deck"]})


def test_gap_just_over_the_limit_is_not_printed_as_equal_to_it():
    assert agent._gap(0.051, 0.05) == "5.1" and agent._gap(0.07, 0.05) == "7" and agent._gap(0.05, 0.05) == "5"
    pools = {"A": [{"id": "a", "name": "a", "affinity": 0.9}], "B": [{"id": "b", "name": "b", "affinity": 0.9}]}
    matrix = {"A": {"a": 1.0, "b": 0.949}, "B": {"a": 1.0, "b": 1.0}}
    _, check, dec = build_itinerary(["A", "B"], pools, matrix, {}, 1, {})
    text = " ".join(d["text"] for d in dec)
    assert not re.search(r"gap 5 pts > 5", text)
    assert "raw<=5+1e-9" in c.get("/").text  # the UI verdict uses the same unrounded threshold


def test_six_conflicting_travelers_on_five_days_all_get_picks(monkeypatch):
    _live(monkeypatch, _graph(per_taster=True))
    t = [{"label": n, "likes": [{"name": f"taste {n}", "type": "artist"}]} for n in "ABCDEF"]
    try:
        r = plan(t, days=5)
    finally:
        qloo._cached_get.cache_clear()
    assert len(r["itinerary"]) == 15 and all(v >= 2 for v in r["fair_share"].values())


def test_qloo_with_no_destinations_is_an_honest_message(monkeypatch):
    _live(monkeypatch, _graph(dests=False))
    try:
        r = c.post("/api/plan", json={"days": 1, "travelers": [{"label": "A", "likes": [{"name": "x"}]}]})
    finally:
        qloo._cached_get.cache_clear()
    d = r.json()
    assert d["error"] == "no_destinations" and "Destination field" in d["ask"]
    assert "no_destinations:" in c.get("/").text


def test_qloo_returning_html_instead_of_json_is_a_clean_502(monkeypatch):
    def handler(url, **kw):
        return httpx.Response(200, text="<html>Bad gateway</html>")
    _live(monkeypatch, handler)
    try:
        r = c.post("/api/plan", json={"days": 1, "travelers": [{"label": "A", "likes": [{"name": "x"}]}]})
    finally:
        qloo._cached_get.cache_clear()
    assert r.status_code == 502 and r.json()["error"] == "upstream"


def test_qloo_unreachable_and_slow_are_clean_errors(monkeypatch):
    for exc, code, kind in ((httpx.ConnectError("down"), 502, "upstream"),
                            (httpx.ReadTimeout("slow"), 504, "qloo_timeout")):
        def handler(url, exc=exc, **kw):
            raise exc
        _live(monkeypatch, handler)
        try:
            r = c.post("/api/plan", json={"days": 1, "travelers": [{"label": "A", "likes": [{"name": "x"}]}]})
        finally:
            qloo._cached_get.cache_clear()
        assert r.status_code == code and r.json()["error"] == kind and r.json()["ask"]


def test_frontend_error_paths_are_honest():
    html = c.get("/").text
    assert "r.json().catch(" in html  # a non-JSON 500/504 page doesn't become a fake "network" error
    assert "AbortController" in html and "Connection problem" in html and "Something broke on our side" in html


def test_form_controls_have_accessible_names():
    html = c.get("/").text
    assert '<label for="dest">' in html and 'role="group" aria-labelledby="dayslbl"' in html
    for attr in ("favourite '+(j+1)+' type", "' nickname'", "'Remove traveler '", "aria-pressed"):
        assert attr in html, attr
    assert 'role="alert"' in html and 'aria-live="polite"' in html
    assert ":focus-visible" in html and "prefers-reduced-motion" in html
    assert "outline:none}" not in html.split(".lbl{", 1)[1].split("\n", 1)[0] or ".lbl:focus-visible" in html


def test_white_text_sits_on_aa_contrast_colours():
    html = c.get("/").text
    dark = dict(re.findall(r"'(#[0-9a-f]{6})':'(#[0-9a-f]{6})'", html.split("const DARK=", 1)[1].split(";", 1)[0]))

    def lum(h):
        v = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        v = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in v]
        return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    assert len(dark) == 6
    for c_ in dark.values():
        assert 1.05 / (lum(c_) + 0.05) >= 4.5, c_
    muted = re.search(r"--muted:(#[0-9a-f]{6})", html).group(1)
    assert (lum("#f7f6fb") + 0.05) / (lum(muted) + 0.05) >= 4.5
