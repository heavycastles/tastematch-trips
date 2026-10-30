# Devpost submission — Qloo Agentic Hackathon

> Draft describes the audited repository version. Verify the deployed commit using `/version` before presenting
> these behaviors as available in the live demo.
> Before submission, review the contest eligibility rules and confirm that the demo can remain available
> through judging within the actual Qloo and hosting account limits.

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
   candidate set (`filter.entities`), with a popularity floor so tiny towns don't dominate. Cities missing a group
   or traveler score are excluded; an incompletely scored chosen city is labeled unscored.
3. Ranks cities by a fairness heuristic: **group_fit = 40% mean + 40% minimum + 20% group affinity**, and names
   the least-matched traveler. The heuristic assumes scores from separate traveler queries are comparable.
4. Pulls local places per traveler (`filter.type=urn:entity:place` + `filter.location.query`). It prefers visitable
   nearby places, but may return the original results if none remain; the UI warns when this fallback is used.
5. Requests **each candidate stop for every traveler** (`filter.entities` over all stops + the same location) —
   a traveler × stop affinity matrix. When scores are missing, the plan omits them and avoids a whole-trip
   fairness check unless every candidate is scored for every traveler.
6. Plans → self-checks → re-plans: the least-matched traveler picks first. With a complete score matrix, each turn
   considers group enjoyment, and the agent checks whole-trip enjoyment relative to each traveler's best candidate.
   If the gap exceeds 5 points, it tries one revision and keeps it only if the gap shrinks.
7. Writes a short narrative from those facts only (deterministic template; an LLM rewrite is optional and off in the hosted demo).
8. If the group names its own destination, resolves it in Qloo and scores it for every traveler next to Qloo's top pick.

The web UI shows the best shared match (group-fit ring, per-traveler fit), the fairness ranking, a photo itinerary
with provenance and available per-traveler scores, the fairness self-check when data is complete, a map and a
trace of logical tool steps. Retries and alternative searches are not individually listed in the trace; this
version reports HTTP attempts and cache hits separately. **Share this plan** gives a link that re-creates the group and
re-plans it live; **Copy for group chat** copies the itinerary as text. Screenshots of a
live run: `docs/screenshots/`. An n8n workflow
(`n8n/telegram-group-trip.json`) can post the plan into a Telegram group.

**Live verification (first run 13 Oct 2026; re-checked on the hosted demo 27 Oct 2026, same result)** against `https://hackathon.api.qloo.com`: sample trio Aziz / Malika / Rustam
resolved all six entities; top destination **Sayulita, Nayarit** (group_fit 78.9; least-matched: Aziz), then
Santa Fe and Ojai; fair itinerary 2×2×2. Sanitized sample in `docs/live-sample.md` (no API key).

## Who it's for

Friend groups, couples, families and student clubs planning a trip together, and the travel apps, group-chat bots
and agencies that serve them. The usual way to settle "where do we go" is a long chat thread where the loudest
voice wins; TasteMatch Trips replaces it with one link everyone can open, a ranking that shows each person's fit,
and a round-robin plan that aims to give each traveler their own picks and says when someone has none yet.
It needs no accounts and only a few favourites per person; users should enter nicknames and public cultural
favourites rather than personal details.

## How we built it

- **FastAPI** app (`app/main.py`) with `POST /api/plan`, sample endpoint, health check, static UI.
- **Agent** (`app/agent.py`): resolve → destination affinities → fairness → places → cross-score stops →
  plan / self-check / re-plan → narrate.
- **Qloo client** (`app/qloo.py`): hackathon base URL, `X-Api-Key`, in-process LRU cache, 429 retries,
  destination labels with geocode disambiguation, offline mock graph for CI and demos without a key.
