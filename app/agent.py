"""TasteMatch Trips: a fairness-aware group-travel agent on Qloo.

Tools (all Qloo): resolve_entity (/search) -> destination_affinity (/v2/insights destination) per traveler and
for the group -> local_places (/v2/insights place + filter.location.query). The planner ranks destinations by a
fairness score (no one is left out), then builds an itinerary where every traveler gets their own picks, and
explains each pick with the Qloo signal it came from. Every candidate stop is also scored for every traveler
(cross_score_places), so the agent can pick group-friendly stops, check how much each person will enjoy the whole
trip, and re-plan once if the gap is too wide. An optional LLM writes the narrative.
"""

from __future__ import annotations

import contextvars
import itertools
import math
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import httpx

from . import qloo

TYPES = {"movie", "artist", "brand", "book", "tv_show", "video_game", "podcast", "person", "place"}
# UI type name -> Qloo entity URN where they differ (Qloo spells it "videogame")
URN = {"video_game": "urn:entity:videogame"}


@dataclass
class Trace:
    steps: list[dict] = field(default_factory=list)

    def add(self, tool: str, **kw):
        self.steps.append({"tool": tool, **kw})


PARALLEL = 6  # independent per-traveler Qloo calls run side by side (a 4-person Tokyo plan: ~30 s -> ~10 s)


def _pmap(fn, items: list) -> list:
    """fn over items, concurrently on the live API; results (and the first error) in input order, so the trace and
    the plan are identical to a sequential run. Each task runs in a copy of the request context (shared deadline and
    call counter)."""
    if len(items) < 2 or not qloo.live():
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(PARALLEL, len(items))) as ex:
        futs = [ex.submit(contextvars.copy_context().run, fn, x) for x in items]
        return [f.result() for f in futs]


TASTE_URNS = {URN.get(t, f"urn:entity:{t}") for t in TYPES if t != "place"}


def _plain(s: str) -> str:
    """'Amélie' -> 'amelie', "Chef's Table" -> 'chef s table' (accents, case and punctuation ignored)."""
    s = "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w]+", " ", s.casefold()).split())


def name_fit(query: str, matched: str) -> float:
    """How well Qloo's match reads as what the traveler typed: 1.0 same name, 0.9 one name contains the other
    ("Amélie" in "Le Fabuleux Destin d'Amélie Poulain"), else a fuzzy ratio ("Spirted Away" ~0.96)."""
    a, b = _plain(query), _plain(matched)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if f" {a} " in f" {b} " or f" {b} " in f" {a} ":
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def other_name(query: str, matched: str) -> bool:
    """Qloo returned a different, similarly named entity: every typed word is in the match, but with extra words
    wedged in ("Michael Jordan" -> "Michael B. Jordan", an actor). Containment ("Amélie" in the full French title)
    and exact names are not flagged."""
    a, b = _plain(query).split(), _plain(matched).split()
    if not a or len(b) <= len(a) or f" {' '.join(a)} " in f" {' '.join(b)} ":
        return False
    it = iter(b)
    return all(w in it for w in a)


LOOSE = 0.6  # below this the typed-search hit is probably the wrong thing ("Studio Ghibli" as a brand -> a photo app)


def _latin(s: str) -> bool:
    return bool(re.search(r"[a-z]", _plain(s)))


def _search(name: str, etype: str) -> list[dict]:
    try:
        return qloo.search(name, URN.get(etype, f"urn:entity:{etype}"), 1)
    except qloo.QlooError as e:  # Qloo rejected this one query (e.g. odd input): skip it, keep the plan
        if not 400 <= e.status < 500 or e.status == 429:
            raise
        return []


def _any_type(name: str) -> dict | None:
    """The traveler may have picked the wrong type (Studio Ghibli is an artist in Qloo, not a brand): look the name
    up across all taste types and keep a hit only if it really is that name."""
    try:
        hits = qloo.search(name, None, 5)
    except qloo.QlooError as e:
        if not 400 <= e.status < 500 or e.status == 429:
            raise
        return None
    hits = [h for h in hits if h.get("type") in TASTE_URNS and h.get("id")]
    best = max(hits, key=lambda h: name_fit(name, h.get("name") or ""), default=None)
    return best if best and name_fit(name, best.get("name") or "") >= 0.85 else None


def _lookup(like: dict) -> tuple[str, list[dict], float, str | None]:
    etype = like.get("type", "movie")
    etype = etype if etype in TYPES else "movie"
    hits = _search(like["name"], etype)
    fit = name_fit(like["name"], hits[0].get("name") or "") if hits else 0.0
    retyped = None
    if fit < LOOSE and _latin(like["name"]):
        alt = _any_type(like["name"])
        if alt and name_fit(like["name"], alt["name"]) > fit:
            hits, retyped = [alt], alt["type"].rsplit(":", 1)[-1]
            fit = name_fit(like["name"], alt["name"])
    return etype, hits, fit, retyped


