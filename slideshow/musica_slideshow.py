#!/usr/bin/env python3
"""
musica_slideshow.py - Modo Música para o Slideshow da Cozinha
Troca as fotos por imagens do artista enquanto o Chromecast da sala toca música.
Lê ARTIST, TITLE, VIDEO_ID, ENTITY_PIC, ALBUM via variáveis de ambiente.
"""
import os, sys, time, signal, json, random, datetime
import urllib.request, urllib.parse, urllib.error
from io import BytesIO

LAT, LON = float(os.environ.get("WEATHER_LAT","40.7128")), float(os.environ.get("WEATHER_LON","-74.0060"))  # defina suas coordenadas

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("[musica] PIL não encontrado")

OUT_FILE = "/config/www/current.jpg"
TMP_FILE = "/config/www/.music_tmp.jpg"
RECIPE_FILE = "/config/music_recipe.json"
INTERVAL = 15

IMG_W, IMG_H = 1920, 1080

FONT_DIR  = "/usr/local/lib/python3.14/site-packages/aioslimproto/font"
FONT_BOLD = os.path.join(FONT_DIR, "DejaVu-Sans-Bold.ttf")
FONT_REG  = os.path.join(FONT_DIR, "DejaVu-Sans.ttf")
ACCENT_YELLOW = (255, 220, 60)


def get_font(bold=False, size=48):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except Exception:
        return ImageFont.load_default()



def fetch_current_temp():
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        "&current=temperature_2m"
        "&timezone=America%2FSao_Paulo"
    )
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            data = json.loads(r.read())
        return data["current"]["temperature_2m"]
    except Exception as e:
        print(f"[temp] falhou: {e}")
        return None

def shadow(draw, pos, text, font, color=(255, 255, 255)):
    x, y = pos
    for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2),(0,3),(3,0),(-3,0),(0,-3)]:
        draw.text((x+dx, y+dy), text, font=font, fill=(0, 0, 0, 210))
    draw.text((x, y), text, font=font, fill=color)


def text_width(draw, text, font):
    try:
        return draw.textlength(text, font=font)
    except Exception:
        return draw.textbbox((0, 0), text, font=font)[2]


