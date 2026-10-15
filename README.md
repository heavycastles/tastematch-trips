# TasteMatch Trips — a group-travel agent that's fair to everyone's taste

**Qloo Agentic Hackathon** · [MIT License](LICENSE) · Built by heavycastles

Group trips fail on taste: one friend wants anime museums, another techno clubs, the third street food.
Trip planners optimise for "the group average" and someone always loses. **TasteMatch Trips** asks each
traveler for 2–3 cultural favourites (movies, artists, brands, shows — **nicknames only, no personal data**)
and runs a fairness-aware agent over the **Qloo Taste AI** API.

## What it does

1. **resolve_entity** — `GET /search` turns each favourite into a Qloo entity (unmatched ones are reported, never guessed).
2. **destination_affinity** — `GET /v2/insights?filter.type=urn:entity:destination&signal.interests.entities=…`
   for the whole group (with `filter.popularity.min` so tiny towns don't dominate), then once per traveler
   with `filter.entities=<group candidates>` so every city gets a real per-traveler affinity.
3. **fairness ranking** — `group_fit = 40% mean + 40% minimum + 20% group affinity`, so a city that thrills two
   friends and bores the third ranks below one everyone likes. The "least-matched traveler" is shown.
4. **local_places** — `GET /v2/insights?filter.type=urn:entity:place&filter.location.query=<City, Region>` per traveler.
5. **itinerary** — round-robin slots so everyone gets their own picks; each pick cites the Qloo affinity and
   the favourites it came from (provenance). Optional LLM writes the pitch from those facts only.

The UI shows the full agent trace (each Qloo call). Responses are cached in memory only, never stored in the
repo. Results are presented as aggregate affinities, not predictions about individuals (per Qloo's safe-use guide).

## Live example (verified 13 Oct 2026)

Against `https://hackathon.api.qloo.com` (`X-Api-Key`). Sample group: Aziz (Spirited Away, Patagonia),
Malika (Daft Punk, Wes Anderson), Rustam (Anthony Bourdain, Chef's Table) — all six entities resolved.

| Rank | Destination | group_fit | least-matched |
| ---: | --- | ---: | --- |
| 1 | **Sayulita, Nayarit** | 78.9 | Aziz |
| 2 | Santa Fe, New Mexico | 78.6 | Malika |
| 3 | Ojai, California | 77.4 | Malika |

Fair itinerary (2 days): Aziz ×2, Malika ×2, Rustam ×2 — e.g. Hacienda Camino al Mar (Aziz 0.92),
Playa Sayulita (Malika 0.83), Mita Mary (Rustam 0.80). Full sanitized sample: [`docs/live-sample.md`](docs/live-sample.md).

## Architecture

```
Travelers (nicknames + cultural likes)
        │
        ▼
FastAPI  POST /api/plan  ──► plan()                         app/agent.py
                              ├─ resolve_entity  /search
                              ├─ destination_affinity  /v2/insights (group + per traveler)
                              ├─ fairness()  mean + min + group affinity
                              ├─ local_places  /v2/insights place + location
                              ├─ itinerary  round-robin fair share + provenance
                              └─ narrate()  optional LLM from Qloo facts only
        │
        ▼
Web UI (/)  ranking bars · itinerary · agent trace · source badge (live | mock)
n8n/telegram-group-trip.json  → Telegram group bot
```

Qloo client: `app/qloo.py` — base `https://hackathon.api.qloo.com`, header `X-Api-Key`, in-process LRU cache,
retry on HTTP 429. Without `QLOO_API_KEY` a built-in mock taste graph is used (`source: mock`).

## Run

```bash
cp .env.example .env               # QLOO_API_KEY from the hackathon key form
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                # 13 tests (offline mock + live smoke if key present)
.venv/bin/python serve.py          # loads .env; http://localhost:8080 → "Load sample" → "Plan our trip"
docker compose up --build          # app :8080 + n8n :5678
```

Hackathon keys only work on `https://hackathon.api.qloo.com` with the `X-Api-Key` header.
Never commit `.env` or the API key.

## API

| Method | Path | |
|---|---|---|
| GET | `/healthz` | `{ok, qloo: live\|mock}` |
| GET | `/api/sample` | demo travelers (Aziz / Malika / Rustam) |
| POST | `/api/plan` | body: `{travelers, days, destination?}` → ranking, itinerary, trace |

Example:

```json
POST /api/plan
{"travelers":[{"label":"Aziz","likes":[{"name":"Spirited Away","type":"movie"}]}],"days":2}
```

## Submission pack (local)

- Devpost write-up: [`SUBMISSION.md`](SUBMISSION.md)
- Demo script: [`docs/video-script.md`](docs/video-script.md)
- Slides PDF: [`docs/slides.pdf`](docs/slides.pdf) · cover: [`docs/cover.png`](docs/cover.png)
- Draft demo video: [`docs/demo-draft.mp4`](docs/demo-draft.mp4) (pending user review)


## Preflight / publish (local)

```bash
./scripts/preflight_submit.sh
# VISIBILITY=private ./scripts/publish_github.sh   # gh as heavycastles; wait for user OK
```

## Deploy demo (Render)

One-click free-tier demo. Config: `render.yaml` (Docker, Oregon, health `/healthz`).
`QLOO_API_KEY` is prompted by Render (`sync: false`) — never put the key in git.
`QLOO_BASE_URL` defaults to `https://hackathon.api.qloo.com`. Without a key the app serves the offline mock graph.

1. Push this repo public (user approval required), e.g. `heavycastles/tastematch-qloo`.
2. Open [Render Blueprint](https://dashboard.render.com/select-repo?type=blueprint), connect the repo, Apply.
3. Paste the hackathon API key when Render asks for `QLOO_API_KEY`.
4. Demo URL → paste into `SUBMISSION.md` Links (currently TODO pending Render).

```bash
docker build -t tastematch-qloo .
docker run --rm -p 8080:8080 -e QLOO_BASE_URL=https://hackathon.api.qloo.com tastematch-qloo
# curl http://localhost:8080/healthz   # qloo: mock without key
```

## License

MIT — see [`LICENSE`](LICENSE) (Copyright (c) 2026 heavycastles). GitHub detects it and shows "MIT license" in the repo About sidebar once the repo is public.