def resolve(travelers: list[dict], tr: Trace) -> tuple[list[dict], list[str]]:
    unresolved = []
    likes = [like for t in travelers for like in t.get("likes", [])]
    found = iter(_pmap(_lookup, likes))  # all /search lookups at once, then processed in the order typed
    for t in travelers:
        t["entities"] = []
        for like in t.get("likes", []):
            etype, hits, fit, retyped = next(found)
            tr.add("resolve_entity", endpoint="/search", query=like["name"], type=etype, found=bool(hits),
                   matched=hits[0]["name"] if hits else None, **({"retyped": retyped} if retyped else {}))
            if hits:
                ent = dict(hits[0])
                if ent.get("id") and any(e.get("id") == ent["id"] for e in t["entities"]):
                    tr.steps[-1]["duplicate"] = True  # "Spirited Away" typed twice: one taste signal, not two
                    continue
                if _latin(like["name"]) and (fit < 0.5 or other_name(like["name"], ent.get("name") or "")):
                    ent["loose"] = like["name"]  # e.g. a translated title; shown to the group so they can check it
                t["entities"].append(ent)
            else:
                unresolved.append(f"{t['label']}: {like['name']}")
    return travelers, unresolved


TIE = 0.0005  # affinities closer than this round to the same score: a tie, not a least-matched traveler


def fairness(per_traveler: dict[str, dict[str, float]], group: list[dict]) -> list[dict]:
    names = {e["name"] for e in group} | {n for d in per_traveler.values() for n in d}
    gaff = {e["name"]: e["affinity"] for e in group}
    out = []
    for n in names:
        scores = {lbl: d.get(n, 0.0) for lbl, d in per_traveler.items()}
        vals = list(scores.values()) or [0.0]
        mean, low = sum(vals) / len(vals), min(vals)
        fit = round(100 * (0.4 * mean + 0.4 * low + 0.2 * gaff.get(n, mean)), 1)
        # Nobody is "least matched" when everyone scores the city the same (two travelers who both typed Inception)
        least = min(scores, key=scores.get) if scores and max(vals) - low >= TIE else None
        out.append({"name": n, "group_fit": fit, "per_traveler": scores, "least_happy": least})
    out.sort(key=lambda d: (-d["group_fit"], d["name"]))
    return out


class _Pool(list):
    skipped = 0
    far = 0


FAR_KM = 100  # a city trip shouldn't send the group to a venue hours away (e.g. Niagara Falls in a NYC plan)


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(min(1.0, math.sqrt(h)))


