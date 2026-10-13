---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-family: Inter, Helvetica, Arial, sans-serif; }
  h1 { color: #5b2be0; }
  h2 { color: #1a1a1a; }
  footer { color: #666; font-size: 14px; }
  table { font-size: 18px; }
  code { background: #f4f4f4; }
  strong { color: #5b2be0; }
footer: TasteMatch Trips · Qloo Agentic Hackathon · MIT
---

<!-- _class: lead -->
# TasteMatch Trips
## A fairness-aware group-travel agent on Qloo Taste AI

**heavycastles** · `github.com/heavycastles` · Qloo Agentic Hackathon  
Agents, but with taste — and fairness.

---

# Problem

Group trips fail on **taste**, not calendars.

- One friend: anime museums
- Another: techno & design
- Third: street food & Chef's Table

Classic planners optimise for the **average** → someone quietly loses.

> We need a city where nobody is left out.

---

# Solution

Each traveler names 2–3 **cultural favourites** (nicknames only).

1. **Resolve** favourites via Qloo `/search`
2. **Score** destinations (group + per traveler)
3. **Rank** by fairness: `40% mean + 40% min + 20% group`
4. **Places** via `/v2/insights` + location
5. **Itinerary** round-robin with provenance

```
likes → search → insights → fairness → places → fair itinerary
```

---

# Live result (13 Oct 2026)

Hackathon API · sample Aziz / Malika / Rustam · all 6 entities matched

| Rank | Destination | group_fit | least-matched |
| ---: | --- | ---: | --- |
| 1 | **Sayulita, Nayarit** | **78.9** | Aziz |
| 2 | Santa Fe, New Mexico | 78.6 | Malika |
| 3 | Ojai, California | 77.4 | Malika |

Fair share itinerary: **Aziz ×2, Malika ×2, Rustam ×2**

---

# Architecture

```
Travelers (nicknames + likes)
        │
        ▼
FastAPI  POST /api/plan
   ├─ resolve_entity     GET /search
   ├─ destination_affinity  GET /v2/insights
   ├─ fairness()         mean + min + group
   ├─ local_places       place + location.query
   └─ itinerary + narrate (facts only)
        │
        ▼
UI: ranking · itinerary · agent trace · live|mock badge
n8n → Telegram group bot
```

---

# Responsible use of Qloo

- **Nicknames only** — no personal data to Qloo
- Unmatched likes are **surfaced**, never guessed
- Cache is **in-memory only** (never in the repo)
- Results labelled as **aggregate affinities**
- Trace shows every API call for auditability

---

# What's next

1. `/v2/tags` vibe filters (beach / food / nightlife)
2. Budget & travel-time alongside fairness
3. Telegram group polls to confirm the city
4. Samarkand / Tashkent local guides
5. Public demo deploy (key as secret)

**Built with:** Python · FastAPI · Qloo Taste AI · n8n · Docker · pytest (13)

MIT · Link in description
