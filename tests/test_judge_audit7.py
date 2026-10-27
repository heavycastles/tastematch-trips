"""Seventh judge audit (final pre-submit run on fresh groups, Lisbon and a free-choice pair): a seafood restaurant
with a fish counter labelled "Fish store", a live music venue labelled "Video store", and a museum foundation
labelled "Foundation"."""
from app.agent import kind


def _p(*cats):
    return {"name": "Somewhere", "categories": list(cats)}


def test_a_shop_label_loses_to_what_the_place_is():
    assert kind(_p("restaurant", "fish_store", "seafood_restaurant")) == "Seafood restaurant"  # Mar ao Carmo, Lisbon
    assert kind(_p("video_store", "live_music_venue", "event_venue")) == "Live music venue"  # Launchpad, Albuquerque
    assert kind(_p("book_store", "cafe")) == "Cafe"


def test_shops_and_landmarks_keep_their_labels():
    assert kind(_p("book_store", "gift_shop")) == "Book store"
    assert kind(_p("clothing_store", "shoe_store")) == "Clothing store"
    assert kind(_p("book_store", "tourist_attraction", "historical_landmark", "museum")) == "Historical landmark"
    assert kind(_p("restaurant", "tapas_bar", "pub")) == "Tapas bar"


def test_a_foundation_reads_as_what_it_runs():
    assert kind(_p("foundation", "museum")) == "Museum"
    assert kind(_p("foundation")) == "Foundation"  # nothing better to say
