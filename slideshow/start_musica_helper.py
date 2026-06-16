#!/usr/bin/env python3
"""
start_musica_helper.py
Lê o estado do media player de /config/.music_state.txt (escrito pelo sensor
music_state_writer do HA via Jinja2 template) e inicia musica_slideshow.py.
"""
import os, sys, subprocess, time

STATE_FILE = "/config/.music_state.txt"
LOG_FILE   = "/tmp/musica_slideshow.log"

def read_state():
    try:
        mtime = os.path.getmtime(STATE_FILE)
        age = time.time() - mtime
        if age > 60:
            print(f"[helper] AVISO: state file desatualizado ({age:.0f}s)")
        content = open(STATE_FILE).read().strip()
        # Formato: state|video_id|artist|title|entity_pic|album
        parts = content.split("|")
        if len(parts) < 6:
            print(f"[helper] Formato inválido: {repr(content)}")
            # Verifica se o template não foi renderizado
            if "{{" in content:
                print("[helper] ERRO: template não foi renderizado pelo HA!")
                print("[helper] command_line sensor não suporta templates nesta versão.")
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
        print(f"[helper] {STATE_FILE} não existe ainda (aguardando sensor)")
        return None
    except Exception as e:
        print(f"[helper] Erro ao ler state file: {e}")
        return None


def main():
    os.system("pkill -f '[m]usica_slideshow.py' 2>/dev/null")
    os.system("pkill -f '[s]lideshow_gen.py' 2>/dev/null")

    state = read_state()
    if not state:
        sys.exit(1)

    print(f"[helper] Estado: {state['state']}")

    if state["state"] != "playing":
        print("[helper] Não está tocando, abortando")
        sys.exit(0)

    artist    = state["artist"]
    title     = state["title"]
    video_id  = state["video_id"]
    entity_pic = state["entity_pic"]
    album     = state["album"]

    if not artist and not title:
        print("[helper] Artista/título vazios — template pode não ter renderizado")
        sys.exit(1)

    print(f"[helper] Iniciando: {artist} — {title}")

    env = os.environ.copy()
    env["ARTIST"]     = artist
    env["TITLE"]      = title
    env["VIDEO_ID"]   = video_id
    env["ENTITY_PIC"] = entity_pic
    env["ALBUM"]      = album

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
