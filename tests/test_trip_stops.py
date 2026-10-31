"""Trip stops must be places a group actually visits, at a sensible time of day."""
import httpx

from app import agent, qloo


def _p(name, *cats, desc="", aff=0.8):
    return {"id": name, "name": name, "categories": list(cats), "description": desc, "affinity": aff}


def test_hotels_condos_and_errands_are_not_stops():
    assert not agent.visitable(_p("Casa Velas", "hotel"))
    assert not agent.visitable(_p("Iberostar", "resort_hotel"))
    assert not agent.visitable(_p("Krystal Grand", "restaurant", "event_venue", "hotel"))
    assert not agent.visitable(_p("Peninsula", "housing_development", "condominium_complex"))
    assert not agent.visitable(_p("My Best Friend", "pet_store"))
    assert not agent.visitable(_p("Smile", "dental_clinic"))
    assert not agent.visitable(_p("Hacienda", "guest_house"))
    assert agent.visitable(_p("Mita Mary", "seafood_restaurant"))
    assert agent.visitable(_p("Playa Sayulita", "beach"))
    assert agent.visitable(_p("Aquaventuras", "water_park", "tourist_attraction"))
    assert agent.visitable(_p("Insu Sky Bar", "bar_grill", "bar"))


def test_uncategorised_venues_fall_back_to_description():
    assert not agent.visitable(_p("Vidanta", desc="Sprawling beachfront resort with golf courses"))
    assert not agent.visitable(_p("Family Residences by Villa del Palmar"))
    assert agent.visitable(_p("Tacos Break", desc="Late-night taqueria"))


def test_pool_keeps_top_visitable_and_falls_back_when_only_hotels():
    places = [_p(f"H{i}", "hotel") for i in range(5)] + [_p(f"R{i}", "restaurant") for i in range(10)]
    pool = agent._stops(places)
    assert [p["name"] for p in pool] == [f"R{i}" for i in range(agent.POOL_SIZE)]
    assert pool.skipped == 5 and pool.fallback is False
    only_hotels = [_p(f"H{i}", "hotel") for i in range(3)]
    fallback = agent._stops(only_hotels)
    assert [p["name"] for p in fallback] == ["H0", "H1", "H2"]
    assert fallback.fallback is True


def test_kind_label_prefers_specific_category():
    assert agent.kind(_p("x", "restaurant", "mexican_restaurant")) == "Mexican restaurant"
    assert agent.kind(_p("x", "place", "food_and_drink")) is None
    assert agent.kind(_p("x", "beach")) == "Beach"


def test_day_is_arranged_by_venue_type_without_changing_stops():
    day = [dict(_p("Insu Sky Bar", "bar"), slot="morning", day=1, **{"for": "A"}),
           dict(_p("La Esperanza", "breakfast_restaurant"), slot="afternoon", day=1, **{"for": "B"}),
           dict(_p("Playa", "beach"), slot="evening", day=1, **{"for": "C"})]
    out, moved = agent.arrange_day(day)
    assert moved
    assert {x["slot"]: x["name"] for x in out} == {"morning": "La Esperanza", "afternoon": "Playa",
                                                    "evening": "Insu Sky Bar"}
    assert sorted(x["for"] for x in out) == ["A", "B", "C"]


def test_haunted_house_is_an_evening_stop():
    # Qloo's "Trick or Treat" in Roppongi (category haunted_house, a late-night horror izakaya) was landing at 9 am
    ghost = _p("Trick or Treat", "haunted_house")
    assert agent._slot_fit(ghost, "morning") < 0 < agent._slot_fit(ghost, "evening")
    day = [dict(ghost, slot="morning", day=3, **{"for": "Ana"}),
           dict(_p("Senso-ji", "temple"), slot="afternoon", day=3, **{"for": "Ben"}),
           dict(_p("Ramen", "ramen_restaurant"), slot="evening", day=3, **{"for": "Chen"})]
    out, moved = agent.arrange_day(day)
    assert moved and {x["slot"]: x["name"] for x in out}["morning"] == "Senso-ji"
    assert {x["slot"]: x["name"] for x in out}["morning"] != "Trick or Treat"


def test_whole_word_category_match():
    # 'spa' must not match 'spanish_restaurant'; a Spanish restaurant is a dinner spot
    assert agent._slot_fit(_p("Tapas", "spanish_restaurant"), "evening") == 2
    assert agent._slot_fit(_p("Day spa", "day_spa"), "morning") == 2