- **n8n** Telegram group workflow; **Docker Compose** for app + n8n.
- **Tests:** 157 offline tests passed, with 1 optional live smoke test skipped without a key (audited repository version) covering fairness math, venue-level cross-scoring, hotel/errand/office filtering, stop-card tag filtering (no payment/age/parking chips), night clubs never in a morning slot, distance outliers, time-of-day ordering across days, unscored destinations, group-aware picks, self-check/re-plan, mock planning, chosen destinations, friendly errors (422/503/504), bounded 429 retries and a shared per-plan time budget, duplicate favourites counted once, emoji nicknames and Enter-to-submit, API routes, the sample-load race, international/typo'd favourites and wrong-type retries, loose-match flags, chain/address filtering, long solo trips, honest empty/slow/garbled Qloo errors, accessibility (labels, AA contrast, visible keyboard focus, reduced motion, no iOS input zoom), graceful Qloo image fallbacks and right-sized Qloo images, edge caching and compression, live response shapes, HEAD requests and security headers, a /version route that reports the deployed commit, near-duplicate cities merged, trade/B2B listings kept out of the plan, ties not called a least-matched traveler, affinity wording that follows the real score band, parallel per-traveler calls that keep trace order and share the time budget, errand shops and service studios (framing, printing, repair, web design) kept out of the plan, landmarks labelled as sights rather than their gift shop, restaurants and venues labelled as what they are rather than a shop counter inside, look-alike name matches ("Michael Jordan" → "Michael B. Jordan") flagged to the group, and optional live smoke.

## Challenges we ran into

- Mapping free-text likes to Qloo entity types (`movie`, `artist`, `brand`, `person`, `tv_show`, …) without guessing.
- Live hackathon graph skews toward obscure destinations unless `filter.popularity.min` is set.
- Per-traveler "top N" destinations don't overlap cleanly - we request scores for the **same** group candidate set
  with `filter.entities`. Comparing scores across travelers remains a heuristic assumption.
- `filter.location.query` is sensitive to geocode strings; we prefer `City, Region` from the destination itself
  (e.g. "Sayulita, Nayarit") over nearby village names that resolve to the wrong metro.
- Keeping demos honest: mock vs live badges, no keys in the repo, aggregate-affinity disclaimer on every plan.

## Accomplishments that we're proud of

- End-to-end live API path with a reproducible sample (Sayulita top pick, fair 2×2×2 itinerary).
- Fairness ranking that surfaces the least-matched traveler instead of hiding them.
- Itinerary provenance showing available affinity and the favourites associated with each traveler's pool.
- A trace of logical agent steps, with actual Qloo HTTP attempts counted separately.
- An agent that checks its own plan for fairness — and re-plans when someone would enjoy the trip less.
- Offline tests: 131 passed on baseline `dc63f95`; 157 passed in the audited version. The optional
  live smoke test was skipped without a key.

## What we learned

- Taste AI is most useful when you constrain the candidate set and measure fairness, not when you only ask for
  "top destinations for the union of likes."
- Responsible defaults (nicknames, unmatched surfaced, memory-only cache) are easy to bake in early and hard to retrofit.
- The whole-trip check normalizes each traveler against their own best candidate. The destination ranking still
  compares raw scores across people, so it is a heuristic rather than a proven calibrated fairness measure.
- Small UX cues (source badge, least-matched label, fair-share counters) make an agent feel trustworthy.

## What's next

- Tags-based vibes via `/v2/tags` (beach / food / nightlife filters).
- Budget and travel-time constraints alongside fairness.
- Telegram group polls to confirm the chosen city.
- Local guides for Samarkand / Tashkent as first-class destinations.

## Built with

Python, FastAPI, Qloo Taste AI (`/search`, `/v2/insights`), httpx, Vercel, n8n, Docker, pytest

## Links

- Functional demo: https://tastematch-trips.vercel.app (Vercel; Render Blueprint `render.yaml` also included)
- Public repo (MIT): https://github.com/heavycastles/tastematch-trips
- Video: optional. The archived `docs/demo-v5.mp4` records an earlier deployment; its trace-call wording is
  uncorrected and the actual HTTP count in the recording is unverified. See `docs/video-script-v5.md`.
- Slides PDF: `docs/slides.pdf` · Cover: `docs/cover.png`
- Live sample (sanitized): `docs/live-sample.md`
