# Devpost submission — Qloo Agentic Hackathon (due Oct 30 2026, 23:45 ET = Oct 31 06:45 MSK)

**Project name:** TasteMatch Trips
**Tagline:** Agents, but with taste — and fairness. A Qloo-powered agent that picks the trip your whole group will love.

## Inspiration
Every group trip has the friend who "didn't really enjoy it". Taste is the real constraint, and it's cultural.

## What it does
Each traveler names 2–3 favourites. The agent resolves them in Qloo, scores destinations per traveler and
for the group, ranks by a fairness score, then builds a day-by-day itinerary from Qloo place affinities where
everyone gets their own picks — each with an explanation of which Qloo signal it came from.

## How we built it
FastAPI agent (`app/agent.py`) with three Qloo tools: `/search`, `/v2/insights` (destination) and
`/v2/insights` (place + location filter). Fairness ranking (mean + min + group affinity), provenance per pick,
agent trace in the UI, n8n workflow for a Telegram group bot, optional LLM narrative constrained to Qloo facts.

## Responsible use
Nicknames only, no personal data sent to Qloo; responses cached server-side in memory only; results labelled as
aggregate affinities; unmatched inputs are surfaced, never guessed.

## Challenges / What's next
Mapping free text to Qloo entities and valid parameters per filter.type; next: tags-based vibes (`/v2/tags`),
budget, Telegram group polls, Samarkand/Tashkent local guides.

## Built with
python, fastapi, qloo-insights-api, n8n, docker

## Links (TODO)
- Functional demo URL: TODO (deploy, see README)
- Public repo with MIT license in About: TODO
- Video: TODO (script in docs/video-script.md; not mandatory per rules but strongly recommended)
