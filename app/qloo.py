"""Qloo Taste AI client for the hackathon environment, with an offline mock.

Base URL https://hackathon.api.qloo.com, header X-Api-Key, GET /search and GET /v2/insights (query params).
Responses are cached in-process only (never written to the repo), per Qloo's data-handling rules.
"""

from __future__ import annotations

import os
import time
from functools import lru_cache
from pathlib import Path

import httpx

_ENV_LOADED = False


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader (no python-dotenv dep). Does not override existing env vars."""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    p = path or Path(__file__).resolve().parent.parent / ".env"
    if p.is_file():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    _ENV_LOADED = True


BASE = os.getenv("QLOO_BASE_URL", "https://hackathon.api.qloo.com").rstrip("/")


def base_url() -> str:
    """Read QLOO_BASE_URL at call time, so env vars set after import (or by the host) are respected."""
    return (os.getenv("QLOO_BASE_URL") or BASE).rstrip("/")


class QlooError(RuntimeError):
    """Upstream failure. ``kind`` is one of rate_limited, qloo_timeout, bad_location, upstream."""

    def __init__(self, message: str, kind: str = "upstream", status: int = 0):
        super().__init__(message)
        self.kind, self.status = kind, status


def live() -> bool:
    return bool(os.getenv("QLOO_API_KEY")) and not os.getenv("QLOO_FORCE_MOCK")


def _get(path: str, params: tuple) -> dict:
    return _cached_get(path, params, os.getenv("QLOO_API_KEY", ""))


@lru_cache(maxsize=512)
def _cached_get(path: str, params: tuple, key: str) -> dict:
    timeout = float(os.getenv("QLOO_TIMEOUT", "20"))
    budget = float(os.getenv("QLOO_RETRY_BUDGET", "12"))  # max seconds spent backing off on 429s
    slept, attempt = 0.0, 0
    while True:
        try:
            r = httpx.get(f"{base_url()}{path}", params=list(params), headers={"X-Api-Key": key}, timeout=timeout)
        except httpx.TimeoutException as e:
            raise QlooError(f"Qloo {path} timed out after {timeout:.0f}s", "qloo_timeout") from e
        except httpx.HTTPError as e:
            raise QlooError(f"Qloo {path} unreachable: {type(e).__name__}", "upstream") from e
        if r.status_code == 429:
            try:
                wait = float(r.headers.get("retry-after", ""))
            except ValueError:
                wait = 0.8 * (2**attempt)
            wait = min(wait, budget - slept)
            if wait <= 0:
                raise QlooError(f"Qloo {path} 429: {r.text[:200] or 'Rate limit exceeded'}", "rate_limited", 429)
            time.sleep(wait)
            slept += wait
            attempt += 1
            continue
        if r.status_code >= 400:
            kind = "bad_location" if r.status_code == 400 and "location" in r.text else "upstream"
            raise QlooError(f"Qloo {path} {r.status_code}: {r.text[:200]}", kind, r.status_code)
        try:
            return r.json()
        except ValueError as e:  # an HTML error page or truncated body instead of JSON
            raise QlooError(f"Qloo {path} returned non-JSON ({r.status_code})", "upstream", r.status_code) from e


def _affinity(entity: dict) -> float:
    q = entity.get("query") or {}
    for key in ("affinity", "rank", "score"):
        if q.get(key) is not None:
            try:
                return float(q[key])
            except (TypeError, ValueError):
                pass
    for key in ("affinity", "score", "popularity"):
        if entity.get(key) is not None:
            try:
                return float(entity[key])
            except (TypeError, ValueError):
                pass
    return 0.0


# Tag families that read as noise on a stop card ("18 24", "Nfc mobile payments", "Free parking lot",
# an "Afternoon" chip on an evening stop) -- kept out of the displayed chips.
_HIDDEN_TAG_FAMILIES = {
    "age_range", "payments", "parking", "accessibility", "not_for_display", "place_page_attributes",
    "pets", "planning", "service_options", "service_type", "time_of_day_fit", "noise_level", "room_type",
    "credit_card", "collection", "sustainability_initiative",
}


def _tag_family(tag_id: str) -> str:
    parts = tag_id.split(":")  # urn:tag:<family>:<source>:<slug>
    return parts[2] if len(parts) > 3 and parts[0] == "urn" and parts[1] == "tag" else ""


def _tag_names(entity: dict) -> list[str]:
    out = []
    for t in entity.get("tags") or []:
        if isinstance(t, dict) and t.get("name"):
            if _tag_family(str(t.get("tag_id") or t.get("type") or t.get("id") or "")) in _HIDDEN_TAG_FAMILIES:
                continue
            out.append(t["name"])
        elif isinstance(t, str):
            out.append(t)
    return out[:6]


def _categories(entity: dict) -> list[str]:
    """Venue categories Qloo attaches as urn:tag:category:place:<slug> (e.g. hotel, seafood_restaurant, museum)."""
    out = []
    for t in entity.get("tags") or []:
        tid = t.get("id") if isinstance(t, dict) else None
        if isinstance(tid, str) and tid.startswith("urn:tag:category:place:"):
            out.append(tid.rsplit(":", 1)[-1])
    return out


CITY_STATES = {"HK", "MO", "SG", "MC", "VA", "SM", "LU", "MT", "AD", "LI", "BH"}


def _destination_label(entity: dict) -> str:
    """Disambiguate destinations (e.g. Portland, Maine) using geocode when present."""
    name = (entity.get("name") or "").strip() or "Unknown"
    geo = (entity.get("properties") or {}).get("geocode") or {}
    region = (geo.get("admin1_region") or "").strip()
    country = (geo.get("country_code") or "").strip()
    if country.upper() in CITY_STATES:
        return name  # "Hong Kong, Central and Western" / "Singapore, SG" read as noise
    if region and region.lower() not in name.lower() and region.lower()[:4] != name.lower()[:4]:
        return f"{name}, {region}"
    if country and country.upper() not in name.upper() and not region:
        return f"{name}, {country}"
    return name


def _location_query(entity: dict) -> str:
    """Best string for filter.location.query.

    Prefer the destination's own name plus admin1 region (e.g. "Santa Fe, New Mexico",
    "Sayulita, Nayarit"). Using geocode.name alone is unreliable — it can be a nearby
    village ("Lo de Marcos") that Qloo resolves to the wrong metro.
    """
    name = (entity.get("name") or "").strip()
    geo = (entity.get("properties") or {}).get("geocode") or {}
    region = (geo.get("admin1_region") or "").strip()
    if name and region and region.lower() not in name.lower():
        return f"{name}, {region}"
    if name:
        return name
    return (geo.get("name") or geo.get("city") or geo.get("metro") or "").strip()


def _image_url(entity: dict) -> str | None:
    """First https image URL Qloo returns (properties.image.url or properties.images[0].url)."""
    props = entity.get("properties") or {}
    candidates = [props.get("image")] + list(props.get("images") or [])
    for c in candidates:
        url = c.get("url") if isinstance(c, dict) else c
        if isinstance(url, str) and url.startswith("https://"):
            return url
    return None


def _coords(entity: dict) -> tuple[float | None, float | None]:
    loc = entity.get("location") or {}
    try:
        return float(loc["lat"]), float(loc["lon"])
    except (KeyError, TypeError, ValueError):
        return None, None


def _parse_entity(entity: dict, *, as_destination: bool = False) -> dict:
    props = entity.get("properties") or {}
    name = _destination_label(entity) if as_destination else (entity.get("name") or "")
    lat, lon = _coords(entity)
    return {
        "id": entity.get("entity_id") or entity.get("id"),
        "name": name,
        "affinity": _affinity(entity),
        "tags": _tag_names(entity),
        "categories": _categories(entity),
        "address": props.get("address"),
        "description": (props.get("description") or props.get("short_description") or "")[:240],
        "location_query": _location_query(entity) if as_destination else None,
        "popularity": float(entity.get("popularity") or 0) if entity.get("popularity") is not None else None,
        "image": _image_url(entity),
        "lat": lat,
        "lon": lon,
    }


def search(query: str, etype: str | None = None, take: int = 1) -> list[dict]:
    if not live():
        return MOCK.search(query, etype, take)
    params = [("query", query), ("take", str(take))]
    if etype:
        params.append(("types", etype))
    data = _get("/search", tuple(params))
    results = data.get("results") or []
    if isinstance(results, dict):
        results = results.get("entities") or []
    out = []
    for e in results[:take]:
        types = e.get("types") or []
        out.append({
            "id": e.get("entity_id") or e.get("id"),
            "name": e.get("name"),
            "type": etype or (types[0] if types else ""),
            "image": _image_url(e),
        })
    return out


def insights(
    filter_type: str,
    entity_ids: list[str],
    take: int = 10,
    location: str | None = None,
    tags: list[str] | None = None,
    popularity_min: float | None = None,
    filter_entities: list[str] | None = None,
) -> list[dict]:
    if not live():
        return MOCK.insights(filter_type, entity_ids, take, location, filter_entities=filter_entities)
    params: list[tuple[str, str]] = [("filter.type", filter_type), ("take", str(take))]
    if entity_ids:
        params.append(("signal.interests.entities", ",".join(entity_ids)))
    if location:
        params.append(("filter.location.query", location))
    if tags:
        params.append(("filter.tags", ",".join(tags)))
    if popularity_min is not None:
        params.append(("filter.popularity.min", str(popularity_min)))
    if filter_entities:
        # Score affinity of these specific entities toward the signal (docs: filter.entities /
        # filter.results.entities). Hackathon accepts filter.entities.
        params.append(("filter.entities", ",".join(filter_entities)))
        params = [(k, v) for k, v in params if k != "take"]  # take ignored when filtering to IDs
        params.append(("take", str(max(take, len(filter_entities)))))
    data = _get("/v2/insights", tuple(params))
    results = data.get("results") or {}
    ents = results.get("entities", []) if isinstance(results, dict) else results
    as_dest = filter_type == "urn:entity:destination"
    return [_parse_entity(e, as_destination=as_dest) for e in ents]


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
    CATEGORY = {  # mock venue -> Qloo-style place category slug
        "street_food": "night_market", "craft": "art_studio", "design": "museum", "nightlife": "bar",
        "electronic": "night_club", "nature": "hiking_area", "anime": "museum", "vintage": "amusement_center",
        "fine_dining": "fine_dining_restaurant", "wellness": "spa", "adventure": "tour_agency",
        "shopping": "store", "pop": "karaoke_bar", "rnb": "jazz_club",
    }

    def search(self, query, etype, take):
        k = query.strip().lower()
        if etype == "urn:entity:destination":
            hit = next((d for d in self.DESTINATIONS if d.lower() == k.split(",")[0].strip()), None)
            if not hit:
                return []
            return [{"id": "mock:" + hit.lower().replace(" ", "_"), "name": hit, "type": etype, "image": None}]
        if k not in self.LIKES:
            return []
        return [{"id": "mock:" + k.replace(" ", "_"), "name": query.strip(), "type": etype or "urn:entity:movie",
                 "image": None}]

    def _tags(self, ids):
        out = []
        for i in ids:
            out += self.LIKES.get(i.removeprefix("mock:").replace("_", " "), [])
        return out

    def insights(self, ftype, ids, take, location, filter_entities=None):
        tags = self._tags(ids)
        if ftype == "urn:entity:destination":
            pool = self.DESTINATIONS.items()
        elif ftype == "urn:entity:place":
            pool = [(f"{v} · {location or ''}".strip(" ·"), [k]) for k, v in self.PLACES.items()]
        else:
            return []
        scored = []
        for name, dtags in pool:
            eid = "mock:" + name.lower().replace(" ", "_")
            if filter_entities and eid not in filter_entities and name not in filter_entities:
                continue
            hits = sum(tags.count(t) for t in dtags)
            aff = round(min(0.99, 0.2 + 0.18 * hits), 3) if tags else 0.3
            scored.append({
                "id": eid,
                "name": name,
                "affinity": aff,
                "tags": dtags[:6],
                "categories": [self.CATEGORY[dtags[0]]] if ftype == "urn:entity:place" else [],
                "address": None,
                "description": "",
                "location_query": name if ftype == "urn:entity:destination" else None,
                "popularity": None,
                "image": None,
                "lat": None,
                "lon": None,
            })
        scored.sort(key=lambda e: (-e["affinity"], e["name"]))
        return scored[:take]


MOCK = _Mock()