def _near(places: list[dict]) -> tuple[list[dict], int]:
    """Drop venues far from where most of the candidates are (median of their coordinates)."""
    pts = [(p["lat"], p["lon"]) for p in places if p.get("lat") is not None and p.get("lon") is not None]
    if len(pts) < 3:
        return places, 0
    mid = (sorted(x for x, _ in pts)[len(pts) // 2], sorted(y for _, y in pts)[len(pts) // 2])
    keep = [p for p in places if p.get("lat") is None or p.get("lon") is None
            or _km(mid, (p["lat"], p["lon"])) <= FAR_KM]
    return keep, len(places) - len(keep)


CHAINS = re.compile(r"\b(starbucks|mcdonald'?s|kfc|subway|burger king|domino'?s|pizza hut|dunkin'?|costa coffee|"
                    r"tim hortons|7-eleven|bubba gump|taco bell|wendy'?s|popeyes|chipotle|papa john'?s|"
                    r"carl'?s jr|five guys|krispy kreme)\b", re.I)


def _stops(places: list[dict], size: int | None = None) -> list[dict]:
    """Keep the traveler's top visitable venues (Qloo order = affinity order); hotels, errands and venues far
    outside the city are dropped, global chains (a Starbucks in Kyoto) only fill in if nothing else is left. If a
    small town has nothing but hotels, fall back to what Qloo returned rather than an empty day."""
    keep = [p for p in places if visitable(p)]
    keep = [p for p in keep if not CHAINS.search(p.get("name") or "")] + \
        [p for p in keep if CHAINS.search(p.get("name") or "")]
    near, far = _near(keep)
    pool = _Pool((near or places)[:size or POOL_SIZE])
    pool.skipped = len(places) - len(keep) if keep else 0
    pool.far = far if near else 0
    return pool


SAME_CITY_KM = 15  # Qloo lists some cities twice ("Oaxaca" / "Oaxaca City" 0.03 km apart); Kyoto-Nara is 35 km


def dedupe_cities(ranking: list[dict], coords: dict, chosen_at: tuple | None = None) -> tuple[list[dict], int]:
    """Keep the best-ranked entry of each city: drop a destination within SAME_CITY_KM of a higher-ranked one
    (or of the group's own pick). Entries without coordinates are always kept."""
    kept, seen = [], [chosen_at] if chosen_at else []
    for r in ranking:
        here = coords.get(r["name"])
        if here and any(_km(here, p) <= SAME_CITY_KM for p in seen):
            continue
        kept.append(r)
        if here:
            seen.append(here)
    return kept, len(ranking) - len(kept)


def plan(travelers: list[dict], days: int = 2, destination: str | None = None) -> dict:
    t0 = time.perf_counter()
    qloo.start_request()
    tr = Trace()
    travelers, unresolved = resolve([dict(t) for t in travelers], tr)
    # A favourite two travelers share is one signal for the group query (each traveler is still scored on it).
    all_ids = list(dict.fromkeys(e["id"] for t in travelers for e in t["entities"]))
    if not all_ids:
        return {"error": "none_resolved", "unresolved": unresolved,
                "ask": "I couldn't match any of those tastes in Qloo. Try a well-known movie, artist or brand."}

    chosen_id, shown = None, None
    if destination:
        hit = qloo.search(destination, "urn:entity:destination", 1)
        tr.add("resolve_destination", endpoint="/search", query=destination, type="destination", found=bool(hit))
        if not hit:
            hint = ("Qloo knows cities by their English names (Moscow, not Москва). " if not _latin(destination)
                    else "")
            return {"error": "destination_not_found", "unresolved": unresolved,
                    "ask": f"Qloo doesn't know \"{destination}\" as a destination. {hint}Try a city name such as "
                           "Lisbon or Tokyo, or leave the field empty and let the agent pick."}
        chosen_id = hit[0]["id"]
        shown = hit[0].get("name") or destination.strip()  # Qloo's spelling: "lisbon" -> "Lisbon"

    # Prefer well-known destinations on the live API (hackathon graph skews to tiny towns otherwise).
    dest_kw = {"popularity_min": 0.55} if qloo.live() else {}
    group = qloo.insights("urn:entity:destination", all_ids, 15, **dest_kw)
    tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler="group",
           signals=len(all_ids), results=len(group))
    group_step = tr.steps[-1]
    loc_by_name: dict[str, str] = {}
    for e in group:
        if e.get("location_query"):
            loc_by_name[e["name"]] = e["location_query"]
    candidate_ids = [e["id"] for e in group if e.get("id")]
    if chosen_id and chosen_id not in candidate_ids:
        candidate_ids.append(chosen_id)
    name_by_id = {e["id"]: e["name"] for e in group if e.get("id")}
    coords = {e["name"]: (e["lat"], e["lon"]) for e in group if e.get("lat") is not None and e.get("lon") is not None}

    # Score the SAME candidate set per traveler via filter.entities (true affinities, not top-N overlap).
    per: dict[str, dict[str, float]] = {}
    scored_travelers = [t for t in travelers if t["entities"]]  # nothing resolved: don't drag every city to zero
    filtered = bool(candidate_ids and qloo.live())

    def score_cities(t):
        ids = [e["id"] for e in t["entities"]]
        if filtered:  # candidates already popularity-filtered; score them raw for each traveler
            return qloo.insights("urn:entity:destination", ids, max(15, len(candidate_ids)),
                                 filter_entities=candidate_ids)
        return qloo.insights("urn:entity:destination", ids, 15, **dest_kw)

    for t, res in zip(scored_travelers, _pmap(score_cities, scored_travelers), strict=True):
        tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler=t["label"],
               signals=len(t["entities"]), results=len(res), filtered=filtered)
        per[t["label"]] = {e["name"]: e["affinity"] for e in res}
        for e in res:
            if e.get("id"):
                name_by_id.setdefault(e["id"], e["name"])
            if e.get("location_query"):
                loc_by_name[e["name"]] = e["location_query"]
            if e.get("lat") is not None and e.get("lon") is not None:
                coords.setdefault(e["name"], (e["lat"], e["lon"]))
    ranking = fairness(per, group)
    chosen = None
    if chosen_id:
        cname = name_by_id.get(chosen_id)
        chosen = next((dict(r) for r in ranking if r["name"] == cname), None)
        scored = chosen is not None and any(chosen["per_traveler"].values())
        if not scored:  # Qloo has no affinity for this city at all: say so instead of showing a fake 0.0
            chosen = {"name": shown, "group_fit": None, "least_happy": None,
                      "per_traveler": {t["label"]: None for t in travelers if t["entities"]}}
        chosen["name"] = shown
        chosen["chosen"] = True
        chosen["scored"] = scored
        ranking = [r for r in ranking if r["name"] != cname]
    ranking, merged = dedupe_cities(ranking, coords, coords.get(name_by_id.get(chosen_id, "")) if chosen_id else None)
    if merged:  # "Mexico City" and "Distrito Federal, Mexico City" are one trip, not two options
        group_step["merged"] = merged
    if not ranking and not chosen:  # Qloo answered, but with no destinations for these tastes
        return {"error": "no_destinations", "unresolved": unresolved,
                "ask": "Qloo didn't return any destinations for these tastes. Add a more widely known favourite, "
                       "or type a city in the Destination field."}
    city = shown or (ranking[0]["name"] if ranking else None)
    # Places need a location query string; prefer geocode city over neighborhood labels.
    place_location = destination or (loc_by_name.get(city) if city else None) or city

    pools: dict[str, list[dict]] = {}
    # A solo traveler on a 5-day trip needs 15 own stops, not the default 8.
    tasters = max(1, sum(1 for t in travelers if t["entities"]))
    size = max(POOL_SIZE, math.ceil(3 * max(1, min(days, 5)) / tasters) + 2)
    def fetch_pool(t, where):
        ids = [e["id"] for e in t["entities"]]
        return _stops(qloo.insights("urn:entity:place", ids, PLACE_TAKE, location=where), size) if ids and where else []

    try:
        got = _pmap(lambda t: fetch_pool(t, place_location), travelers)
    except qloo.QlooError as e:
        if e.kind != "bad_location":
            raise
        alt = loc_by_name.get(name_by_id.get(chosen_id, "")) if chosen_id else None
        if not alt or alt == place_location:
            return {"error": "destination_not_found", "unresolved": unresolved,
                    "ask": f"Qloo has no local venue data for \"{place_location}\". Try a nearby larger city, "
                           "or leave the destination empty."}
        place_location = alt
        got = _pmap(lambda t: fetch_pool(t, place_location), travelers)
    for t, pool in zip(travelers, got, strict=True):
        pools[t["label"]] = pool
        tr.add("local_places", endpoint="/v2/insights", filter_type="place", traveler=t["label"],
               location=place_location, results=len(pool),
               skipped=getattr(pool, "skipped", 0), far=getattr(pool, "far", 0))

    # Venue-level fairness: score EVERY candidate stop for EVERY traveler (same filter.entities trick as for
    # cities), so the agent knows not only who a stop is for, but how much the rest of the group will enjoy it.
    union = list(dict.fromkeys(p["id"] for pool in pools.values() for p in pool if p.get("id")))
    matrix: dict[str, dict[str, float]] = {}
    if union and len(travelers) > 1:
        def cross(t):
            ids = [e["id"] for e in t["entities"]]
            if not ids:
                return None
            try:
                return qloo.insights("urn:entity:place", ids, len(union), location=place_location,
                                     filter_entities=union)
            except qloo.QlooError as e:
                if e.kind == "rate_limited":
                    raise
                return []

        for t, res in zip(travelers, _pmap(cross, travelers), strict=True):
            if res is None:
                matrix[t["label"]] = {}
                continue
            matrix[t["label"]] = {p["id"]: p["affinity"] for p in res if p.get("id")}
            tr.add("cross_score_places", endpoint="/v2/insights", filter_type="place", traveler=t["label"],
                   location=place_location, candidates=len(union), results=len(res))
    for t in travelers:  # a traveler's own pool score always counts for them
        own = matrix.setdefault(t["label"], {})
        for p in pools.get(t["label"], []):
            if p.get("id"):
                own.setdefault(p["id"], p["affinity"])

    labels = [t["label"] for t in travelers if t["entities"]]
    likes_of = {t["label"]: ", ".join(e["name"] for e in t["entities"]) for t in travelers}
    dest_score = (chosen if chosen else (ranking[0] if ranking else {})).get("per_traveler", {})
    if chosen and not chosen["scored"]:
        dest_score = {}
    itinerary, check, decisions = build_itinerary(labels, pools, matrix, likes_of, days, dest_score)
    fair = {lbl: sum(1 for x in itinerary if x["for"] == lbl) for lbl in labels}
    result = {"destination": city, "days": max(1, min(days, 5)),
              "mode": "chosen" if chosen else "best_match", "chosen": chosen,
              "ranking": ranking[:6], "itinerary": itinerary, "fair_share": fair,
              "unresolved": unresolved, "trace": tr.steps,
              "unmatched_travelers": [t["label"] for t in travelers if not t["entities"]],
              "loose_matches": [f"{t['label']}: “{e['loose']}” → {e['name']}" for t in travelers
                                for e in t["entities"] if e.get("loose")],
              "fairness_check": check, "decisions": decisions,
              "travelers": [{"label": t["label"], "matched": [e["name"] for e in t["entities"]],
                             "matched_detail": [{"name": e["name"], "type": (e.get("type") or "").rsplit(":", 1)[-1],
                                                 "image": e.get("image")} for e in t["entities"]]}
                            for t in travelers],
              "source": "qloo-hackathon-api" if qloo.live() else "mock",
              "note": "Qloo results are aggregate taste affinities, not predictions about any individual."}
    result["narrative"] = narrate(result)
    fresh = qloo.fresh_calls() if qloo.live() else len(tr.steps)
    result["stats"] = {"qloo_calls": len(tr.steps), "elapsed_ms": int((time.perf_counter() - t0) * 1000),
                       # identical Qloo requests are cached in-process, so a repeat plan answers instantly
                       "cached": max(0, len(tr.steps) - max(0, fresh))}
    return result


