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

# Solution: fairness as a number Qloo can measure

1. **Resolve** each favourite — `GET /search`
2. **Score cities** for the group, then for **each traveler** — `/v2/insights` + `filter.entities`
3. **Rank by fairness** — `40% mean + 40% least-happy + 20% group`
4. **Find stops** per traveler — place insights + `filter.location.query`
   (hotels, errands, offices and >100 km outliers filtered out)
5. **Score every stop for every traveler** — a traveler × stop affinity matrix
6. **Plan → self-check → re-plan** — whole-trip enjoyment gap must be ≤ 5 pts

---

# What the agent decides (and shows)

- **Compensate:** the traveler the city fits least picks first
- **Group-aware picks:** among your top-tier stops, take the one that lifts whoever is furthest behind
- **Self-check:** if the enjoyment gap is > 5 pts, re-plan once and keep it only if it's fairer
- **Time of day:** cafés, sights and beaches by day; dinner, bars and clubs in the evening — never a club at 9 am
- **Honest:** unknown favourites are listed, a city Qloo can't score says "not scored by Qloo", never a fake 0

---

# Live result — hosted demo, re-checked 25 Oct 2026

Sample group Aziz / Malika / Rustam · all 6 favourites matched · 16 Qloo calls in ~4 s

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

# Every stop, scored for everyone

Each card: who it's for, their Qloo affinity, the favourites behind it, and how much every other traveler will enjoy it.

---

![bg right:58% fit](docs/screenshots/10-fairness-self-check.png)

# Fairness self-check

Whole-trip enjoyment per traveler and every decision the agent made — in plain language.

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

- **Nicknames only** — no personal data sent to Qloo
- Unmatched favourites are **surfaced**, never guessed
- Responses cached **in memory only**, never stored
- Results labelled as **aggregate affinities**, not predictions about individuals
- The agent trace shows every Qloo call, with count and time

---

# What's next

1. `/v2/tags` vibe filters (beach / food / nightlife)
2. Budget and travel time alongside fairness
3. Group polls in Telegram (n8n workflow in the repo) to confirm the city
4. Local guides for Samarkand and Tashkent

**Built with:** Python · FastAPI · Qloo Taste AI (`/search`, `/v2/insights`) · Vercel · pytest (106 tests) · n8n

**Try it:** https://tastematch-trips.vercel.app
