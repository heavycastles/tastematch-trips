"""The stop explanation names the real strength of the Qloo affinity instead of always saying "High"."""
import re
from pathlib import Path

import pytest

from app.agent import affinity_band, plan

HTML = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize(("score", "word"), [(0.97, "Very high"), (0.85, "Very high"), (0.84, "High"), (0.70, "High"),
                                             (0.56, "Moderate"), (0.52, "Moderate"), (0.50, "Moderate"),
                                             (0.31, "Low"), (0.0, "Low")])
def test_band_follows_the_score(score, word):
    assert affinity_band(score) == word


def test_every_stop_explanation_uses_the_band_of_its_own_score():
    out = plan([{"label": "Aziz", "likes": [{"name": "Spirited Away", "type": "movie"}]},
                {"label": "Malika", "likes": [{"name": "Daft Punk", "type": "artist"}]}], days=2)
    assert out["itinerary"]
    for stop in out["itinerary"]:
        m = re.match(r"^(Very high|High|Moderate|Low) Qloo affinity \(([0-9.]+)\) with ", stop["why"])
        assert m, stop["why"]
        assert m.group(1) == affinity_band(stop["affinity"])


def test_page_keeps_the_band_word_when_it_hides_the_number():
    assert "/^(Very high|High|Moderate|Low) Qloo affinity \\([0-9.]+\\) with /,'$1 Qloo affinity with '" in HTML
