# TasteMatch Trips — a group-travel agent that's fair to everyone's taste (Qloo Agentic Hackathon)

Group trips fail on taste: one friend wants anime museums, another techno, the third street food. Trip
planners optimise for "the group average" and someone always loses. TasteMatch Trips asks each traveler
for 2–3 cultural favourites (movies, artists, brands, shows — **no personal data, nicknames only**) and runs
an agent over the Qloo Taste AI API:

1. **resolve_entity** — `GET /search` turns each favourite into a Qloo entity (unmatched ones are reported, not guessed).
2. **destination_affinity** — `GET /v2/insights?filter.type=urn:entity:destination&signal.interests.entities=…`
   once per traveler **and** once for the whole group.
3. **fairness ranking** — `group_fit = 40% mean + 40% minimum + 20% group affinity`, so a city that thrills two
   friends and bores the third ranks below one everyone likes. The "least-matched traveler" is shown.
4. **local_places** — `GET /v2/insights?filter.type=urn:entity:place&filter.location.query=<city>` per traveler.
5. **itinerary** — round-robin slots so everyone gets their own picks; each pick cites the Qloo affinity and
   the favourites it came from (provenance). Optional LLM writes the pitch from those facts only.

The UI shows the full agent trace (each Qloo call). Qloo responses are cached in memory only, never stored in
the repo. Results are presented as aggregate affinities, not predictions about individuals (per Qloo's safe-use guide).

## Run
```bash
cp .env.example .env               # QLOO_API_KEY from the hackathon key form
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q                # 9 tests, offline mock
.venv/bin/python serve.py          # http://localhost:8080 -> "Load sample" -> "Plan our trip"
docker compose up --build          # app :8080 + n8n :5678 (n8n/telegram-group-trip.json)
```
Without `QLOO_API_KEY` the app uses a small built-in mock taste graph (clearly labelled `source: mock`).
Hackathon keys only work on `https://hackathon.api.qloo.com` with the `X-Api-Key` header.

## API
`POST /api/plan {"travelers":[{"label":"Aziz","likes":[{"name":"Spirited Away","type":"movie"}]}],"days":2,"destination":null}`

## Deploy (public demo)
Dockerfile listens on `$PORT`; deploy to Render / Fly.io / Railway / Google Cloud Run with `QLOO_API_KEY` as a secret.

## License
MIT
