#!/usr/bin/env python3
"""
start_musica_helper.py
Reads the media player state from /config/.music_state.txt (written by the
Home Assistant music_state_writer sensor via a Jinja2 template) and starts
musica_slideshow.py.
"""
import fcntl, os, sys, subprocess, time

STATE_FILE = "/config/.music_state.txt"
LOG_FILE   = "/tmp/musica_slideshow.log"
LOCK_FILE  = "/config/.slideshow_renderer.lock"

def read_state():
    try:
        mtime = os.path.getmtime(STATE_FILE)
        age = time.time() - mtime
        if age > 60:
            print(f"[helper] WARNING: stale state file ({age:.0f}s)")
        content = open(STATE_FILE).read().strip()
        # Format: state|video_id|artist|title|entity_pic|album
        parts = content.split("|")
        if len(parts) < 6:
            print(f"[helper] Invalid format: {repr(content)}")
            # Detect a template that was not rendered
            if "{{" in content:
                print("[helper] ERROR: template was not rendered by Home Assistant!")
                print("[helper] command_line sensor does not support templates in this version.")
            return None
        return {
            "state":      parts[0].strip(),
            "video_id":   parts[1].strip(),
            "artist":     parts[2].strip(),
            "title":      parts[3].strip(),
            "entity_pic": parts[4].strip(),
            "album":      parts[5].strip(),
        }
    except FileNotFoundError:
        print(f"[helper] {STATE_FILE} does not exist yet (waiting for sensor)")
        return None
    except Exception as e:
        print(f"[helper] Error reading state file: {e}")
        return None


def main():
    state = read_state()
    if not state:
        sys.exit(1)

    print(f"[helper] State: {state['state']}")

    if state["state"] != "playing":
        print("[helper] Not playing, aborting")
        sys.exit(0)

    artist    = state["artist"]
    title     = state["title"]
    video_id  = state["video_id"]
    entity_pic = state["entity_pic"]
    album     = state["album"]

    if not artist and not title:
        print("[helper] Empty artist/title; template may not have rendered")
        sys.exit(1)

    print(f"[helper] Starting: {artist} — {title}")

    env = os.environ.copy()
    env["ARTIST"]     = artist
    env["TITLE"]      = title
    env["VIDEO_ID"]   = video_id
    env["ENTITY_PIC"] = entity_pic
    env["ALBUM"]      = album

    # Renderer ownership is serialized with the photo watchdog through an flock.
    # State and metadata are validated before the running renderer is killed,
    # so a bad trigger cannot blank the TV.
    with open(LOCK_FILE, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        os.system("pkill -f '[m]usica_slideshow.py' 2>/dev/null")
        os.system("pkill -f '[s]lideshow_gen.py' 2>/dev/null")
        log = open(LOG_FILE, "w")
        proc = subprocess.Popen(
            ["python3", "-u", "/config/musica_slideshow.py"],
            env=env,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        print(f"[helper] PID={proc.pid} — OK")


if __name__ == "__main__":
    main()