SLOTS = ("morning", "afternoon", "evening")
PLACE_TAKE = 40  # Qloo's place results skew heavily to hotels; fetch a wider list, keep the visitable ones
POOL_SIZE = 8

# Somewhere you sleep or a local errand is not a trip stop (Qloo's place graph includes both).
NOT_A_STOP = ("hotel", "motel", "hostel", "lodging", "accommodation", "guest_house", "bed_and_breakfast", "inn",
              "villa", "cottage", "chalet", "apartment", "condominium", "housing", "residential", "real_estate",
              "campground", "rv_park", "pet_", "veterinar", "dentist", "doctor", "clinic", "hospital", "pharmacy",
              "bank", "atm", "insurance", "lawyer", "attorney", "accountant", "car_", "auto_", "gas_station",
              "storage", "laundry", "dry_clean", "plumber", "electrician", "contractor", "locksmith",
              "corporate_office", "school", "post_office", "government", "funeral", "cemetery", "parking",
              "psychotherapist", "psychologist", "counselor", "therapist", "make_up_artist", "beauty_salon",
              "hair_salon", "nail_salon", "barber", "subway_station", "train_station", "bus_station",
              "transit_station", "talent_agency", "consultant", "production_company", "record_company",
              "media_company", "publisher", "agency", "recording_studio",
              # errand shops ("Frame Dubai - Picture Framing Shop", next to a garden centre): not a trip stop
              "picture_frame", "framing", "print_shop", "printing", "copy_shop", "hardware_store",
              "home_improvement", "appliance", "mobile_phone", "cell_phone", "repair", "courier", "shipping",
              "moving_company", "key_duplication",
              # studios selling services, not visits (LA's "The Futur", a design course company)
              "website_designer", "web_design", "graphic_designer", "interior_designer", "software", "advertising",
              "marketing", "it_services", "computer_")
