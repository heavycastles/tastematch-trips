# Live API sample (sanitized)

Verified **2026-10-13** against `https://hackathon.api.qloo.com` with a hackathon key;
re-run live on **2026-10-19** with identical rankings, affinities and itinerary.
`source`: `qloo-hackathon-api`. No API key or raw payloads are stored here.

## Sample group

- **Aziz**: likes Spirited Away (movie), Patagonia (brand) → matched `Spirited Away, Patagonia`
- **Malika**: likes Daft Punk (artist), Wes Anderson (person) → matched `Daft Punk, Wes Anderson`
- **Rustam**: likes Anthony Bourdain (person), Chef's Table (tv_show) → matched `Anthony Bourdain, Chef's Table`

Unresolved: `none`.

## Chosen destination: **Sayulita, Nayarit**

Ranked by fairness `group_fit = 40% mean + 40% min + 20% group affinity` (per-traveler affinities via `filter.entities` on the group candidate set).

| Rank | Destination | group_fit | least-matched | per-traveler affinities |
| ---: | --- | ---: | --- | --- |
| 1 | Sayulita, Nayarit | 78.9 | Aziz | Aziz=0.747, Malika=0.904, Rustam=0.761 |
| 2 | Santa Fe, New Mexico | 78.6 | Malika | Aziz=0.852, Malika=0.740, Rustam=0.796 |
| 3 | Ojai, California | 77.4 | Malika | Aziz=0.810, Malika=0.719, Rustam=0.835 |
| 4 | Juneau, Alaska | 76.7 | Malika | Aziz=0.829, Malika=0.713, Rustam=0.800 |
| 5 | Solvang, California | 76.4 | Malika | Aziz=0.800, Malika=0.710, Rustam=0.823 |
| 6 | Sonoma, California | 76.4 | Malika | Aziz=0.741, Malika=0.690, Rustam=0.925 |

## Itinerary sample (fair share Aziz×2, Malika×2, Rustam×2)

- **Day 1 morning** — Hacienda Camino al Mar — Benito Juárez 63732 Bucerías, Nay. Mexico  
  for **Aziz**, affinity 0.918. High Qloo affinity (0.92) with Aziz's tastes: Spirited Away, Patagonia
- **Day 1 afternoon** — Playa Sayulita — Nayarit Mexico  
  for **Malika**, affinity 0.834. High Qloo affinity (0.83) with Malika's tastes: Daft Punk, Wes Anderson
- **Day 1 evening** — Mita Mary — Carretera Federal 200 Km 19.5 63734 Punta de Mita, Nay. Mexico  
  for **Rustam**, affinity 0.803. High Qloo affinity (0.80) with Rustam's tastes: Anthony Bourdain, Chef's Table
- **Day 2 morning** — Casa Velas — C. Pelícanos 311 Marina Vallarta 48335 Puerto Vallarta, Jal. Mexico  
  for **Aziz**, affinity 0.913. High Qloo affinity (0.91) with Aziz's tastes: Spirited Away, Patagonia
- **Day 2 afternoon** — Carricitos Beach — 63728 Nay. Mexico  
  for **Malika**, affinity 0.822. High Qloo affinity (0.82) with Malika's tastes: Daft Punk, Wes Anderson
- **Day 2 evening** — SAYULITA WINES & Co. — C. Miramar 51 63728 Sayulita, Nay. Mexico  
  for **Rustam**, affinity 0.788. High Qloo affinity (0.79) with Rustam's tastes: Anthony Bourdain, Chef's Table

## Narrative

Sayulita, Nayarit is the best shared match (group fit 78.9; least-matched traveler: Aziz). Everyone gets their own picks: Aziz ×2, Malika ×2, Rustam ×2.

_Qloo results are aggregate taste affinities, not predictions about any individual._
