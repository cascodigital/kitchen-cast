# AI Porting Guide

This document is written for a strong coding agent asked to adapt `kitchen-cast` to a different home. Treat it as the operational brief.

## Mission

Recreate the behavior, not the original author's infrastructure:

1. A TV normally shows a photo slideshow.
2. When a separate music speaker starts playing, the TV switches to album art and track metadata.
3. If a recipe has been armed, the TV overlays a compact recipe panel on top of the music screen.
4. A web app lets the user select a recipe, request an AI-generated playlist, and arm the recipe for the next music session.
5. When music stops, the TV returns to the photo slideshow and the armed recipe eventually clears.

## Non-goals

- Do not make this a universal installer before it works in the target home.
- Do not replace Home Assistant with a new event bus.
- Do not merge the web app, renderer, and Home Assistant automations into one large service.
- Do not add crossfade or browser-based casting during the first port.
- Do not store SSH keys in the web-facing app.

## Mental model

The Chromecast TV displays only one URL:

```text
http://<home-assistant-host>:8123/local/current.jpg?t=<timestamp>
```

Everything else is deciding which process writes `current.jpg`.

- Photo mode: `slideshow_gen.py` writes `current.jpg`.
- Music mode: `musica_slideshow.py` writes `current.jpg`.
- Recipe overlay: `musica_slideshow.py` reads `music_recipe.json` each frame and draws the panel only when the file exists and is enabled.

The web app does not cast anything. It only arms a recipe and starts playlist creation. Home Assistant remains the display state machine.

## Required target-home facts

Before editing code, collect these values:

| Value | Example placeholder | Where used |
|---|---|---|
| Home Assistant base URL | `http://homeassistant.local:8123` | app env, cast URL, snippets |
| TV media player entity | `media_player.COZINHA` | scripts and automations |
| Music speaker entity | `media_player.SALA` | automations, music metadata sensor |
| App host URL reachable from HA | `http://APP_HOST:8095` | `fetch_music_recipe` shell command |
| Photo source path | `/media/photos` | `slideshow_gen.py` adaptation |
| Recipe source path | `/recipes` | app volume |
| Weather coordinates | `WEATHER_LAT`, `WEATHER_LON` | renderers |
| AI worker command | `docker exec ... llm-cli ...` | `app/app.py` |
| YouTube Music auth file | `/auth/ytmusic_auth.json` | app volume |

## Porting order

Follow this order. It reduces failure domains.

1. **Static photo cast**
   - Put a known `current.jpg` under Home Assistant `/config/www/current.jpg`.
   - Make the TV display it with `media_player.play_media`.
   - Add cache-busting query strings.

2. **Photo renderer**
   - Run `slideshow_gen.py` until it updates `/config/www/current.jpg`.
   - Verify repeated downloads of `/local/current.jpg` have changing hashes or timestamps.

3. **Music metadata capture**
   - Confirm the speaker entity exposes `media_artist`, `media_title`, `media_album_name`, `media_content_id`, and ideally `entity_picture`.
   - Add `sensor.music_state_writer`.
   - Confirm `/config/.music_state.txt` changes while music plays.

4. **Music renderer**
   - Run `start_musica_helper.py`.
   - Confirm `musica_slideshow.py` writes a music frame to `current.jpg`.
   - Push the TV twice after starting the renderer. This avoids stale Chromecast frames.

5. **State machine**
   - Add `musica_slideshow_start` and `musica_slideshow_stop`.
   - Verify speaker playing starts music mode.
   - Verify speaker stopped restarts photo mode.

6. **Recipe overlay**
   - Manually write `music_recipe.json`.
   - Confirm the overlay appears in music mode.
   - Delete the file and confirm music mode has no recipe panel.

7. **Recipe arm/disarm**
   - Add `timer.recipe_window`, `input_boolean.recipe_armed`, `fetch_music_recipe`, and `disarm_music_recipe`.
   - Confirm the web app can arm a recipe without SSH.

8. **Playlist generation**
   - Wire the AI worker last.
   - The system should still be useful if playlist generation fails.

## Recommended AI-agent prompt

Use a prompt like this when handing the repo to another coding agent:

```text
You are porting this personal Home Assistant + Chromecast reference build to my home.

Read README.md, docs/AI_PORTING_GUIDE.md, docs/SYSTEM_CONTRACTS.md, docs/ARCHITECTURE.md, and the Home Assistant YAML snippets before editing.

Do not redesign the architecture. Keep the contracts:
- /config/www/current.jpg is the only TV image.
- /config/.music_state.txt is the music metadata handoff.
- /config/music_recipe.json is the optional recipe overlay.
- Home Assistant controls the state machine.
- The web app arms recipes and asks an AI worker for playlists.

First collect my target entity ids, hosts, paths, weather coordinates, and worker command. Then produce a small patch and a validation checklist. Avoid crossfade/browser casting in the initial port.
```

## Validation checklist

- `current.jpg` is reachable from Home Assistant `/local/current.jpg`.
- TV can display a static `current.jpg`.
- Photo renderer changes the file without manual intervention.
- Speaker entity changes to `playing` and exposes enough metadata.
- `.music_state.txt` updates with the current track.
- Music renderer produces album-art frames.
- TV receives the current track, not the previous track.
- Recipe JSON appears in the overlay.
- Recipe disarms after the session.
- Web app can arm a recipe with no SSH key.
- Playlist generation failure does not break recipe arming.

## Failure boundaries

Debug in this order:

1. Is `current.jpg` changing?
2. Can Home Assistant serve it through `/local/current.jpg`?
3. Did the TV receive a fresh `play_media` call with a new query string?
4. Is the music metadata file current?
5. Is the correct renderer running?
6. Does `music_recipe.json` exist and parse?
7. Is the web app reachable from Home Assistant?
8. Is the AI worker reachable from the web app?

Most bugs are not AI bugs. They are stale files, stale Chromecast frames, YAML parsing, or metadata timing.