# Not a sight on its own (campus, gym, wedding hall, tattoo parlour) unless Qloo also tags it as an attraction.
SOFT_NOT_A_STOP = ("university", "college", "gym", "fitness", "wedding", "tattoo", "coworking", "event_planner",
                   "entertainer", "building",  # "building": an office block or a bare street address
                   # trade and B2B listings ("Electrical appliance wholesaler", "Port operating company", a marina
                   # tagged "marine engineer, yacht broker"); a museum run by a company still counts via SIGHT
                   "wholesaler", "supplier", "manufacturer", "distributor", "company", "engineer", "broker")
SIGHT = ("tourist_attraction", "historical_landmark", "museum", "cultural_landmark", "landmark", "historic",
         "observation_deck", "scenic_spot")
LODGING_WORDS = re.compile(r"\b(hotel|resort|residences|suites|hostel|motel|condo\w*|apartments?|villas?|"
                           r"boarding|vacation rental)\b", re.I)


def _cat_hit(cat: str) -> bool:
    return any(cat == k or cat.startswith(k) or cat.endswith("_" + k) for k in NOT_A_STOP)


def visitable(p: dict) -> bool:
    """True if a Qloo place is somewhere a group would actually go during the day (not a hotel, condo, pet shop,
    bank...). Uses Qloo's urn:tag:category:place tags; uncategorised venues fall back to a description check."""
    cats = p.get("categories") or []
    if cats:
        if any(_cat_hit(c) for c in cats):
            return False
        soft = any(_has([c], SOFT_NOT_A_STOP) for c in cats)
        return not soft or any(_has([c], SIGHT) for c in cats)
    return not LODGING_WORDS.search(f"{p.get('name') or ''} {p.get('description') or ''}")


SHOP_LABELS = ("store", "shop", "boutique")
ORG_LABELS = ("organization", "company", "corporate_office", "engineer", "broker", "wholesaler", "supplier")


def kind(p: dict) -> str | None:
    """Human label for the venue type, e.g. 'Seafood restaurant' (most specific Qloo category first)."""
    cats = [c for c in (p.get("categories") or []) if c not in ("place", "food_and_drink")]
    if not cats:
        return None
    specific = [c for c in cats if c != "restaurant"] or cats
    # "Non profit organization" says who runs it, not what it is: a museum run by a non-profit reads as "Museum"
    specific.sort(key=lambda c: _has([c], ORG_LABELS))
    # A landmark house with a gift shop reads as what it is ("Historical landmark", not "Book store")
    sights = [c for c in specific if _has([c], SIGHT)]
    if sights and _has([specific[0]], SHOP_LABELS):
        specific = [c for c in sights if c != "tourist_attraction"] or sights
    return specific[0].replace("_", " ").capitalize()


EVENING = ("bar", "pub", "night_club", "club", "lounge", "fine_dining", "steak_house", "restaurant", "brewery",
           "winery", "theater", "jazz", "karaoke", "cocktail", "izakaya", "music_venue", "concert", "stadium", "arena",
           "haunted_house")  # haunted houses / horror bars (Qloo's Tokyo "Trick or Treat") are an after-dark outing
