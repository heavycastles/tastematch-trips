# TasteMatch Trips — demo video v3

`docs/demo-v3.mp4` · 2:20 · 1920×1080 · 30 fps · burned-in subtitles (`docs/demo-v3.srt`) in a band below the app window (they never cover the UI) · cover `docs/demo-v3-cover.png`

Recorded on 22 Oct 2026 from the production deployment https://tastematch-trips.vercel.app (live Qloo hackathon API, fresh deployment so nothing was served from cache for the main run; fictional sample groups Aziz / Malika / Rustam and Sam / Jo / Kai).
Shows the features added in commit 1205049: every stop scored for every traveler, the Fairness self-check card with re-plan, share link and copy-for-group-chat.
Music: synthesized for this video (no third-party tracks). The only speed-ups are the typing (≤1.2×), the trace scroll (≤1.3×) and the Paris loading wait (2×, labelled in the frame).

| Time | Scene | Narration |
|---|---|---|
| 0:00 | Hook: three friends with different tastes → real result frame (“So who gets their way?”) → title | Three friends. Three totally different tastes. One trip. So who gets their way? With TasteMatch Trips, everyone does. |
| 0:08 | Problem card: majority pick vs fair pick (illustration) | Group trips usually get planned for the majority, or for the loudest friend. And someone always ends up dragged along. |
| 0:15 | Live site: typing the three travelers' favourites | This is the live app. Each friend adds a nickname and a couple of favourites. Aziz loves Interstellar and Patagonia. Malika, Daft Punk and Wes Anderson. Rustam, Anthony Bourdain and Chef's Table. |
| 0:29 | Plan our trip → agent at work (7 steps) → results; real time, no speed-up · 16 Qloo calls · 4.0 s | One click, and the agent goes to work on Qloo's live API. Sixteen calls, about four seconds. |
| 0:36 | Best shared match: Sayulita, Nayarit · group fit 80.0 · Aziz 77% / Malika 90% / Rustam 76% | Sayulita, Mexico. Group fit: eighty. Malika is at ninety percent, and even the least-matched friend, Rustam, gets seventy-six. |
| 0:47 | Fairness ranking of destinations (40/40/20) | Every city is ranked by fairness: forty percent average, forty percent the least happy traveler, twenty percent the group. |
| 0:55 | **New:** 2-day itinerary; every stop shows Qloo scores for all three travelers (e.g. Mita Mary: for Rustam 80, Aziz 87, Malika 80) | Then the itinerary. Every stop is scored by Qloo for every traveler, not just the friend who picked it. This seafood bistro is Rustam's pick, and Aziz loves it too, at eighty-seven. |
| 1:07 | **New:** Fairness self-check card: whole-trip enjoyment Aziz 95% · Malika 94% · Rustam 95%, “✓ Fair: within 1 pts”, agent decisions (compensate → group-aware picks → self-check) | Now the agent checks its own work. The fairness self-check measures how much each friend should enjoy the whole trip. Ninety-five, ninety-four, ninety-five. Within one point, so the plan passes. |
| 1:19 | Map of 6 stops + agent trace (resolve_entity → destination_affinity → local_places → cross_score_places) | Every stop sits on one map, and every Qloo call the agent made is right here in the trace. |
| 1:25 | **New:** Share this plan (toast “Link copied…”) and Copy for group chat (toast “Itinerary copied…”) | Happy with the plan? Share this plan copies a link, and Copy for group chat puts the whole itinerary on your clipboard, ready to paste. |
| 1:34 | **New:** a shared `#plan=` link opens a harder group (Sam / Jo / Kai, Paris): form auto-filled, re-planned live (17 calls, 5.9 s; loading shown 2× faster, labelled), card “Gap 7 pts · re-planned” — re-plan didn't help, kept the original and says so | Anyone who opens a shared link gets the group re-planned live. Here's a harder group, in Paris. The gap was seven points, over the limit of five, so the agent re-planned. When that didn't help, it said so honestly. |
| 1:47 | How it uses Qloo: /search → /v2/insights destination (+ filter.entities per traveler) → /v2/insights place + filter.location.query → /v2/insights place + filter.entities (every stop × every traveler) | Under the hood, it's the Qloo Insights API. Search turns each favourite into a Qloo entity. Destination insights score cities for the group, and filter dot entities re-scores the same cities for each traveler. Place insights fill the itinerary, and filter dot entities again scores every stop for every friend. That traveler-by-stop matrix comes from real taste data. An LLM alone can't produce it. |
| 2:12 | Close: live URL + GitHub repo | TasteMatch Trips. One trip, everyone's taste. Try it live, and grab the open-source code on GitHub. |
