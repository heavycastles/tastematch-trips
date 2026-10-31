"""Final pre-submit pass: one entry per city in the ranking, and per-traveler Qloo calls run side by side."""
import threading
import time

import httpx

from app import agent, qloo

GEO = {  # Qloo really returns these near-duplicates for a Radiohead + Blade Runner fan
    "Mexico City": (19.4326, -99.1332, 0.88), "Oaxaca": (17.0603, -96.7255, 0.87),
    "Distrito Federal, Mexico City": (19.344362, -99.13226, 0.86), "Oaxaca City": (17.0606, -96.7254, 0.85),
    "Puebla": (19.044855, -98.19516, 0.84), "Cuernavaca, Morelos": (18.9333, -99.2333, 0.83),
}


def test_same_city_listed_twice_is_merged_but_neighbours_stay():
    ranking = [{"name": n, "group_fit": 100 * g[2]} for n, g in GEO.items()]
    coords = {n: g[:2] for n, g in GEO.items()}
    kept, merged = agent.dedupe_cities(ranking, coords)
    assert [r["name"] for r in kept] == ["Mexico City", "Oaxaca", "Puebla", "Cuernavaca, Morelos"]
    assert merged == 2
    # Kyoto and Nara are ~35 km apart: two real destinations, both stay
    kyoto_nara = {"Kyoto": (35.0116, 135.7681), "Nara": (34.6851, 135.8048)}
    assert len(agent.dedupe_cities([{"name": "Kyoto"}, {"name": "Nara"}], kyoto_nara)[0]) == 2
    # no coordinates (mock graph): nothing is dropped
    assert agent.dedupe_cities(ranking, {})[0] == ranking


def test_duplicate_of_the_groups_own_city_is_not_offered_as_qloo_best_match():
    coords = {"Distrito Federal, Mexico City": GEO["Distrito Federal, Mexico City"][:2], "Oaxaca": GEO["Oaxaca"][:2]}
    kept, _ = agent.dedupe_cities([{"name": "Distrito Federal, Mexico City"}, {"name": "Oaxaca"}], coords,
                                  chosen_at=GEO["Mexico City"][:2])
    assert [r["name"] for r in kept] == ["Oaxaca"]


def _live(monkeypatch, handler):
    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()


def _dest(name, aff):
    lat, lon, _ = GEO[name]
    return {"entity_id": "D-" + name, "name": name, "query": {"affinity": aff}, "location": {"lat": lat, "lon": lon}}


def _handler(delay=0.0, active=None):
    lock = threading.Lock()

    def handler(url, **kw):
        if active is not None:
            with lock:
                active[0] += 1
                active[1] = max(active[1], active[0])
        try:
            time.sleep(delay)
            params = dict(kw.get("params") or [])
            if url.endswith("/search"):
                return httpx.Response(200, json={"results": [{"entity_id": "E-" + params["query"],
                                                              "name": params["query"]}]})
            if params.get("filter.type") == "urn:entity:destination":
                return httpx.Response(200, json={"results": {"entities": [
                    _dest("Mexico City", 0.9), _dest("Distrito Federal, Mexico City", 0.89), _dest("Oaxaca", 0.8)]}})
            tag = [{"id": "urn:tag:category:place:museum", "name": "museum", "type": "urn:tag:category:place"}]
            return httpx.Response(200, json={"results": {"entities": [
                {"entity_id": f"P{i}", "name": f"Museo {i}", "tags": tag, "query": {"affinity": 0.9 - i / 100}}
                for i in range(6)]}})
        finally:
            if active is not None:
                with lock:
                    active[0] -= 1
    return handler


GROUP = [{"label": n, "likes": [{"name": f"{n} fav {i}", "type": "movie"} for i in range(2)]}
         for n in ("Ana", "Ben", "Chen", "Dana")]


def test_live_ranking_shows_each_city_once_and_the_trace_says_so(monkeypatch):
    _live(monkeypatch, _handler())
    try:
        r = agent.plan([dict(t) for t in GROUP], days=1)
    finally:
        qloo._cached_get.cache_clear()
    names = [x["name"] for x in r["ranking"]]
    assert names == ["Mexico City", "Oaxaca"]
    group = next(s for s in r["trace"] if s["tool"] == "destination_affinity" and s["traveler"] == "group")
    assert group["merged"] == 1


def test_per_traveler_calls_run_in_parallel_and_the_trace_keeps_input_order(monkeypatch):
    active = [0, 0]
    _live(monkeypatch, _handler(delay=0.05, active=active))
    try:
        t0 = time.perf_counter()
        r = agent.plan([dict(t) for t in GROUP], days=2)
        took = time.perf_counter() - t0
    finally:
        qloo._cached_get.cache_clear()
    calls = r["stats"]["qloo_calls"]
    assert calls == 8 + 1 + 4 + 4 + 4  # 8 favourites, group, 4 per-traveler cities, 4 place pools, 4 cross-scores
    assert active[1] > 1  # really concurrent
    assert took < calls * 0.05 * 0.6  # well under the sequential time
    assert r["stats"]["cached"] == 0  # every parallel call was counted as a fresh Qloo request
    queries = [s["query"] for s in r["trace"] if s["tool"] == "resolve_entity"]
    assert queries == [like["name"] for t in GROUP for like in t["likes"]]
    for tool in ("destination_affinity", "local_places", "cross_score_places"):
        who = [s["traveler"] for s in r["trace"] if s["tool"] == tool and s["traveler"] != "group"]
        assert who == ["Ana", "Ben", "Chen", "Dana"]


def test_parallel_calls_share_the_plan_time_budget(monkeypatch):
    _live(monkeypatch, _handler())
    monkeypatch.setenv("QLOO_REQUEST_BUDGET", "0")
    try:
        try:
            agent.plan([dict(t) for t in GROUP], days=1)
            raise AssertionError("expected the shared deadline to stop the plan")
        except qloo.QlooError as e:
            assert e.kind == "qloo_timeout"
    finally:
        qloo._cached_get.cache_clear()


def test_trace_row_tells_the_user_about_merged_cities():
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")
    assert "s.merged" in html and "duplicate city" in html