MORNING = ("breakfast", "cafe", "coffee", "bakery", "brunch", "market", "museum", "gallery", "park", "garden",
           "hiking", "trail", "beach", "tour", "temple", "church", "attraction", "landmark", "spa", "studio",
           "store", "shop", "boutique", "mall", "scenic_spot", "zoo", "aquarium", "water_park", "amusement_park",
           "natural_feature", "monument", "observation_deck", "tower", "fortress", "viewpoint")


def _has(cats: list[str], keys: tuple[str, ...]) -> bool:
    """Whole-word match on category slugs ('spa' matches 'day_spa', not 'spanish_restaurant')."""
    for c in cats:
        toks = c.split("_")
        if any(k == c or k in toks or ("_" in k and k in c) for k in keys):
            return True
    return False


NIGHT = ("bar", "pub", "night_club", "club", "lounge", "cocktail", "karaoke", "jazz", "hookah", "brewery")
DAYTIME_FOOD = ("breakfast", "cafe", "coffee", "bakery", "brunch")


def _slot_fit(stop: dict, slot: str) -> int:
    cats = stop.get("categories") or []
    if not cats:
        return 0
    eve = _has(cats, EVENING) and not _has(cats, DAYTIME_FOOD)
    night = eve and _has(cats, NIGHT)  # bars and clubs: only ever an evening stop
    day = _has(cats, MORNING)
    if slot == "evening":
        return 2 if eve else (-1 if day else 0)
    if slot == "morning":
        return -4 if night else 2 if day else (-1 if eve else 0)  # an overflow club goes to the afternoon, not 9 am
    if night:
        return -2
    return 1 if day else 0  # afternoon: sights/beaches/lunch spots are all fine


def arrange_day(stops: list[dict]) -> tuple[list[dict], bool]:
    """Re-order one day's picks so cafés and sights land in the morning and dinner/bars in the evening. Only the
    time of day changes: the same stops, owners and scores, so the fairness math is untouched."""
    slots = [s["slot"] for s in stops]
    best, best_fit = list(stops), sum(_slot_fit(s, sl) for s, sl in zip(stops, slots, strict=True))
    for perm in itertools.permutations(stops):
        fit = sum(_slot_fit(s, sl) for s, sl in zip(perm, slots, strict=True))
        if fit > best_fit:
            best, best_fit = list(perm), fit
    moved = [s["id"] for s in best] != [s["id"] for s in stops]
    out = [dict(s, slot=sl) for s, sl in zip(best, slots, strict=True)]
    return out, moved

def arrange_trip(itinerary: list[dict]) -> tuple[list[dict], int]:
    """Best time of day across the whole trip: order each day, then swap stops between days while that improves
    the fit (a bar picked for day 2's morning trades places with day 1's evening museum). Owners, stops and
    scores stay the same, only (day, slot) moves. Returns (itinerary, number of stops moved)."""
    out = []
    for d in sorted({x["day"] for x in itinerary}):
        out += arrange_day([x for x in itinerary if x["day"] == d])[0]

    def fit(x, day, slot):
        return _slot_fit(x, slot)

    improved = True
    while improved:
        improved = False
        for i, j in itertools.combinations(range(len(out)), 2):
            a, b = out[i], out[j]
            if a["day"] == b["day"] and a["slot"] == b["slot"]:
                continue
            gain = (fit(a, b["day"], b["slot"]) + fit(b, a["day"], a["slot"])
                    - fit(a, a["day"], a["slot"]) - fit(b, b["day"], b["slot"]))
            if gain > 0:
                out[i], out[j] = dict(a, day=b["day"], slot=b["slot"]), dict(b, day=a["day"], slot=a["slot"])
                improved = True
    order = {s: k for k, s in enumerate(SLOTS)}
    out.sort(key=lambda x: (x["day"], order.get(x["slot"], 9)))
    before = {x["place"]: (x["day"], x["slot"]) for x in itinerary}
    moved = sum(1 for x in out if before.get(x["place"]) != (x["day"], x["slot"]))
    return out, moved


def _pts(v: float) -> str:
    n = round(100 * v)
    return "under 1 pt" if n < 1 else f"within {n} pt" + ("s" if n != 1 else "")


def _gap(v: float, limit: float) -> str:
    """Gap in points; one decimal when rounding would hide it ("5.1 pts > 5", not "5 pts > 5")."""
    n, lim = 100 * v, round(100 * limit)
    return f"{n:.1f}" if round(n) == lim and abs(n - lim) > 1e-9 else f"{round(n)}"


AFFINITY_BANDS = ((0.85, "Very high"), (0.70, "High"), (0.50, "Moderate"))


def affinity_band(score: float) -> str:
    """Word for a per-entity Qloo affinity, so the explanation never calls a 0.55 'high'."""
    return next((word for floor, word in AFFINITY_BANDS if score >= floor), "Low")


TIER = 0.03  # a pick counts as "the owner's top tier" within this affinity of their best remaining stop


