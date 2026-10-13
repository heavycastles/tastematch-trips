"""Qloo Taste AI client for the hackathon environment, with an offline mock.

Base URL https://hackathon.api.qloo.com, header X-Api-Key, GET /search and GET /v2/insights (query params).
Responses are cached in-process only (never written to the repo), per Qloo's data-handling rules.
"""

from __future__ import annotations

import os
from functools import lru_cache

import httpx

BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/")


class QlooError(RuntimeError):
    pass


def live() -> bool:
    return bool(os.getenv("QLOO_API_KEY"))


def _get(path: str, params: tuple) -> dict:
    return _cached_get(path, params, os.getenv("QLOO_API_KEY", ""))


@lru_cache(maxsize=512)
def _cached_get(path: str, params: tuple, key: str) -> dict:
    r = httpx.get(f"{BASE}{path}", params=list(params), headers={"X-Api-Key": key},
                  timeout=float(os.getenv("QLOO_TIMEOUT", "20")))
    if r.status_code >= 400:
        raise QlooError(f"Qloo {path} {r.status_code}: {r.text[:200]}")
    return r.json()


def search(query: str, etype: str | None = None, take: int = 1) -> list[dict]:
    if not live():
        return MOCK.search(query, etype, take)
    params = [("query", query), ("take", str(take))]
    if etype:
        params.append(("types", etype))
    data = _get("/search", tuple(params))
    return [{"id": e.get("entity_id") or e.get("id"), "name": e.get("name"),
             "type": etype or (e.get("types") or [""])[0]} for e in data.get("results", [])][:take]


def insights(filter_type: str, entity_ids: list[str], take: int = 10, location: str | None = None,
             tags: list[str] | None = None) -> list[dict]:
    if not live():
        return MOCK.insights(filter_type, entity_ids, take, location)
    params = [("filter.type", filter_type), ("take", str(take))]
    if entity_ids:
        params.append(("signal.interests.entities", ",".join(entity_ids)))
    if location:
        params.append(("filter.location.query", location))
    if tags:
        params.append(("filter.tags", ",".join(tags)))
    data = _get("/v2/insights", tuple(params))
    ents = (data.get("results") or {}).get("entities", [])
    out = []
    for e in ents:
        q = e.get("query") or {}
        props = e.get("properties") or {}
        out.append({"id": e.get("entity_id"), "name": e.get("name"),
                    "affinity": float(q.get("affinity", e.get("popularity", 0)) or 0),
                    "tags": [t.get("name") for t in (e.get("tags") or [])[:6] if isinstance(t, dict)],
                    "address": props.get("address"), "description": (props.get("description") or "")[:240]})
    return out


# ------------------------------------------------------------------------ mock
class _Mock:
    """Tiny deterministic taste graph so the app, tests and demo work without a key."""

    LIKES = {  # liked thing -> latent taste tags
        "studio ghibli": ["anime", "nature", "craft"], "spirited away": ["anime", "nature", "craft"],
        "anthony bourdain": ["street_food", "adventure"], "bourdain": ["street_food", "adventure"],
        "daft punk": ["nightlife", "electronic"], "the weeknd": ["nightlife", "rnb"],
        "wes anderson": ["design", "vintage"], "grand budapest hotel": ["design", "vintage"],
        "patagonia": ["nature", "adventure"], "aesop": ["design", "wellness"],
        "chef's table": ["fine_dining", "craft"], "taylor swift": ["pop", "shopping"],
        "zelda": ["nature", "anime"], "sopranos": ["street_food", "vintage"],
    }
    DESTINATIONS = {
        "Tokyo": ["anime", "nightlife", "design", "craft", "street_food", "electronic", "shopping"],
        "Kyoto": ["craft", "nature", "design", "wellness", "fine_dining"],
        "Lisbon": ["vintage", "street_food", "nightlife", "design"],
        "Samarkand": ["craft", "vintage", "street_food", "adventure"],
        "Berlin": ["electronic", "nightlife", "design", "vintage"],
        "Mexico City": ["street_food", "design", "fine_dining", "nightlife"],
        "Reykjavik": ["nature", "adventure", "wellness"],
        "Seoul": ["pop", "shopping", "nightlife", "street_food", "rnb"],
    }
    PLACES = {
        "street_food": "Night market", "craft": "Artisan workshop", "design": "Design museum",
        "nightlife": "Listening bar", "electronic": "Techno club", "nature": "Hillside trail",
        "anime": "Animation museum", "vintage": "Vintage arcade", "fine_dining": "Tasting-menu bistro",
        "wellness": "Bathhouse", "adventure": "Day-hike outfitter", "shopping": "Concept store",
        "pop": "Karaoke lounge", "rnb": "Jazz & soul bar",
    }

    def search(self, query, etype, take):
        k = query.strip().lower()
        if k not in self.LIKES:
            return []
        return [{"id": "mock:" + k.replace(" ", "_"), "name": query.strip(), "type": etype or "urn:entity:movie"}]

    def _tags(self, ids):
        out = []
        for i in ids:
            out += self.LIKES.get(i.removeprefix("mock:").replace("_", " "), [])
        return out

    def insights(self, ftype, ids, take, location):
        tags = self._tags(ids)
        if ftype == "urn:entity:destination":
            pool = self.DESTINATIONS.items()
        elif ftype == "urn:entity:place":
            pool = [(f"{v} · {location or ''}".strip(" ·"), [k]) for k, v in self.PLACES.items()]
        else:
            return []
        scored = []
        for name, dtags in pool:
            hits = sum(tags.count(t) for t in dtags)
            aff = round(min(0.99, 0.2 + 0.18 * hits), 3) if tags else 0.3
            scored.append({"id": "mock:" + name.lower().replace(" ", "_"), "name": name, "affinity": aff,
                           "tags": dtags[:6], "address": None, "description": ""})
        scored.sort(key=lambda e: (-e["affinity"], e["name"]))
        return scored[:take]


MOCK = _Mock()
