# Reddit Post Draft

## Title options

- I built a kitchen Chromecast that switches from family photos to live music art and overlays AI-condensed recipes
- My Home Assistant kitchen TV turns music into a live album-art + recipe display, with AI-generated YouTube Music playlists
- I accidentally built a tiny kitchen operating system with Home Assistant, Chromecast, recipes, and an AI DJ

## Short version

I built a Home Assistant + Chromecast kitchen display that normally shows a family photo slideshow. When music starts on my Chromecast Audio, the kitchen TV automatically switches to a music mode showing live album art and track metadata.

The extra absurd part: I also have a recipe website. I pick a recipe, type a playlist vibe, and an AI worker creates a YouTube Music playlist. The selected recipe gets condensed into a TV-friendly overlay. When I press play, the Chromecast Audio triggers the kitchen TV, so the screen shows both the album art and the recipe while I cook.

When the music stops, it falls back to the photo slideshow and eventually disarms the recipe.

Repo: `https://github.com/cascodigital/kitchen-cast`

## Longer version

This started as a simple ambient kitchen TV and turned into a small distributed home-lab project.

The base state is a Home Assistant-hosted slideshow. A Python/PIL renderer writes `/config/www/current.jpg`, and Home Assistant keeps pushing that image to a Chromecast on the kitchen TV with a cache-busting URL.

When a separate Chromecast Audio starts playing, Home Assistant captures the track metadata, writes it into a small state file, stops the photo renderer, starts a music renderer, and pushes the new frame to the TV. The music renderer uses album art as the visual background and draws now-playing metadata.

The recipe layer is opt-in. The web app lets me select a recipe and "arm" it by exposing a JSON payload. Home Assistant pulls that payload into `/config/music_recipe.json`. The music renderer reads that file every frame and draws a compact recipe overlay only when the file exists and is enabled.

Playlist generation is delegated to a headless AI worker connected to YouTube Music. The app asks it to create a playlist based on the selected recipe and the user's requested vibe, then returns a playlist link. I press play, the speaker starts, and the TV changes automatically.

It is not a one-click installer. The repo is a reference implementation with sanitized Home Assistant snippets, renderer scripts, the web app, screenshots, architecture docs, and an AI porting guide.

## What made it harder than expected

- Chromecast sometimes holds a stale JPEG even when the file changed.
- Home Assistant `shell_command` does not render Jinja2, so metadata capture needs a `command_line` sensor.
- Track IDs can update before artist/title metadata, causing a "one song behind" bug.
- YAML parses `off` as boolean `False` if you forget quotes.
- The web-facing app should not have SSH keys, so Home Assistant pulls the recipe JSON instead of the app pushing it.

## Suggested subreddits

- `r/homeassistant`
- `r/selfhosted`
- `r/homelab`
- `r/Chromecast`
