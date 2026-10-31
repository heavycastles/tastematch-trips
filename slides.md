---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-family: Inter, Helvetica, Arial, sans-serif; font-size: 26px; }
  h1 { color: #5b2be0; }
  h2 { color: #1a1a1a; }
  footer { color: #666; font-size: 14px; }
  table { font-size: 20px; }
  code { background: #f4f4f4; }
  strong { color: #5b2be0; }
footer: TasteMatch Trips · Qloo Agentic Hackathon · MIT · tastematch-trips.vercel.app
---

<!-- _class: lead -->
# TasteMatch Trips
## A fairness-aware group-travel agent on Qloo Taste AI

**Live demo:** https://tastematch-trips.vercel.app (no login)
**Code:** https://github.com/heavycastles/tastematch-trips (MIT)

**Status:** check `/version` to confirm the live demo's deployed commit.

Agents, but with taste — and fairness.

---

# Problem

Group trips fail on **taste**, not calendars.

- One friend: Spirited Away & Patagonia
- Another: Daft Punk & Wes Anderson
- Third: Anthony Bourdain & Chef's Table

Planners optimise for the **average** → someone quietly loses.
An LLM can *say* "something for everyone" — it can't **measure** it.

---

# Solution: a fairness heuristic using Qloo scores

1. **Resolve** each favourite — `GET /search`
2. **Score cities** for the group, then for **each traveler** — `/v2/insights` + `filter.entities`
3. **Rank by fairness** — `40% mean + 40% least-happy + 20% group`
4. **Find stops** per traveler — place insights + `filter.location.query`
   (prefer visitable nearby places; original results may be used as a fallback)
5. **Request stop scores for every traveler** — a traveler × stop affinity matrix
6. **Plan → self-check → re-plan** — try to reduce gaps above 5 pts when scores are complete

---

# What the agent decides (and shows)

- **Compensate:** the traveler the city fits least picks first
- **Group-aware picks:** with complete stop scores, choose among top-tier stops to lift whoever is furthest behind
- **Self-check:** if the enjoyment gap is > 5 pts and scores are complete, re-plan once; keep it only if it's fairer
- **Time of day:** cafés, sights and beaches by day; dinner, bars and clubs in the evening — never a club at 9 am
- **Limits:** missing scores are disclosed; city ranking assumes scores are comparable across travelers

---

# Live result — hosted demo, re-checked 27 Oct 2026

Sample group Aziz / Malika / Rustam · all 6 favourites matched · 16 logged steps in ~4 s

| Rank | Destination | group_fit | least-matched |
| ---: | --- | ---: | --- |
| 1 | **Sayulita, Nayarit** | **78.9** | Aziz |
| 2 | Santa Fe, New Mexico | 78.6 | Malika |
| 3 | Ojai, California | 77.4 | Malika |

Itinerary Aziz ×2 · Malika ×2 · Rustam ×2 — whole-trip enjoyment **92% · 93% · 96%** (gap 4 pts, 3 stops swapped)

---

![bg right:58% fit](docs/screenshots/04-best-match.png)

# Best shared match

Group-fit ring, per-traveler fit, matched favourites with Qloo images.

**Share this plan** link + **Copy for group chat**.

---

![bg right:58% fit](docs/screenshots/06-itinerary-day1.png)

# Recorded run: stop scores

Each card shows its owner, Qloo affinity, the favourites associated with that owner's pool, and available scores for other travelers.

---

![bg right:58% fit](docs/screenshots/10-fairness-self-check.png)

# Fairness self-check

When candidate scores are complete, the agent checks whole-trip enjoyment and explains its decisions.

---

# Architecture

```
Travelers (nicknames + favourites)
        │
        ▼
FastAPI  POST /api/plan   (Vercel, Python)
   ├─ resolve_entity        GET /search
   ├─ destination_affinity  GET /v2/insights (+ filter.entities per traveler)
   ├─ fairness()            mean + least-happy + group
   ├─ local_places          place insights + location, venue & distance filters
   ├─ cross_score_places    traveler × stop matrix
   └─ itinerary             plan → self-check → re-plan → time of day
        │
        ▼
UI: best match · ranking · itinerary · self-check · map · agent trace
```

---

# Responsible use of Qloo

- Use **nicknames and public favourites**; typed favourites and destination are sent to Qloo
- Unmatched favourites are **surfaced**, never guessed
- The app's Qloo response cache is **in memory**
- Results labelled as **aggregate affinities**, not predictions about individuals
- The trace groups logical steps; retries and alternate searches are not all listed separately

---

# What's next

1. `/v2/tags` vibe filters (beach / food / nightlife)
2. Budget and travel time alongside fairness
3. Group polls in Telegram (n8n workflow in the repo) to confirm the city
4. Local guides for Samarkand and Tashkent

**Built with:** Python · FastAPI · Qloo Taste AI (`/search`, `/v2/insights`) · Vercel · pytest · n8n

**Try it:** https://tastematch-trips.vercel.app
