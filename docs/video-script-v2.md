# TasteMatch Trips — demo video v2

`docs/demo-v2.mp4` · 1:54 · 1920×1080 · 30 fps · burned-in subtitles (`docs/demo-v2.srt`) · cover `docs/demo-v2-cover.png`

Recorded from the production deployment https://tastematch-trips.vercel.app (live Qloo hackathon API, fictional sample group Aziz / Malika / Rustam; two plan runs).
Music: synthesized for this video (no third-party tracks).

| Time | Scene | Narration |
|---|---|---|
| 0:00 | Hook card: three friends with different tastes → real result frame ("So who gets their way?") → title | Three friends. Three totally different tastes. One trip. So who gets their way? With TasteMatch Trips, everyone does. |
| 0:08 | Problem card: majority pick vs fair pick (illustration) | Group trips usually get planned for the majority, or for the loudest friend. And someone always ends up dragged along. |
| 0:15 | Live site: typing the three travelers' favourites | This is the live app. Each friend adds a nickname and a couple of favourites. Aziz loves Interstellar and Patagonia. Malika, Daft Punk and Wes Anderson. Rustam, Anthony Bourdain and Chef's Table. |
| 0:29 | Live site: Plan our trip → agent at work → results (real time, no speed-up) | One click, and the agent goes to work on Qloo's live API. Thirteen calls, about a second. |
| 0:36 | Best shared match: Sayulita, Nayarit · group fit 80.0 · Aziz 77% / Malika 90% / Rustam 76% | Sayulita, Mexico. Group fit: eighty. Malika is at ninety percent, and even the least-matched friend, Rustam, gets seventy-six. |
| 0:47 | Fairness ranking (40/40/20) | Every city is ranked by fairness: forty percent average, forty percent the least happy traveler, twenty percent group affinity. |
| 0:55 | 2-day itinerary from Qloo place insights, round-robin 2×2×2 | Then a two-day plan built from Qloo's local places. It's shared round-robin, so everyone gets two picks of their own, and every stop shows the Qloo signal behind it. |
| 1:05 | Map of 6 stops + agent trace (13 Qloo calls, 1.2 s) | All six stops on one map, plus a trace of every Qloo call the agent made. |
| 1:10 | Own destination: type Lisbon → plan | Already have a city in mind? Type Lisbon. The agent finds it in Qloo and scores it for every traveler, with the same taste signals. |
| 1:19 | Lisbon 65.1 vs Qloo's top pick Sayulita 80.0, "your pick" row in the ranking | Lisbon gets sixty-five, against Qloo's top pick, Sayulita, at eighty. Now the group can decide with real numbers. |
| 1:28 | How it uses Qloo: /search → /v2/insights destination (+ filter.entities per traveler) → /v2/insights place + filter.location.query | Under the hood, it's the Qloo Insights API. Search turns each favourite into a Qloo entity. Destination insights score cities for the whole group, and filter dot entities re-scores that exact candidate set for each traveler. Then place insights, filtered by location, fill the itinerary. |
| 1:46 | Close: live URL + GitHub repo | TasteMatch Trips. One trip, everyone's taste. Try it live, and grab the open-source code on GitHub. |
