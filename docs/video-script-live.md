# TasteMatch Trips — live demo video script (draft `docs/demo-live-draft.mp4`, 1:59)

Built from a real screen recording of the live app on 20 Oct 2026 ~00:45 MSK against `https://hackathon.api.qloo.com`
(13 Qloo calls, plan returned in ~6.1 s; same result as `docs/live-sample.md`). Fictional sample group: Aziz, Malika, Rustam.
1280×720, 30 fps. Voice-over: text-to-speech (draft voice, can be replaced by a human read). Burned-in subtitles.
Music: our own scripted synth track (no samples, no third-party audio). Place photos in the UI are the images Qloo returns for each place.

| Start | Scene | Narration |
|---|---|---|
| 0:00.2 | Hook — three friends + their favourites, live result (Sayulita, group fit 78.9), Day 1 itinerary, logo | Three friends. Three totally different tastes. One trip. Who loses? With TasteMatch Trips, nobody. It finds the destination that fits the whole group, using live Qloo taste data. |
| 0:12.9 | Problem — "planned for the average"; majority pick vs fair pick (labelled illustration) | Group trips get planned for the average, or for the loudest friend. Somebody always ends up dragged along to places they don't care about. |
| 0:21.2 | Live demo · landing → Load sample (Aziz / Malika / Rustam) | This is TasteMatch Trips, running live on the Qloo hackathon API. Load the sample group: Aziz, Malika and Rustam. Nicknames only, two favourites each, from movies and brands to music, chefs and TV. |
| 0:36.0 | Live demo · Plan our trip → agent at work (real ~6 s wait, no speed-up) | One click. The agent resolves every favourite with Qloo search, scores fifteen destinations for the whole group, then re-scores the same cities for each traveler. |
| 0:46.0 | Live demo · best shared match card: group fit ring, per-traveler fit, matched favourites with Qloo images | About six seconds later: Sayulita, Nayarit. Group fit seventy-eight point nine. Malika is at ninety percent, and even Aziz, the least-matched friend, gets seventy-five. |
| 0:59.2 | Live demo · fairness ranking (6 destinations, per-traveler bars, least-happy marked) | Every city is ranked by forty percent average, forty percent the least happy traveler, and twenty percent group affinity. Santa Fe is a close second. |
| 1:08.6 | Live demo · 2-day itinerary with Qloo place photos, "for X" tags, taste match %, provenance | Then a two-day plan from Qloo's local places. Round-robin, so everyone gets two picks of their own. A villa and a resort for Aziz, beaches for Malika, seafood and a wine bar for Rustam. And every stop says which Qloo signal it came from. |
| 1:24.4 | Live demo · map of all 6 stops + agent trace (13 Qloo calls, 6.1 s, qloo-hackathon-api) | All six stops on one map. And the agent trace shows every one of the thirteen Qloo calls: search, destination insights, and place insights. |
| 1:33.4 | Under the hood — four tools, fairness formula, memory-only cache, n8n Telegram | Under the hood: a FastAPI agent with four Qloo-powered tools. Responses are cached in memory only, travelers are just nicknames, and results are framed as aggregate affinities, never personal predictions. The same endpoint powers an n8n workflow for Telegram groups. |
| 1:51.6 | Close — TasteMatch Trips · One trip. Everyone's taste. | TasteMatch Trips. One trip, everyone's taste. Built on Qloo Taste AI, and open source. |

Notes for the final cut:
- Everything in the demo part is real time; the ~6 s wait for the agent is shown uncut. Short holds (slow push-ins on a frozen frame) give the narration room.
- The browser window is shown without its address bar (the page area is framed on the brand background).
- The "majority pick vs fair pick" bars in the problem scene are an illustration, labelled as such on screen.
- Re-record after hosting (Render) if the demo URL should appear; the flow and numbers will be the same unless Qloo data changes.
- Build: `docs/video-work/live/` (record.py → tts.py → music.py → cards.py → build.py); the folder is git-ignored.
