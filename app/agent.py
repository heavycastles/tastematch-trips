"""TasteMatch Trips: a fairness-aware group-travel agent on Qloo.

Tools (all Qloo): resolve_entity (/search) -> destination_affinity (/v2/insights destination) per traveler and
for the group -> local_places (/v2/insights place + filter.location.query). The planner ranks destinations by a
fairness score (no one is left out), then builds an itinerary where every traveler gets their own picks, and
explains each pick with the Qloo signal it came from. An optional LLM writes the narrative.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from . import qloo

TYPES = {"movie", "artist", "brand", "book", "tv_show", "video_game", "podcast", "person", "place"}


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
            hits = qloo.search(like["name"], f"urn:entity:{etype}", 1)
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
    tr = Trace()
    travelers, unresolved = resolve([dict(t) for t in travelers], tr)
    all_ids = [e["id"] for t in travelers for e in t["entities"]]
    if not all_ids:
        return {"error": "none_resolved", "unresolved": unresolved,
                "ask": "I couldn't match any of those tastes in Qloo. Try a well-known movie, artist or brand."}

    per: dict[str, dict[str, float]] = {}
    for t in travelers:
        ids = [e["id"] for e in t["entities"]]
        res = qloo.insights("urn:entity:destination", ids, 15) if ids else []
        tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler=t["label"],
               signals=len(ids), results=len(res))
        per[t["label"]] = {e["name"]: e["affinity"] for e in res}
    group = qloo.insights("urn:entity:destination", all_ids, 15)
    tr.add("destination_affinity", endpoint="/v2/insights", filter_type="destination", traveler="group",
           signals=len(all_ids), results=len(group))
    ranking = fairness(per, group)
    city = destination or (ranking[0]["name"] if ranking else None)

    pools: dict[str, list[dict]] = {}
    for t in travelers:
        ids = [e["id"] for e in t["entities"]]
        pools[t["label"]] = qloo.insights("urn:entity:place", ids, 8, location=city) if ids and city else []
        tr.add("local_places", endpoint="/v2/insights", filter_type="place", traveler=t["label"], location=city,
               results=len(pools[t["label"]]))

    itinerary, used = [], set()
    labels = [t["label"] for t in travelers]
    slots = ["morning", "afternoon", "evening"]
    i = 0
    for d in range(1, max(1, min(days, 5)) + 1):
        for s in slots:
            lbl = labels[i % len(labels)]
            i += 1
            pick = next((p for p in pools.get(lbl, []) if p["name"] not in used), None)
            if not pick:
                continue
            used.add(pick["name"])
            likes = ", ".join(e["name"] for t in travelers if t["label"] == lbl for e in t["entities"])
            itinerary.append({"day": d, "slot": s, "place": pick["name"], "for": lbl,
                              "affinity": pick["affinity"], "address": pick.get("address"),
                              "why": f"High Qloo affinity ({pick['affinity']:.2f}) with {lbl}'s tastes: {likes}",
                              "tags": pick.get("tags", [])})
    fair = {lbl: sum(1 for x in itinerary if x["for"] == lbl) for lbl in labels}
    result = {"destination": city, "ranking": ranking[:6], "itinerary": itinerary, "fair_share": fair,
              "unresolved": unresolved, "trace": tr.steps,
              "travelers": [{"label": t["label"], "matched": [e["name"] for e in t["entities"]]} for t in travelers],
              "source": "qloo-hackathon-api" if qloo.live() else "mock",
              "note": "Qloo results are aggregate taste affinities, not predictions about any individual."}
    result["narrative"] = narrate(result)
    return result


def narrate(r: dict) -> str:
    top = r["ranking"][0] if r["ranking"] else None
    base = (f"{r['destination']} is the best shared match"
            + (f" (group fit {top['group_fit']}; least-matched traveler: {top['least_happy']})" if top else "")
            + ". Everyone gets their own picks: "
            + ", ".join(f"{k} ×{v}" for k, v in r["fair_share"].items()) + ".")
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
