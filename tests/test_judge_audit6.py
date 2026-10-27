"""Sixth judge audit, from live runs with fresh groups (Dubai, Tokyo, Pasadena): a picture-framing shop picked as a
trip stop, "Michael Jordan" silently matched to the actor Michael B. Jordan, and a landmark house labelled
"Book store" because it has a gift shop."""
from app import qloo
from app.agent import kind, other_name, plan, visitable
from tests.test_judge_audit3 import _graph, _live


def _p(*cats, name="Somewhere"):
    return {"name": name, "categories": list(cats)}


def test_errand_shops_are_not_trip_stops():
    assert not visitable(_p("picture_frame_shop"))  # Qloo's "Frame Dubai - Picture Framing Shop"
    assert not visitable(_p("print_shop", "copy_shop"))
    assert not visitable(_p("hardware_store"))
    assert not visitable(_p("mobile_phone_store"))
    assert not visitable(_p("electronics_repair_shop", "repair"))
    assert not visitable(_p("website_designer"))  # Qloo's "The Futur" in Los Angeles
    assert not visitable(_p("graphic_designer", "advertising_agency"))
    assert not visitable(_p("software_company"))
    # real shopping and sights still count
    assert visitable(_p("book_store", "gift_shop"))
    assert visitable(_p("clothing_store", "shoe_store"))
    assert visitable(_p("tourist_attraction", "garden"))


def test_a_landmark_with_a_gift_shop_reads_as_the_landmark():
    gamble = _p("book_store", "tourist_attraction", "historical_landmark", "museum")
    assert kind(gamble) == "Historical landmark"
    assert kind(_p("gift_shop", "tourist_attraction")) == "Tourist attraction"
    assert kind(_p("book_store", "gift_shop")) == "Book store"  # a plain shop stays a shop
    assert kind(_p("museum", "art_center")) == "Museum"  # unchanged


def test_similar_name_with_extra_words_is_another_entity():
    assert other_name("Michael Jordan", "Michael B. Jordan")
    assert not other_name("Michael Jordan", "Michael Jordan")
    assert not other_name("Amélie", "Le Fabuleux Destin d'Amélie Poulain")  # the full title: same film
    assert not other_name("Harry Potter", "Harry Potter and the Deathly Hallows: Part 2")
    assert not other_name("Spirted Away", "Spirited Away")  # a typo fix, not another entity
    assert not other_name("Beyonce", "Beyoncé")


def test_michael_jordan_matched_to_the_actor_is_shown_to_the_group(monkeypatch):
    def search(p):
        return [{"entity_id": "MBJ", "name": "Michael B. Jordan", "types": ["urn:entity:person"]}]
    _live(monkeypatch, _graph(search))
    try:
        r = plan([{"label": "Cy", "likes": [{"name": "Michael Jordan", "type": "person"}]}], days=1)
    finally:
        qloo._cached_get.cache_clear()
    assert r["travelers"][0]["matched"] == ["Michael B. Jordan"]
    assert r["loose_matches"] == ["Cy: “Michael Jordan” → Michael B. Jordan"]
