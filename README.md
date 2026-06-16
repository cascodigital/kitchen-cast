# kitchen-cast

Turn a kitchen TV into an ambient photo frame that **becomes a music + recipe display the moment you play music** — and lets an AI build the cooking playlist for you.

You play music on a speaker. A *different* screen in another room notices, flips from your photo slideshow to the album art of whatever is playing, and (optionally) overlays the recipe you're about to cook. An AI DJ assembles a fitting YouTube Music playlist in the background. You press play; the food and the music both show up where you're cooking.

No app to open mid-cook. No phone propped against the flour bag. Music is the trigger; everything else follows.

---

## What it actually does

It's a **two-state machine on a Chromecast-connected TV**, plus an optional recipe overlay and an AI playlist step.

```
                          ┌──────────────────────────────────────────────┐
   DEFAULT STATE  ───────▶│  PHOTO SLIDESHOW                              │
   (no music)             │  your photos + clock + 3-day weather          │
                          │  slideshow_gen.py → current.jpg → Chromecast  │
                          └──────────────────────────────────────────────┘
                                        ▲                 │
                  music stops           │                 │  music starts on the speaker
                  (back to photos)      │                 ▼
                          ┌──────────────────────────────────────────────┐
   MUSIC STATE    ───────▶│  NOW PLAYING                                  │
   (speaker active)       │  album art of the current track (full screen) │
                          │  musica_slideshow.py → current.jpg → Chromecast│
                          │                                              │
                          │   + optional RECIPE OVERLAY (right half)      │
                          │     shown only while a recipe is "armed"      │
                          └──────────────────────────────────────────────┘
```

- **Photo slideshow** is what you see almost all the time. It's the base layer.
- **Music mode** takes over automatically when your speaker starts playing, and reverts when it stops. Nothing manual.
- **The recipe overlay** is opt-in: you "arm" a recipe (by chat or via the web app), and it rides on top of music mode for one cooking session, then disarms itself.

## The pieces

| Piece | Role | Where it runs |
|---|---|---|
| `slideshow/slideshow_gen.py` | Photo slideshow renderer (PIL): photo + clock + weather | Home Assistant (Chromecast host) |
| `slideshow/musica_slideshow.py` | Music-mode renderer: album art + optional recipe overlay | Home Assistant |
| `slideshow/start_musica_helper.py` | Launches the music renderer with current track metadata | Home Assistant |
| `homeassistant/*.yaml` | The state machine: triggers on the speaker, casts the image, arms/disarms recipes | Home Assistant config |
| `app/` | **Web app**: pick a recipe, set a vibe, arm it + get a playlist | any Docker host |
| (your AI worker) | Headless LLM that curates the YouTube Music playlist | any Docker host |

## How a cook works (the web app)

1. Open the site, tap a recipe.
2. Type a vibe for the playlist (or leave blank), **or** tap one of 5 random existing playlists for instant music.
3. The app **arms the recipe** (writes the recipe overlay, starts a 30-minute window) and asks the AI worker to build a playlist.
4. You get a link to the ready playlist. You press play on your speaker.
5. Music mode kicks in → album art + your recipe on the kitchen TV. When you're done, it disarms and goes back to photos.

## Why it's built this way

- **Music is the only trigger.** No new habit to learn — you already play music when you cook.
- **The renderer never changes for the front-end.** Arming a recipe just writes one JSON file the renderer reads each frame. Chat, web app, or a future button all do the same thing.
- **No secrets in the web-facing app.** It never holds an SSH key to the Chromecast host; Home Assistant *pulls* the recipe over HTTP (`shell_command` + `curl`). The app only carries a Home Assistant REST token.
- **Playlist curation is the only "AI" step**, and it's delegated to a headless LLM worker — everything else is deterministic.

## Setup (high level)

1. **Home Assistant** with a Chromecast (or Chromecast Audio as the trigger speaker + a Chromecast on the TV). Drop the `slideshow/` scripts in `/config`, add the `homeassistant/` snippets, set your speaker/TV entity ids and weather coordinates (`WEATHER_LAT`/`WEATHER_LON`).
2. **Recipes**: one `.txt` per recipe in a folder (ingredient/step lines).
3. **AI worker**: a container with a headless LLM CLI + a YouTube Music tool that can create playlists.
4. **Web app**: `app/` — copy `docker-compose.example.yml`, fill the volume paths and `HASS_TOKEN`, `docker compose up -d --build`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full data flow and the gotchas (there are a few good ones).

## Status

Personal project, built incrementally and developed over time. Expect rough edges and opinions baked in. Roadmap in [`docs/ROADMAP.md`](docs/ROADMAP.md).
