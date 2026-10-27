"""Fifth judge audit, from a live run with non-sample groups: B2B listings as trip stops, a museum labelled by its
operator, a tie called a "least-matched traveler", and a Cyrillic city name with no hint what to type instead."""
from fastapi.testclient import TestClient

from app import agent, qloo
from app.agent import fairness, kind, narrate, plan, visitable
from app.main import app

c = TestClient(app)


def _p(*cats, name="Somewhere"):
    return {"name": name, "categories": list(cats)}


def test_trade_and_b2b_listings_are_not_trip_stops():
    # Qloo's Tehran / Ensenada / Tver results for real groups
    assert not visitable(_p("electrical_appliance_wholesaler"))
    assert not visitable(_p("port_operating_company"))
    assert not visitable(_p("marine_engineer", "yacht_broker", "yacht_club"))
    assert not visitable(_p("food_products_supplier"))
    assert not visitable(_p("furniture_manufacturer"))


def test_a_sight_run_by_a_non_profit_stays_and_reads_as_a_museum():
    hart = _p("non_profit_organization", "museum", "art_museum", "tourist_attraction")
    assert visitable(hart)
    assert kind(hart) == "Museum"
    assert visitable(_p("tea_house", "cafe")) and kind(_p("tea_house", "cafe")) == "Tea house"
    assert kind(_p("seafood_restaurant", "restaurant")) == "Seafood restaurant"  # unchanged


def test_equal_scores_name_no_least_matched_traveler():
    group = [{"name": "Santa Clarita", "affinity": 0.9}, {"name": "Pasadena", "affinity": 0.8}]
    per = {"A": {"Santa Clarita": 0.907, "Pasadena": 0.7}, "B": {"Santa Clarita": 0.907, "Pasadena": 0.9}}
    rk = {r["name"]: r for r in fairness(per, group)}
    assert rk["Santa Clarita"]["least_happy"] is None
    assert rk["Pasadena"]["least_happy"] == "A"


def _result(least):
    top = {"name": "Santa Clarita", "group_fit": 90.7, "per_traveler": {"A": 0.9, "B": 0.9}, "least_happy": least}
    return {"ranking": [top], "fair_share": {"A": 3, "B": 3}, "chosen": None, "destination": "Santa Clarita",
            "itinerary": [{}] * 6, "unmatched_travelers": [], "fairness_check": {}}


def test_narrative_on_a_tie_says_equal_fit_not_none(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    text = narrate(_result(None))
    assert "least-matched traveler: None" not in text and "an equal fit for everyone" in text
    assert "least-matched traveler: A" in narrate(_result("A"))
    assert "none, equal fit" in c.get("/").text  # the result chip says so too, instead of a bare dash


def test_cyrillic_destination_gets_an_english_name_hint(monkeypatch):
    real = qloo.search

    def search(q, t, n=1):
        return [] if t == "urn:entity:destination" else real(q, t, n)

    monkeypatch.setattr(agent.qloo, "search", search)
    two = [{"label": "A", "likes": [{"name": "Daft Punk", "type": "artist"}]},
           {"label": "B", "likes": [{"name": "Spirited Away", "type": "movie"}]}]
    r = plan(two, days=1, destination="Москва")
    assert r["error"] == "destination_not_found" and "English names" in r["ask"]
    r = plan(two, days=1, destination="Atlantisville")
    assert r["error"] == "destination_not_found" and "English names" not in r["ask"]


def test_not_found_warning_suggests_checking_the_spelling():
    assert "Check the spelling or try the full English title" in c.get("/").text