def test_live_plan_drops_hotels_and_asks_for_a_wider_list(monkeypatch):
    seen_takes = []

    def handler(url, **kw):
        params = dict(kw.get("params") or [])
        if url.endswith("/search"):
            return httpx.Response(200, json={"results": [{"entity_id": "E-" + params["query"],
                                                          "name": params["query"]}]})
        if params.get("filter.type") == "urn:entity:place":
            if "filter.entities" not in params:
                seen_takes.append(int(params["take"]))
            cat = lambda c: [{"id": f"urn:tag:category:place:{c}", "name": c, "type": "urn:tag:category:place"}]  # noqa: E731
            ents = ([{"entity_id": f"H{i}", "name": f"Hotel {i}", "tags": cat("hotel"),
                      "query": {"affinity": 0.9}} for i in range(4)]
                    + [{"entity_id": "C1", "name": "Cafe Uno", "tags": cat("cafe"), "query": {"affinity": 0.8}},
                       {"entity_id": "B1", "name": "Bar Dos", "tags": cat("cocktail_bar"), "query": {"affinity": 0.79}},
                       {"entity_id": "M1", "name": "Museo", "tags": cat("museum"), "query": {"affinity": 0.78}}])
            if "filter.entities" in params:
                ids = params["filter.entities"].split(",")
                ents = [e for e in ents if e["entity_id"] in ids]
            return httpx.Response(200, json={"results": {"entities": ents}})
        return httpx.Response(200, json={"results": {"entities": [
            {"entity_id": "D1", "name": "Lisbon", "query": {"affinity": 0.7}}]}})

    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    try:
        r = agent.plan([{"label": "A", "likes": [{"name": "x", "type": "movie"}]},
                        {"label": "B", "likes": [{"name": "y", "type": "movie"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert seen_takes and all(t == agent.PLACE_TAKE for t in seen_takes)
    names = [x["place"] for x in r["itinerary"]]
    assert names and not any(n.startswith("Hotel") for n in names)
    slots = {x["slot"]: x["place"] for x in r["itinerary"]}
    assert slots["evening"] == "Bar Dos"
    assert all(x["kind"] for x in r["itinerary"])
    lp = [s for s in r["trace"] if s["tool"] == "local_places"]
    assert lp and all(s["skipped"] == 4 for s in lp)


def test_stats_report_cached_qloo_calls(monkeypatch):
    def handler(url, **kw):
        params = dict(kw.get("params") or [])
        if url.endswith("/search"):
            return httpx.Response(200, json={"results": [{"entity_id": "E1", "name": params["query"]}]})
        return httpx.Response(200, json={"results": {"entities": [
            {"entity_id": "D1", "name": "Lisbon", "query": {"affinity": 0.7}}]}})

    monkeypatch.setattr(httpx, "get", handler)
    monkeypatch.setenv("QLOO_API_KEY", "k")
    monkeypatch.delenv("QLOO_FORCE_MOCK", raising=False)
    qloo._cached_get.cache_clear()
    t = [{"label": "A", "likes": [{"name": "x", "type": "movie"}]}]
    try:
        first, again = agent.plan(t, days=1), agent.plan(t, days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert first["stats"]["cached"] == 0
    assert again["stats"]["cached"] == first["stats"]["qloo_calls"] > 0
    assert again["stats"]["qloo_calls"] == 0


def test_shops_are_daytime_and_stadiums_evening():
    assert agent._slot_fit(_p("99 Problems", "shoe_store"), "evening") == -1
    assert agent._slot_fit(_p("Banorte Stadium", "stadium"), "evening") == 2


def test_stop_chips_skip_demographic_payment_and_time_tags():
    entity = {"tags": [
        {"id": "urn:tag:age_range:qloo:18_24", "name": "18 24"},
        {"id": "urn:tag:payments:place:nfc_mobile_payments", "name": "Nfc mobile payments"},
        {"id": "urn:tag:payments:place:price_level", "name": "Price level"},
        {"id": "urn:tag:time_of_day_fit:qloo:afternoon", "name": "Afternoon"},
        {"id": "urn:tag:parking:place:free_parking_lot", "name": "Free parking lot"},
        # live /search + /v2/insights shape: the urn sits in tag_id / type, not id
        {"tag_id": "urn:tag:credit_card:place:mastercard", "type": "urn:tag:credit_card:place", "name": "Mastercard"},
        {"type": "urn:tag:planning:place", "name": "Accepts reservations"},
        {"id": "urn:tag:category:place:seafood_restaurant", "name": "Seafood restaurant"},
        {"id": "urn:tag:menu_highlight:qloo:salmon_ceviche", "name": "Salmon ceviche"},
        {"id": "urn:tag:ambience:qloo:casual", "name": "Casual"},
        "Surf town",
    ]}
    assert qloo._tag_names(entity) == ["Seafood restaurant", "Salmon ceviche", "Casual", "Surf town"]
