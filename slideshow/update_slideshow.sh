#!/bin/sh
# Regenerates fotos.json (JSON array of image paths relative to PHOTOS_DIR).
# Writes atomically and only replaces the file when the list actually changed,
# so slideshow_gen.py reloads its deck only on real changes.
set -eu

FOTOS_DIR="${PHOTOS_DIR:-/media/media/Pictures}"
OUT="${PHOTOS_JSON:-/config/www/fotos.json}"
TMP="${OUT}.tmp"

find "$FOTOS_DIR" -type f \( -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.png" -o -iname "*.webp" \) \
  | sed "s|$FOTOS_DIR/||" \
  | sort \
  | python3 -c "import sys,json; print(json.dumps([line.strip() for line in sys.stdin if line.strip()]))" \
  > "$TMP"

COUNT=$(python3 -c "import json; data=json.load(open('$TMP')); assert data; assert len(data)==len(set(data)); print(len(data))")

if [ -f "$OUT" ] && cmp -s "$TMP" "$OUT"; then
  rm -f "$TMP"
  echo "fotos.json unchanged: $COUNT photos"
else
  mv "$TMP" "$OUT"
  echo "fotos.json updated: $COUNT photos"
fi
