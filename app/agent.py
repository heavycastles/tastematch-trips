"""TasteMatch Trips: a fairness-aware group-travel agent on Qloo.

Tools (all Qloo): resolve_entity (/search) -> destination_affinity (/v2/insights destination) per traveler and
for the group -> local_places (/v2/insights place + filter.location.query). The planner ranks destinations by a
fairness score (no one is left out), then builds an itinerary where every traveler gets their own picks, and
explains each pick with the Qloo signal it came from. Every candidate stop is also scored for every traveler
(cross_score_places), so the agent can pick group-friendly stops, check how much each person will enjoy the whole
trip, and re-plan once if the gap is too wide. An optional LLM writes the narrative.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

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


def resolve(travelers: list[dict], tr: Trace) -> tuple[list[dict], list[str]]:
    unresolved = []
    for t in travelers:
        t["entities"] = []
        for like in t.get("likes", []):
            etype = like.get("type", "movie")
            etype = etype if etype in TYPES else "movie"
            hits = qloo.search(like["name"], URN.get(etype, f"urn:entity:{etype}"), 1)
            tr.add("resolve_entity", endpoint="/search", query=like["name"], type=etype, found=bool(hits))
            if hits:
                t["entities"].append(hits[0])
            else:
                unresolved.append(f"{t['label']}: {like['name']}")
    return travelers, unresolved


def fairness(per_traveler: dict[str, dict[str, float]], group: list[dict]) -> list[dict]:
    names = {e["name"] for e in group} | {n for d in per_traveler.values() for n in d}
    gaff = {e["name"]: e["affinity"] for e in group}
    out = []
    for n in names:
        scores = {lbl: d.get(n, 0.0) for lbl, d in per_traveler.items()}
        vals = list(scores.values()) or [0.0]
        mean, low = sum(vals) / len(vals), min(vals)
        fit = round(100 * (0.4 * mean + 0.4 * low + 0.2 * gaff.get(n, mean)), 1)
        least = min(scores, key=scores.get) if scores else None
        out.append({"name": n, "group_fit": fit, "per_traveler": scores, "least_happy": least})
    out.sort(key=lambda d: (-d["group_fit"], d["name"]))
    return out


def plan(travelers: list[dict], days: int = 2, destination: str | None = None) -> dict:
    t0 = time.perf_counter()
    tr = Trace()
    travelers, unresolved = resolve([dict(t) for t in travelers], tr)
    all_ids = [e["id"] for t in travelers for e in t["entities"]]
    if not all_ids:
        return {"error": "none_resolved", "unresolved": unresolved,
                "ask": "I couldn't match any of those tastes in Qloo. Try a well-known movie, artist or brand."}

    chosen_id = None
    if destination:
        hit = qloo.search(destination, "urn:entity:destination", 1)
        tr.add("resolve_destination", endpoint="/search", query=destination, type="destination", found=bool(hit))
        if not hit:
            return {"error": "destination_not_found", "unresolved": unresolved,
                    "ask": f"Qloo doesn't know \"{destination}\" as a destination. Try a city name such as "
                           "Lisbon or Tokyo, or leave the field empty and let the agent pick."}
        chosen_id = hit[0]["id"]

    # Prefer well-known destinations on the live API (hackathon graph skews to tiny towns otherwise).
    dest_kw = {"popularity_min": 0.55} if qloo.live() else {}
    group = qloo.insights("urn:entity:destination", all_ids, 15, **dest_kw)
    tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler="group",
           signals=len(all_ids), results=len(group))
    loc_by_name: dict[str, str] = {}
    for e in group:
        if e.get("location_query"):
            loc_by_name[e["name"]] = e["location_query"]
    candidate_ids = [e["id"] for e in group if e.get("id")]
    if chosen_id and chosen_id not in candidate_ids:
        candidate_ids.append(chosen_id)
    name_by_id = {e["id"]: e["name"] for e in group if e.get("id")}

    # Score the SAME candidate set per traveler via filter.entities (true affinities, not top-N overlap).
    per: dict[str, dict[str, float]] = {}
    for t in travelers:
        ids = [e["id"] for e in t["entities"]]
        if not ids:  # nothing resolved: don't let an unknown taste drag every city's fairness to zero
            continue
        if candidate_ids and qloo.live():
            # Candidates already popularity-filtered; score them raw for each traveler.
            res = qloo.insights(
                "urn:entity:destination", ids, max(15, len(candidate_ids)),
                filter_entities=candidate_ids,
            )
        else:
            res = qloo.insights("urn:entity:destination", ids, 15, **dest_kw)
        tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler=t["label"],
               signals=len(ids), results=len(res), filtered=bool(candidate_ids and qloo.live()))
        per[t["label"]] = {e["name"]: e["affinity"] for e in res}
        for e in res:
            if e.get("id"):
                name_by_id.setdefault(e["id"], e["name"])
            if e.get("location_query"):
                loc_by_name[e["name"]] = e["location_query"]
    ranking = fairness(per, group)
    chosen = None
    if chosen_id:
        cname = name_by_id.get(chosen_id)
        chosen = next((dict(r) for r in ranking if r["name"] == cname), None)
        if chosen is None:  # Qloo returned no affinity at all for the chosen city
            chosen = {"name": cname or destination, "group_fit": 0.0, "least_happy": None,
                      "per_traveler": {t["label"]: 0.0 for t in travelers}}
        chosen["name"] = destination
        chosen["chosen"] = True
        ranking = [r for r in ranking if r["name"] != cname]
    city = destination or (ranking[0]["name"] if ranking else None)
    # Places need a location query string; prefer geocode city over neighborhood labels.
    place_location = destination or (loc_by_name.get(city) if city else None) or city

    pools: dict[str, list[dict]] = {}
    for t in travelers:
        ids = [e["id"] for e in t["entities"]]
        try:
            pools[t["label"]] = (
                qloo.insights("urn:entity:place", ids, 8, location=place_location) if ids and place_location else []
            )
        except qloo.QlooError as e:
            if e.kind != "bad_location":
                raise
            alt = loc_by_name.get(name_by_id.get(chosen_id, "")) if chosen_id else None
            if alt and alt != place_location:
                place_location = alt
                pools[t["label"]] = qloo.insights("urn:entity:place", ids, 8, location=place_location)
            else:
                return {"error": "destination_not_found", "unresolved": unresolved,
                        "ask": f"Qloo has no local venue data for \"{place_location}\". Try a nearby larger city, "
                               "or leave the destination empty."}
        tr.add("local_places", endpoint="/v2/insights", filter_type="place", traveler=t["label"],
               location=place_location, results=len(pools[t["label"]]))

    # Venue-level fairness: score EVERY candidate stop for EVERY traveler (same filter.entities trick as for
    # cities), so the agent knows not only who a stop is for, but how much the rest of the group will enjoy it.
    union = list(dict.fromkeys(p["id"] for pool in pools.values() for p in pool if p.get("id")))
    matrix: dict[str, dict[str, float]] = {}
    if union and len(travelers) > 1:
        for t in travelers:
            ids = [e["id"] for e in t["entities"]]
            if not ids:
                matrix[t["label"]] = {}
                continue
            try:
                res = qloo.insights("urn:entity:place", ids, len(union), location=place_location,
                                    filter_entities=union)
            except qloo.QlooError as e:
                if e.kind == "rate_limited":
                    raise
                res = []
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
    dest_score = (chosen or (ranking[0] if ranking else {})).get("per_traveler", {})
    itinerary, check, decisions = build_itinerary(labels, pools, matrix, likes_of, days, dest_score)
    fair = {lbl: sum(1 for x in itinerary if x["for"] == lbl) for lbl in labels}
    result = {"destination": city, "days": max(1, min(days, 5)),
              "mode": "chosen" if chosen else "best_match", "chosen": chosen,
              "ranking": ranking[:6], "itinerary": itinerary, "fair_share": fair,
              "unresolved": unresolved, "trace": tr.steps,
              "fairness_check": check, "decisions": decisions,
              "travelers": [{"label": t["label"], "matched": [e["name"] for e in t["entities"]],
                             "matched_detail": [{"name": e["name"], "type": (e.get("type") or "").rsplit(":", 1)[-1],
                                                 "image": e.get("image")} for e in t["entities"]]}
                            for t in travelers],
              "source": "qloo-hackathon-api" if qloo.live() else "mock",
              "note": "Qloo results are aggregate taste affinities, not predictions about any individual."}
    result["narrative"] = narrate(result)
    result["stats"] = {"qloo_calls": len(tr.steps), "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    return result


SLOTS = ("morning", "afternoon", "evening")
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
                why = f"High Qloo affinity ({aff:.2f}) with {lbl}'s tastes: {likes_of.get(lbl, '')}"
                if also:
                    why += f"; {also} scores it {round(100 * scores[also])}% too"
                itinerary.append({"day": d, "slot": s, "place": pick["name"], "id": pick.get("id"), "for": lbl,
                                  "affinity": aff, "group_scores": scores, "address": pick.get("address"),
                                  "description": pick.get("description") or "", "image": pick.get("image"),
                                  "lat": pick.get("lat"), "lon": pick.get("lon"), "why": why,
                                  "tags": pick.get("tags", [])})
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
                              f"Self-check: trip-enjoyment gap {round(100 * check['spread'])} pts > "
                              f"{round(100 * max_spread)}, {lo} enjoys the trip least — re-planned with {lo} picking "
                              f"first and a wider group-aware window: gap {round(100 * alt_check['spread'])} pts, "
                              + ("kept the revision." if kept else "no improvement, kept the original plan.")})
            if kept:
                itinerary, check = alt, alt_check
        else:
            decisions.append({"step": "self_check", "text": f"Self-check passed: everyone's expected enjoyment of "
                              f"the whole trip is within {round(100 * check['spread'])} pts "
                              f"(limit {round(100 * max_spread)})."})
    check["own_picks"] = {lb: sum(1 for x in itinerary if x["for"] == lb) for lb in labels}
    check["scored_for_everyone"] = bool(itinerary) and all(
        all(x["id"] in matrix.get(lb, {}) for lb in labels) for x in itinerary if x.get("id"))
    return itinerary, check, decisions


def narrate(r: dict) -> str:
    top = r["ranking"][0] if r["ranking"] else None
    share = ", ".join(f"{k} ×{v}" for k, v in r["fair_share"].items())
    ch = r.get("chosen")
    if ch:
        base = (f"{r['destination']} (your pick) has a group fit of {ch['group_fit']}"
                + (f"; least-matched traveler: {ch['least_happy']}" if ch.get("least_happy") else "") + "."
                + (f" Qloo's best shared match for this group would be {top['name']} ({top['group_fit']})."
                   if top else "")
                + (f" Everyone still gets their own picks: {share}." if r["itinerary"] else ""))
    else:
        base = (f"{r['destination']} is the best shared match"
                + (f" (group fit {top['group_fit']}; least-matched traveler: {top['least_happy']})" if top else "")
                + (f". Everyone gets their own picks: {share}." if r["itinerary"] else "."))
    fc = r.get("fairness_check") or {}
    enjoy = fc.get("trip_enjoyment") or {}
    if len(enjoy) > 1 and fc.get("scored_for_everyone"):
        lo, hi = round(100 * min(enjoy.values())), round(100 * max(enjoy.values()))
        base += (f" Fairness self-check: every stop was scored for every traveler, and each of you should enjoy "
                 f"{lo}–{hi}% of your best option there across the whole trip.")
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