def _norm(matrix: dict) -> dict:
    """Qloo affinities aren't comparable across people (some tastes score high everywhere), so measure each
    traveler against their own best candidate stop: 1.0 = as good as their favourite option in this city."""
    out = {}
    for lb, row in matrix.items():
        top = max(row.values(), default=0.0) or 1.0
        out[lb] = {k: v / top for k, v in row.items()}
    return out


def _choose(owner, pool, used, norm, labels, tier, running):
    """Owner's turn: among the owner's top-tier stops, take the one that best lifts whoever in the rest of the
    group is furthest behind so far (running enjoyment)."""
    free = [p for p in pool if p["name"] not in used]
    if not free:
        return None, False
    own = {p["name"]: norm.get(owner, {}).get(p.get("id"), 0.0) for p in free}
    best = max(own.values())
    others = [lb for lb in labels if lb != owner and norm.get(lb)]

    def lift(p):
        if not others:
            return 0.0
        return min(running.get(lb, 0.0) + norm[lb].get(p.get("id"), 0.0) for lb in others)

    first = max(free, key=lambda p: own[p["name"]])
    tier_set = [p for p in free if own[p["name"]] >= best - tier]
    pick = max(tier_set, key=lambda p: (round(lift(p), 6), own[p["name"]]))
    return pick, pick["name"] != first["name"]


def _evaluate(itinerary: list[dict], labels: list[str], norm: dict) -> dict:
    """How much each traveler is expected to enjoy the WHOLE trip: mean over every stop of their Qloo affinity,
    relative to their own best option in the city (so different taste baselines are compared fairly)."""
    sat = {}
    for lb in [lb for lb in labels if norm.get(lb)]:  # travelers with no resolved taste can't be scored
        vals = [norm.get(lb, {}).get(x.get("id")) for x in itinerary]
        vals = [v for v in vals if v is not None]
        sat[lb] = round(sum(vals) / len(vals), 3) if vals else 0.0
    vals = list(sat.values()) or [0.0]
    return {"trip_enjoyment": sat, "spread": round(max(vals) - min(vals), 3),
            "least_satisfied": min(sat, key=sat.get) if sat else None}


def build_itinerary(labels, pools, matrix, likes_of, days, dest_score, max_spread: float = 0.05):
    """Plan -> self-check -> revise once. Returns (itinerary, fairness_check, decisions)."""
    days = max(1, min(days, 5))
    decisions: list[dict] = []
    norm = _norm(matrix)
    # Compensation: whoever the destination fits least picks first (gets the extra slot when slots don't divide).
    order = sorted(labels, key=lambda lb: (dest_score.get(lb, 0.0), labels.index(lb)))
    if len(labels) > 1 and dest_score:
        lo = order[0]
        decisions.append({"step": "compensate", "text": f"{lo} is the least-matched traveler for this destination "
                          f"({round(100 * dest_score.get(lo, 0.0))}%), so {lo} picks first each round."})

    def run(tier, order):
        itinerary, used, i, swaps = [], set(), 0, 0
        running = dict.fromkeys(labels, 0.0)
        for d in range(1, days + 1):
            for s in SLOTS:
                lbl = order[i % len(order)]
                i += 1
                pick, swapped = _choose(lbl, pools.get(lbl, []), used, norm, labels, tier, running)
                if not pick:
                    continue
                swaps += swapped
                used.add(pick["name"])
                for lb in labels:
                    running[lb] += norm.get(lb, {}).get(pick.get("id"), 0.0)
                scores = {lb: round(matrix.get(lb, {}).get(pick.get("id"), 0.0), 3) for lb in labels}
                aff = scores.get(lbl) or pick["affinity"]
                others = [lb for lb in labels if lb != lbl and scores.get(lb)]
                also = max(others, key=lambda lb: scores[lb]) if others else None
                why = f"{affinity_band(aff)} Qloo affinity ({aff:.2f}) with {lbl}'s tastes: {likes_of.get(lbl, '')}"
                if also:
                    why += f"; {also} scores it {round(100 * scores[also])}% too"
                itinerary.append({"day": d, "slot": s, "place": pick["name"], "id": pick.get("id"), "for": lbl,
                                  "affinity": aff, "group_scores": scores, "address": pick.get("address"),
                                  "description": pick.get("description") or "", "image": pick.get("image"),
                                  "lat": pick.get("lat"), "lon": pick.get("lon"), "why": why,
                                  "tags": pick.get("tags", []), "kind": kind(pick),
                                  "categories": pick.get("categories", [])})
        return itinerary, swaps

    itinerary, swaps = run(TIER, order)
    check = _evaluate(itinerary, labels, norm)
    if len(labels) > 1 and any(matrix.get(lb) for lb in labels):
        if swaps:
            decisions.append({"step": "group_aware", "text": f"{swaps} stop(s) swapped for an equally-loved option "
                              "(within 3 points for its owner) that helps whoever in the group was furthest behind."})
        if check["spread"] > max_spread:
            lo = check["least_satisfied"]
            alt, _ = run(TIER * 3, [lo] + [lb for lb in order if lb != lo])
            alt_check = _evaluate(alt, labels, norm)
            kept = alt_check["spread"] < check["spread"]
            decisions.append({"step": "revise", "text":
                              f"Self-check: trip-enjoyment gap {_gap(check['spread'], max_spread)} pts > "
                              f"{round(100 * max_spread)}, {lo} enjoys the trip least — re-planned with {lo} picking "
                              f"first and a wider group-aware window: gap {_gap(alt_check['spread'], max_spread)} pts, "
                              + ("kept the revision." if kept else "no improvement, kept the original plan.")})
            if kept:
                itinerary, check = alt, alt_check
        else:
            decisions.append({"step": "self_check", "text": f"Self-check passed: everyone's expected enjoyment of "
                              f"the whole trip is {_pts(check['spread'])} "
                              f"(limit {round(100 * max_spread)})."})
    itinerary, moved = arrange_trip(itinerary)
    if moved:
        decisions.append({"step": "time_of_day", "text": f"Moved {moved} stop(s) to a better time of day: cafés, "
                          "sights and beaches by day, dinner and bars in the evening (same stops, same scores)."})
    check["own_picks"] = {lb: sum(1 for x in itinerary if x["for"] == lb) for lb in labels}
    check["scored_for_everyone"] = bool(itinerary) and all(
        all(x["id"] in matrix.get(lb, {}) for lb in labels) for x in itinerary if x.get("id"))
    return itinerary, check, decisions