def wrap_line(draw, text, font, max_width):
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if text_width(draw, candidate, font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def load_recipe_overlay():
    if not os.path.exists(RECIPE_FILE):
        return None
    try:
        with open(RECIPE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[receita] erro lendo {RECIPE_FILE}: {e}")
        return None

    if not data.get("enabled", False):
        return None

    title = str(data.get("title", "")).strip()
    lines = data.get("lines", [])
    if isinstance(lines, str):
        lines = [line.strip() for line in lines.splitlines() if line.strip()]
    elif isinstance(lines, list):
        lines = [str(line).strip() for line in lines if str(line).strip()]
    else:
        lines = []

    if not title or not lines:
        print("[receita] arquivo ativo sem title/lines validos")
        return None

    return {"title": title, "lines": lines}


def draw_recipe_overlay(draw, recipe):
    panel_x = IMG_W // 2 + 28
    panel_y = 122
    panel_w = IMG_W - panel_x - 46
    panel_h = 780

    draw.rounded_rectangle(
        [(panel_x, panel_y), (panel_x + panel_w, panel_y + panel_h)],
        radius=22,
        fill=(0, 0, 0, 142),
        outline=(255, 255, 255, 38),
        width=2,
    )

    x = panel_x + 34
    y = panel_y + 30
    max_w = panel_w - 68

    title_font = get_font(True, 42)
    body_font = get_font(False, 29)
    small_font = get_font(False, 25)

    shadow(draw, (x, y), recipe["title"], title_font, color=(255, 255, 255))
    y += 62

    for idx, line in enumerate(recipe["lines"]):
        prefix = "• "
        font = body_font if idx < 10 else small_font
        wrapped = wrap_line(draw, prefix + line, font, max_w)
        for part in wrapped:
            shadow(draw, (x, y), part, font, color=(245, 245, 245))
            y += 35 if font == body_font else 30
        y += 5
        if y > panel_y + panel_h - 36:
            break


def fetch_image(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return Image.open(BytesIO(r.read())).convert("RGB")
    except Exception as e:
        print(f"[fetch] {url[:70]}: {e}")
        return None


def fetch_deezer_images(artist_name, max_images=4):
    imgs = []
    try:
        q = urllib.parse.quote(artist_name)
        url = f"https://api.deezer.com/search/artist?q={q}&limit=5"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        for a in data.get("data", [])[:3]:
            if a.get("name", "").lower() not in artist_name.lower() and \
               artist_name.lower() not in a.get("name", "").lower():
                continue
            for size in ["picture_xl", "picture_big"]:
                pic = a.get(size, "")
                if pic and "default" not in pic:
                    img = fetch_image(pic)
                    if img:
                        imgs.append(img)
                        print(f"[deezer] {a['name']} ({size}) ok")
                        break
            if len(imgs) >= max_images:
                break

        # Se não achou match exato, pega o primeiro resultado mesmo
        if not imgs:
            for a in data.get("data", [])[:2]:
                for size in ["picture_xl", "picture_big"]:
                    pic = a.get(size, "")
                    if pic and "default" not in pic:
                        img = fetch_image(pic)
                        if img:
                            imgs.append(img)
                            print(f"[deezer] fallback {a['name']} ok")
                            break
                if imgs:
                    break
    except Exception as e:
        print(f"[deezer] erro: {e}")
    return imgs


def fit_fill(img, w, h):
    """Redimensiona e corta a imagem para preencher w x h (cover)."""
    ratio = max(w / img.width, h / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def make_frame(bg_img, artist, title, album="", current_temp=None):
    canvas = fit_fill(bg_img.copy(), IMG_W, IMG_H)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Gradiente escuro na parte de baixo
    for i in range(320):
        alpha = int(220 * (i / 320))
        draw.rectangle([(0, IMG_H - 320 + i), (IMG_W, IMG_H - 320 + i + 1)],
                       fill=(0, 0, 0, alpha))

    # Gradiente suave no topo
    for i in range(80):
        alpha = int(120 * (1 - i / 80))
        draw.rectangle([(0, i), (IMG_W, i + 1)], fill=(0, 0, 0, alpha))

    DIAS = ["Seg","Ter","Qua","Qui","Sex","Sab","Dom"]
    now  = datetime.datetime.now()
    hora = now.strftime("%H:%M")
    data_lbl = f"{DIAS[now.weekday()]}, {now.day}"
    f_hora = get_font(bold=True,  size=78)
    f_data = get_font(bold=False, size=42)
    hora_w = draw.textlength(hora, font=f_hora)
    shadow(draw, (48, 30), hora, f_hora)
    shadow(draw, (48 + hora_w + 24, 52), data_lbl, f_data)
    if current_temp is not None:
        temp_str = f"{round(current_temp)}°"
        f_temp = get_font(bold=True, size=42)
        data_w = draw.textlength(data_lbl, font=f_data)
        shadow(draw, (48 + hora_w + 24 + data_w + 18, 52), temp_str, f_temp, color=ACCENT_YELLOW)

    y_base = IMG_H - 210

    # ♪ ícone
    shadow(draw, (55, y_base), "♪", get_font(True, 54), color=(255, 200, 50))

    # Artista
    shadow(draw, (130, y_base), artist, get_font(True, 58), color=(255, 255, 255))

    # Título
    shadow(draw, (130, y_base + 72), title, get_font(False, 42), color=(210, 210, 210))

    # Album
    if album:
        shadow(draw, (130, y_base + 130), album, get_font(False, 28), color=ACCENT_YELLOW)

    # Label "AO VIVO" no canto superior direito
    label = "♫ TOCANDO AGORA"
    f_label = get_font(False, 26)
    lw = draw.textlength(label, font=f_label)
    shadow(draw, (IMG_W - lw - 50, 28), label, f_label, color=(255, 200, 50))

    recipe = load_recipe_overlay()
    if recipe:
        draw_recipe_overlay(draw, recipe)

    canvas.save(TMP_FILE, "JPEG", quality=90)
    os.replace(TMP_FILE, OUT_FILE)


running = True


def stop(sig, frame):
    global running
    print("[musica] sinal recebido, encerrando...")
    running = False


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)


def main():
    artist      = os.environ.get("ARTIST", "Artista").strip()
    title       = os.environ.get("TITLE", "").strip()
    video_id    = os.environ.get("VIDEO_ID", "").strip()
    entity_pic  = os.environ.get("ENTITY_PIC", "").strip()
    album       = os.environ.get("ALBUM", "").strip()

    print(f"[musica] {artist} — {title} | video={video_id}")
    current_temp = fetch_current_temp()
    temp_time = time.time()

    images = []
    image_source = "fallback"

    # 1. Album art da URL pública do YouTube Music (entity_picture).
    # Se a capa atual existir, usa só ela. Isso evita alternar para imagens ruins
    # de artista/fallback enquanto uma capa correta está disponível.
    if entity_pic.startswith("http"):
        ep = entity_pic.replace("w544-h544", "w1920-h1080")
        img = fetch_image(ep)
        if img:
            images = [img]
            image_source = "album art"
            print("[img] album art ok; usando apenas a capa atual")

    # 2. YouTube thumbnail (maxres ou hq), apenas se a capa falhar.
    if not images and video_id:
        for q in ["maxresdefault", "hqdefault"]:
            img = fetch_image(f"https://img.youtube.com/vi/{video_id}/{q}.jpg")
            if img:
                # Ignora thumbnail genérico do YT (todo preto/cinza)
                arr = list(img.getdata())
                if len(set(arr[::500])) > 10:
                    images = [img]
                    image_source = f"youtube {q}"
                    print(f"[img] youtube {q} ok")
                    break

    # 3. Imagens do artista via Deezer, apenas se capa e YouTube falharem.
    if not images:
        images = fetch_deezer_images(artist, max_images=4)
        if images:
            image_source = "deezer artist"

    if not images:
        print("[musica] sem imagens, usando fallback")
        fb = Image.new("RGB", (IMG_W, IMG_H), (15, 15, 25))
        images = [fb]

    print(f"[musica] {len(images)} imagem(ns), fonte={image_source}, ciclo {INTERVAL}s")

    idx = 0

    while running:
        if time.time() - temp_time > 1800:
            current_temp = fetch_current_temp()
            temp_time = time.time()
        try:
            make_frame(images[idx % len(images)], artist, title, album, current_temp)
        except Exception as e:
            print(f"[musica] erro frame: {e}")
        idx += 1
        for _ in range(INTERVAL):
            if not running:
                break
            time.sleep(1)

    print("[musica] encerrado.")


if __name__ == "__main__":
    main()
