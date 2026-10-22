# Devpost submission — Qloo Agentic Hackathon

**Deadline:** Oct 30 2026, 23:45 ET (= Oct 31 06:45 MSK)

**Project name:** TasteMatch Trips  
**Tagline:** Agents, but with taste — and fairness. A Qloo-powered agent that picks the trip your whole group will love.

**Built by:** heavycastles

---

## Inspiration

Every group trip has the friend who "didn't really enjoy it." Budgets and calendars are easy to reconcile;
taste is the real constraint, and it's cultural — movies, music, food, design. Classic planners collapse
everyone into an average and someone quietly loses. We wanted an agent that treats fairness as a first-class
signal: not "what's hottest for the group," but "where nobody is left out."

Qloo's Taste AI gives cultural affinities without needing personal profiles. That matches how real travel
groups talk ("I love Spirited Away and Patagonia") and stays inside responsible-use rules: nicknames only,
aggregate affinities, no invented entities.

## What it does

Each traveler names 2–3 cultural favourites. TasteMatch Trips:

1. Resolves each favourite via Qloo `GET /search` (unmatched inputs are surfaced, never guessed).
2. Scores destinations with `GET /v2/insights` for the whole group and again per traveler against the same
   candidate set (`filter.entities`), with a popularity floor so tiny towns don't dominate.
3. Ranks cities by a fairness score: **group_fit = 40% mean + 40% minimum + 20% group affinity**, and names
   the least-matched traveler.
4. Pulls local places per traveler (`filter.type=urn:entity:place` + `filter.location.query`).
5. Scores **every candidate stop for every traveler** (`filter.entities` over all stops + the same location) —
   a traveler × stop affinity matrix.
6. Plans → self-checks → re-plans: the least-matched traveler picks first; each turn takes one of the owner's
   top-tier stops that best lifts whoever is furthest behind; then the agent measures how much each person should
   enjoy the whole trip (relative to their own best option there) and re-plans once if the gap exceeds 5 points.
   The UI shows the result and every decision ("Fairness self-check").
7. Writes a short narrative from those facts only (deterministic template; an LLM rewrite is optional and off in the hosted demo).
8. If the group names its own destination, resolves it in Qloo and scores it for every traveler next to Qloo's top pick.

The web UI shows the best shared match (group-fit ring, per-traveler fit), the fairness ranking, a photo itinerary
with provenance and per-traveler scores on every stop, the fairness self-check, a map of the stops and the full
agent trace (every Qloo call, count and time). **Share this plan** gives a link that re-creates the group and
re-plans it live; **Copy for group chat** copies the itinerary as text. Screenshots of a
live run: `docs/screenshots/`; demo video: `docs/demo-v4.mp4` (hosted demo, 2:24). An n8n workflow
(`n8n/telegram-group-trip.json`) can post the plan into a Telegram group.

**Live verification (13 Oct 2026)** against `https://hackathon.api.qloo.com`: sample trio Aziz / Malika / Rustam
resolved all six entities; top destination **Sayulita, Nayarit** (group_fit 78.9; least-matched: Aziz), then
Santa Fe and Ojai; fair itinerary 2×2×2. Sanitized sample in `docs/live-sample.md` (no API key).

## How we built it

- **FastAPI** app (`app/main.py`) with `POST /api/plan`, sample endpoint, health check, static UI.
- **Agent** (`app/agent.py`): resolve → destination affinities → fairness → places → cross-score stops →
  plan / self-check / re-plan → narrate.
- **Qloo client** (`app/qloo.py`): hackathon base URL, `X-Api-Key`, in-process LRU cache, 429 retries,
  destination labels with geocode disambiguation, offline mock graph for CI and demos without a key.
- **n8n** Telegram group workflow; **Docker Compose** for app + n8n.
- **Tests:** 48 pytest cases covering fairness math, venue-level cross-scoring, hotel/errand filtering, time-of-day ordering, group-aware picks, self-check/re-plan, mock planning, chosen destinations, friendly errors (422/503/504), bounded 429 retries, API routes, live response shapes, and optional live smoke.

## Challenges we ran into

- Mapping free-text likes to Qloo entity types (`movie`, `artist`, `brand`, `person`, `tv_show`, …) without guessing.
- Live hackathon graph skews toward obscure destinations unless `filter.popularity.min` is set.
- Per-traveler "top N" destinations don't overlap cleanly — we score the **same** group candidate set with
  `filter.entities` so affinities are comparable.
- `filter.location.query` is sensitive to geocode strings; we prefer `City, Region` from the destination itself
  (e.g. "Sayulita, Nayarit") over nearby village names that resolve to the wrong metro.
- Keeping demos honest: mock vs live badges, no keys in the repo, aggregate-affinity disclaimer on every plan.

## Accomplishments that we're proud of

- End-to-end live API path with a reproducible sample (Sayulita top pick, fair 2×2×2 itinerary).
- Fairness ranking that surfaces the least-matched traveler instead of hiding them.
- Provenance on every itinerary slot (affinity + which favourites drove the pick).
- Full agent trace in the UI so judges can see every Qloo call.
- An agent that checks its own plan for fairness — and re-plans when someone would enjoy the trip less.
- 48 passing tests; works offline via mock when the key is absent.

## What we learned

- Taste AI is most useful when you constrain the candidate set and measure fairness, not when you only ask for
  "top destinations for the union of likes."
- Responsible defaults (nicknames, unmatched surfaced, memory-only cache) are easy to bake in early and hard to retrofit.
- Raw affinities aren't comparable across people (some tastes score high everywhere), so fairness has to be
  measured against each traveler's own best option.
- Small UX cues (source badge, least-matched label, fair-share counters) make an agent feel trustworthy.

## What's next

- Tags-based vibes via `/v2/tags` (beach / food / nightlife filters).
- Budget and travel-time constraints alongside fairness.
- Telegram group polls to confirm the chosen city.
- Local guides for Samarkand / Tashkent as first-class destinations.

## Built with

Python, FastAPI, Qloo Taste AI (`/search`, `/v2/insights`), httpx, n8n, Docker, pytest

## Links

- Functional demo: https://tastematch-trips.vercel.app (Vercel; Render Blueprint `render.yaml` also included)
- Public repo (MIT): https://github.com/heavycastles/tastematch-trips
- Video: `docs/demo-v4.mp4` (2:24, script `docs/video-script-v4.md`, subtitles `docs/demo-v4.srt`, cover `docs/demo-v4-cover.png`); previous cuts `docs/demo-v3.mp4` (2:20, before the venue filter), `docs/demo-v2.mp4` (1:54); older drafts `docs/demo-live-draft.mp4`, `docs/demo-draft.mp4`
- Slides PDF: `docs/slides.pdf` · Cover: `docs/cover.png`
- Live sample (sanitized): `docs/live-sample.md`
