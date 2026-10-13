# Demo video script (~2:30–3:00, English)

**Visual style:** title cards + terminal/UI screenshots from a real live run (source: qloo-hackathon-api).
Narration: gTTS draft in `docs/demo-draft.mp4`; replace with recorded voice for final submit.

---

### 0:00–0:20 — Hook
**Visual:** Cover / title card — "TasteMatch Trips" · Qloo Agentic Hackathon.

**Say:** "Three friends, one trip. Aziz loves Spirited Away and Patagonia. Malika loves Daft Punk and Wes Anderson.
Rustam loves Anthony Bourdain and Chef's Table. Classic planners pick a city for the average — and someone loses.
This is TasteMatch Trips: a fairness-aware group-travel agent on Qloo Taste AI."

---

### 0:20–0:45 — Problem → idea
**Visual:** Slide with unfair trip vs fairness formula.

**Say:** "Taste is cultural, not just a survey score. We ask only nicknames and cultural favourites — no personal data.
The agent resolves each favourite in Qloo, scores destinations for the group and for every traveler, then ranks by a
fairness score: forty percent mean affinity, forty percent minimum, twenty percent group affinity. The least-matched
traveler is named out loud."

---

### 0:45–1:25 — Live demo: plan
**Visual:** Terminal or UI — `POST /api/plan` / "Load sample" → Plan. Badge shows `Qloo: live`.

**Say:** "We load the sample group and hit Plan. Against the live hackathon API, all six favourites resolve —
Spirited Away, Patagonia, Daft Punk, Wes Anderson, Anthony Bourdain, Chef's Table. No guesses, nothing unmatched."

**Show ranking table:**
- Sayulita, Nayarit — group fit 78.9 — least-matched: Aziz
- Santa Fe, New Mexico — 78.6 — Malika
- Ojai, California — 77.4 — Malika

**Say:** "Sayulita wins. Not because it is the hottest city for any one person, but because nobody is left behind."

---

### 1:25–2:00 — Itinerary + provenance
**Visual:** Day 1–2 slots with "for Aziz/Malika/Rustam" and affinity.

**Say:** "The itinerary is round-robin so the fair share is two slots each. Day one morning: Hacienda Camino al Mar
for Aziz, affinity point nine two, driven by Spirited Away and Patagonia. Afternoon: Playa Sayulita for Malika.
Evening: Mita Mary for Rustam's food tastes. Every pick cites the Qloo affinity and the favourites it came from."

---

### 2:00–2:25 — Agent trace + responsible use
**Visual:** Trace list — `/search` ×6, destination insights ×4, place insights ×3.

**Say:** "The agent trace shows every Qloo call: six searches, four destination insight calls, three place calls.
Responses stay in memory only. Results are aggregate taste affinities — not predictions about any individual.
Nicknames only."

---

### 2:25–2:45 — Close
**Visual:** Architecture slide → tagline.

**Say:** "TasteMatch Trips: agents, but with taste — and fairness. Built with Qloo Taste AI, FastAPI, and n8n.
Open source, MIT. Link in the description."

---

## Shot list checklist
- [ ] Cover card
- [ ] Fairness formula slide
- [ ] Live plan ranking (Sayulita / Santa Fe / Ojai)
- [ ] Itinerary fair-share slots
- [ ] Agent trace counts
- [ ] Architecture + tagline
