#!/bin/sh
# Photo-mode watchdog: starts slideshow_gen.py only if no renderer is running.
# Shares an flock with start_musica_helper.py so the two renderers never race.
# Prints one word for the Home Assistant status sensor: music | running | started
set -eu

LOCK_FILE="${LOCK_FILE:-/config/.slideshow_renderer.lock}"

(
  flock -x 9
  if pgrep -f '[m]usica_slideshow.py' >/dev/null; then
    echo music
  elif pgrep -f '[s]lideshow_gen.py' >/dev/null; then
    echo running
  else
    nohup python3 /config/slideshow_gen.py 9>&- >/dev/null 2>&1 &
    echo started
  fi
) 9>"$LOCK_FILE"