def _names(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def narrate(r: dict) -> str:
    top = r["ranking"][0] if r["ranking"] else None
    fs = r["fair_share"]
    solo = len(fs) == 1
    ch = r.get("chosen")
    dest = r["destination"]
    if ch and ch.get("scored") is False:
        base = (f"{dest} (your pick): Qloo doesn't score {dest} against these tastes, so there is no city-level "
                "fit, but every stop below comes from Qloo venue affinities in the city."
                + (f" Qloo's best match for this group would be {top['name']} ({top['group_fit']})." if top else ""))
    elif ch:
        base = (f"{dest} (your pick) has a {'taste' if solo else 'group'} fit of {ch['group_fit']}"
                + (f"; least-matched traveler: {ch['least_happy']}" if ch.get("least_happy") and not solo else "")
                + "." + (f" Qloo's best match for {'this taste' if solo else 'this group'} would be {top['name']} "
                         f"({top['group_fit']})." if top else ""))
    elif solo:
        base = f"{dest} is the best match for {next(iter(fs))}'s taste" + (
            f" (fit {top['group_fit']})." if top else ".")
    else:
        base = (f"{dest} is the best shared match"
                + ((f" (group fit {top['group_fit']}; least-matched traveler: {top['least_happy']})"
                    if top.get("least_happy") else f" (group fit {top['group_fit']}, an equal fit for everyone)")
                   if top else "")
                + ".")
    if r["itinerary"] and not solo:
        own = [f"{k} ×{v}" for k, v in fs.items() if v]
        zero = [k for k, v in fs.items() if not v]
        if not zero:
            base += f" Everyone gets their own picks: {', '.join(own)}."
        else:
            n = len(r["itinerary"])
            base += (f" {n} stops for {len(fs)} travelers, so own picks go to {', '.join(own)}; {_names(zero)} "
                     f"{'has' if len(zero) == 1 else 'have'} no own pick yet (every stop is still scored for them)"
                     " — add more days so everyone gets one.")
    missing = r.get("unmatched_travelers") or []
    if missing:
        base += (f" {_names(missing)}'s favourites weren't found in Qloo, so the plan follows "
                 + ("the rest of the group." if len(fs) > 1 else f"{next(iter(fs))}'s taste."))
    fc = r.get("fairness_check") or {}
    enjoy = fc.get("trip_enjoyment") or {}
    if len(enjoy) > 1 and fc.get("scored_for_everyone"):
        lo, hi = round(100 * min(enjoy.values())), round(100 * max(enjoy.values()))
        rng = f"about {lo}%" if lo == hi else f"{lo}–{hi}%"
        base += (f" Fairness self-check: every stop was scored for every traveler, and each of you should enjoy "
                 f"{rng} of your best option there across the whole trip.")
    url, key = os.getenv("LLM_BASE_URL"), os.getenv("LLM_API_KEY")
    if not (url and key):
        return base
    try:
        resp = httpx.post(f"{url.rstrip('/')}/chat/completions", timeout=30,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": os.getenv("LLM_MODEL", "gpt-4o-mini"), "temperature": 0.5,
                                "messages": [{"role": "system", "content":
                                              "Write a warm 4-sentence trip pitch. Only use facts given. "
                                              "Say affinities are aggregate, not personal predictions."},
                                             {"role": "user", "content": str({k: r[k] for k in
                                              ("destination", "ranking", "itinerary", "fair_share")})[:6000]}]})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:  # noqa: BLE001
        return base
