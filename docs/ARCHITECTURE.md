# Architecture

For an implementation-oriented checklist, read [`AI_PORTING_GUIDE.md`](AI_PORTING_GUIDE.md). For exact file, route, and entity contracts, read [`SYSTEM_CONTRACTS.md`](SYSTEM_CONTRACTS.md).

## The core idea: one image file, two renderers

The Chromecast on the TV is dumb — it just displays one URL: `current.jpg`, refreshed with a cache-busting `?t=<timestamp>`. Everything is about **who writes `current.jpg`**.

- In the **photo state**, `slideshow_gen.py` writes it (~every 25s).
- In the **music state**, `musica_slideshow.py` writes it (~every 15s).

Only one runs at a time. The Home Assistant automations kill one and start the other based on whether your speaker is playing. The TV never knows the difference.

## State machine

```
            speaker → playing
  PHOTOS ───────────────────────▶ MUSIC
     ▲                              │
     └──────────────────────────────┘
          speaker → paused/idle/off
```

- `musica_slideshow_start` (trigger: speaker playing / track metadata changed) → stop photo renderer, start music renderer, push the new frame to the TV.
- `musica_slideshow_stop` (trigger: speaker paused/idle/off) → stop music renderer, restart photo renderer.

## Recipe overlay (opt-in layer on top of MUSIC)

A recipe is just a JSON file the music renderer reads **every frame**:

```json
{ "enabled": true, "title": "RECIPE NAME", "lines": ["ingredient: amount", "step", "..."] }
```

If the file exists with `enabled:true`, the renderer draws a translucent panel on the right half. If not, music mode is just album art. "Arming" = writing that file + flipping an `input_boolean` + starting a 30-minute `timer`. "Disarming" = deleting it.

A separate automation (`recipe_disarm`) removes the recipe when **either** the 30-minute window expires with no play **or** the speaker has been stopped for 15 minutes — but only if the speaker isn't currently playing, so it never wipes the recipe mid-cook.

## Two ways to arm

1. **Chat** — an assistant turns a recipe into the JSON and writes it.
2. **Web app** (`app/`) — you pick a recipe and tap send.

Both are just triggers for the same one-file mechanism. The renderer is oblivious to which one armed it.

## Web app data flow

```
browser → app POST /cook
  ├─ ARM (deterministic):
  │    recipe.txt → recipe JSON → held in memory at /api/pending_recipe
  │    → Home Assistant shell_command curls /api/pending_recipe → writes the recipe file
  │    → input_boolean ON + timer start (30 min)
  └─ PLAYLIST (AI):
       docker exec <worker> <llm-cli> -p "<DJ prompt>"  → creates a YouTube Music playlist
       → returns the playlist URL
app → returns job id ; browser polls /job/<id> until the playlist URL is ready
```

The app also lists existing playlists (via `ytmusicapi`) and offers 5 random "play now" shortcuts that arm the recipe and redirect straight to the playlist — no waiting for the AI.

## Why no SSH key in the web app

The web app may be internet-exposed. Writing the recipe file onto the Home Assistant host would normally need SSH. Instead, **Home Assistant pulls**: a `shell_command` does `curl http://APP_HOST/api/pending_recipe -o /config/music_recipe.json`. The app holds only a Home Assistant REST token, never an SSH key. Smaller blast radius if the app is ever compromised.

## Adaptation surface

Most target-home changes should be limited to these surfaces:

- Home Assistant entity ids in `homeassistant/*.yaml`
- Home Assistant/app hostnames
- photo folder path and recipe folder path
- weather coordinates
- AI worker command and music-provider auth
- visual layout preferences in `musica_slideshow.py`

Avoid changing the contracts first. The system stays understandable because the contracts are small: one image file, one music metadata file, one active recipe file, and Home Assistant as the state machine.

## Gotchas learned the hard way

- **`shell_command` doesn't render Jinja2.** Templated values pass through literally. Use a `command_line` sensor (which *does* render) to write the track metadata to a state file, then have the helper read that file.
- **YAML parses `off` as `False`.** A trigger list `to: [paused, idle, off]` silently drops `off`. Quote them all: `"off"`.
- **The "one song behind" bug.** The speaker can update `media_content_id` before `media_artist`/`media_title`. Arm a delay + force a sensor update + a second delay before reading metadata, and push the TV frame **twice** (e.g. +4s and +12s) so the first push doesn't ship the previous track's art.
- **Chromecast holds the old JPEG.** Even with a correct `current.jpg`, the Default Media Receiver may keep the stale image. A `media_stop` → short delay → `play_media` with a fresh `?t=` forces the reload.
- **Cross-device `os.replace` fails silently.** Write the temp image on the *same* filesystem as the destination before the atomic replace.

## Weather

Both renderers fetch a forecast from the free Open-Meteo API. Set `WEATHER_LAT` / `WEATHER_LON` (defaults are a placeholder city). No API key required.
