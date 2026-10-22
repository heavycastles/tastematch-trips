"""Venue-level fairness: cross-scored stops, group-aware picks, self-check and re-plan, share link UI."""
import httpx
from fastapi.testclient import TestClient

from app import qloo
from app.agent import _norm, build_itinerary, plan
from app.main import SAMPLE, app

c = TestClient(app)


def _p(pid, aff):
    return {"id": pid, "name": pid, "affinity": aff}


def test_every_stop_is_scored_for_every_traveler_mock():
    r = plan(SAMPLE["travelers"], days=2)
    labels = {"Aziz", "Malika", "Rustam"}
    tools = [s["tool"] for s in r["trace"]]
    assert tools.count("cross_score_places") == 3
    assert r["stats"]["qloo_calls"] == len(r["trace"])  # decisions are not counted as Qloo calls
    for x in r["itinerary"]:
        assert set(x["group_scores"]) == labels and all(0 <= v <= 1 for v in x["group_scores"].values())
        assert x["group_scores"][x["for"]] == round(x["affinity"], 3)
    fc = r["fairness_check"]
    assert set(fc["trip_enjoyment"]) == labels and fc["scored_for_everyone"] is True
    assert fc["own_picks"] == r["fair_share"]
    assert {d["step"] for d in r["decisions"]} >= {"compensate"}
    assert "Fairness self-check" in r["narrative"]


def test_least_matched_traveler_picks_first():
    pools = {"A": [_p("a1", 0.9)], "B": [_p("b1", 0.9)]}
    matrix = {"A": {"a1": 0.9, "b1": 0.5}, "B": {"a1": 0.5, "b1": 0.9}}
    it, _, dec = build_itinerary(["A", "B"], pools, matrix, {}, 1, {"A": 0.8, "B": 0.6})
    assert it[0]["for"] == "B" and dec[0]["step"] == "compensate" and "B is the least-matched" in dec[0]["text"]


def test_group_aware_pick_stays_in_owners_top_tier():
    # A's best is a1 (0.90) but B hates it; a2 is within the tier and B loves it; a3 is great for B but not A's tier.
    pools = {"A": [_p("a1", 0.90), _p("a2", 0.89), _p("a3", 0.70)], "B": [_p("b1", 0.9)]}
    matrix = {"A": {"a1": 0.90, "a2": 0.89, "a3": 0.70, "b1": 0.6},
              "B": {"a1": 0.30, "a2": 0.85, "a3": 0.95, "b1": 0.9}}
    it, _, dec = build_itinerary(["A", "B"], pools, matrix, {}, 1, {})
    first_a = next(x for x in it if x["for"] == "A")
    assert first_a["place"] == "a2"
    assert any(d["step"] == "group_aware" for d in dec)


def test_self_check_replans_and_keeps_only_improvements():
    # A picks first; within the narrow tier A takes a1 (B hates it). The wider window lets a2 in → smaller gap.
    pools = {"A": [_p("a1", 0.90), _p("a2", 0.82)], "B": [_p("b1", 0.9)]}
    matrix = {"A": {"a1": 0.90, "a2": 0.82, "b1": 0.85}, "B": {"a1": 0.10, "a2": 0.88, "b1": 0.90}}
    it, fc, dec = build_itinerary(["A", "B"], pools, matrix, {}, 1, {"A": 0.5, "B": 0.9})
    rev = next(d for d in dec if d["step"] == "revise")
    assert "kept the revision" in rev["text"]
    assert [x["place"] for x in it if x["for"] == "A"][0] == "a2"
    assert fc["spread"] <= 0.1


def test_norm_compares_travelers_to_their_own_best():
    n = _norm({"A": {"x": 0.9, "y": 0.45}, "B": {"x": 0.6}})
    assert n["A"] == {"x": 1.0, "y": 0.5} and n["B"] == {"x": 1.0}


def test_single_traveler_skips_cross_scoring():
    r = plan([{"label": "Solo", "likes": [{"name": "Daft Punk", "type": "artist"}]}], days=1)
    assert "cross_score_places" not in [s["tool"] for s in r["trace"]]
    assert r["itinerary"] and [d for d in r["decisions"] if d["step"] != "time_of_day"] == []


def test_cross_score_failure_degrades_gracefully(monkeypatch):
    def handler(url, **kw):
        params = dict(kw.get("params") or [])
        if url.endswith("/search"):
            return httpx.Response(200, json={"results": [{"entity_id": "E-" + params["query"],
                                                          "name": params["query"]}]})
        if params.get("filter.type") == "urn:entity:place":
            if "filter.entities" in params:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, json={"results": {"entities": [
                {"entity_id": "P-" + params["signal.interests.entities"], "name": "Stop " +
                 params["signal.interests.entities"], "query": {"affinity": 0.8}}]}})
        return httpx.Response(200, json={"results": {"entities": [
            {"entity_id": "D1", "name": "Lisbon", "query": {"affinity": 0.7}}]}})

    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    t = [{"label": "A", "likes": [{"name": "x", "type": "movie"}]},
         {"label": "B", "likes": [{"name": "y", "type": "movie"}]}]
    r = plan(t, days=1)
    assert len(r["itinerary"]) == 2 and r["fairness_check"]["scored_for_everyone"] is False
    assert all(s["results"] == 0 for s in r["trace"] if s["tool"] == "cross_score_places")


def test_ui_has_share_link_copy_and_fairness_card():
    html = c.get("/").text
    for needle in ("#plan=", "loadFromHash", "Copy for group chat", "Share this plan", "Fairness self-check",
                   "cross_score_places", "navigator.clipboard", "aria-live"):
        assert needle in html
    r = c.post("/api/plan", json=SAMPLE)
    assert r.status_code == 200 and r.json()["fairness_check"]["trip_enjoyment"]


def test_traveler_without_resolved_tastes_is_not_counted_as_unhappy():
    t = SAMPLE["travelers"] + [{"label": "Ghost", "likes": [{"name": "zzqx unknown", "type": "movie"}]}]
    r = plan(t, days=2)
    assert "Ghost" not in r["fairness_check"]["trip_enjoyment"]
    assert r["unresolved"] == ["Ghost: zzqx unknown"]
    assert all("Ghost" not in x["per_traveler"] for x in r["ranking"])
    assert r["ranking"][0]["least_happy"] != "Ghost" and "Ghost" not in r["fair_share"]
