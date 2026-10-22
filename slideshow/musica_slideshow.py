#!/usr/bin/env python3
"""
musica_slideshow.py - music mode for the kitchen slideshow.
Replaces the photos with album/artist art while the trigger speaker plays music.
Reads ARTIST, TITLE, VIDEO_ID, ENTITY_PIC, ALBUM from environment variables.
"""
import os, sys, time, signal, json, random, datetime
import urllib.request, urllib.parse, urllib.error
from io import BytesIO

LAT, LON = float(os.environ.get("WEATHER_LAT","40.7128")), float(os.environ.get("WEATHER_LON","-74.0060"))  # placeholder; set your coordinates

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    sys.exit("[musica] PIL not found")

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
        print(f"[temp] failed: {e}")
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
        print(f"[recipe] error reading {RECIPE_FILE}: {e}")
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
        print("[recipe] active file has no valid title/lines")
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

        # No exact match: fall back to the first result
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
        print(f"[deezer] error: {e}")
    return imgs


def fit_fill(img, w, h):
    """Resize and crop the image to fill w x h (cover)."""
    ratio = max(w / img.width, h / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def _brighten(c, target=235):
    """Raise the color brightness while keeping the hue, for legibility on a dark scrim."""
    mx = max(c) or 1
    f = target / mx
    return tuple(min(255, int(v * f)) for v in c)


def dominant_color(img, default=ACCENT_YELLOW):
    """Extract the cover accent color: the most frequent one that is neither dark nor gray."""
    try:
        small = img.convert("RGB").resize((80, 80))
        q = small.quantize(colors=8, method=Image.FASTOCTREE)
        pal = q.getpalette()
        for count, idx in sorted(q.getcolors(), reverse=True):
            r, g, b = pal[idx * 3: idx * 3 + 3]
            if max(r, g, b) < 60:                  # too dark
                continue
            if max(r, g, b) - min(r, g, b) < 40:   # too gray
                continue
            return _brighten((r, g, b))
    except Exception as e:
        print(f"[color] fallback: {e}")
    return default


def blurred_background(img, blur=38, darken=70):
    """Cinematic background: full-screen cover, heavy blur and a dark veil."""
    bg = fit_fill(img.copy(), IMG_W, IMG_H).filter(ImageFilter.GaussianBlur(blur))
    canvas = bg.convert("RGBA")
    canvas.alpha_composite(Image.new("RGBA", (IMG_W, IMG_H), (8, 8, 14, darken)))
    return canvas


def rounded_card(canvas, img, box, radius=24, shadow_blur=24, accent=None):
    """Paste the image as a rounded card with a drop shadow and a subtle border."""
    x, y, w, h = box
    card = fit_fill(img.copy(), w, h).convert("RGBA")

    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)

    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle(
        [x - 6, y + 10, x + w + 6, y + h + 14], radius=radius + 6, fill=(0, 0, 0, 180))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(shadow_blur)))

    canvas.paste(card, (x, y), mask)
    border = accent + (110,) if accent else (255, 255, 255, 55)
    ImageDraw.Draw(canvas, "RGBA").rounded_rectangle(
        [x, y, x + w - 1, y + h - 1], radius=radius, outline=border, width=2)


def draw_soft_text(canvas, pos, text, font, fill=(255, 255, 255),
                   shadow_alpha=190, blur=6, offset=(0, 3)):
    """Text with a real (blurred layer) shadow instead of a hard pixel shadow."""
    x, y = pos
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + offset[0], y + offset[1]), text, font=font,
                            fill=(0, 0, 0, shadow_alpha))
    canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))
    if len(fill) == 3:
        fill = fill + (255,)
    ImageDraw.Draw(canvas, "RGBA").text((x, y), text, font=font, fill=fill)


def ellipsize(text, font, max_w):
    """Truncate the text with an ellipsis if it exceeds max_w."""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if probe.textlength(text, font=font) <= max_w:
        return text
    while text and probe.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return (text.rstrip() + "…") if text else ""


# "Two squares" layout: cover and (optional) recipe side by side, same size.
SQUARE = 650          # square side length
SQUARE_Y = 150        # top of the squares (below the clock)
SQUARE_GAP = 70       # gap between cover and recipe


def draw_clock(canvas, accent, current_temp):
    draw = ImageDraw.Draw(canvas, "RGBA")
    DIAS = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sab", "Dom"]
    now = datetime.datetime.now()
    hora = now.strftime("%H:%M")
    data_lbl = f"{DIAS[now.weekday()]}, {now.day}"
    f_hora = get_font(True, 78)
    f_data = get_font(False, 42)
    hora_w = draw.textlength(hora, font=f_hora)
    draw_soft_text(canvas, (48, 30), hora, f_hora)
    draw_soft_text(canvas, (48 + hora_w + 24, 52), data_lbl, f_data, fill=(225, 225, 225))
    if current_temp is not None:
        data_w = draw.textlength(data_lbl, font=f_data)
        draw_soft_text(canvas, (48 + hora_w + 24 + data_w + 18, 52),
                       f"{round(current_temp)}°", get_font(True, 42), fill=accent)


def centered_text(canvas, cx, y, text, font, fill, blur=6):
    w = ImageDraw.Draw(canvas).textlength(text, font=font)
    draw_soft_text(canvas, (int(cx - w / 2), y), text, font, fill=fill, blur=blur)


def draw_bottom_bar(canvas, accent, artist, title, album):
    """Bottom black bar with a centered 'now playing' label."""
    draw = ImageDraw.Draw(canvas, "RGBA")
    for i in range(220):
        a = int(205 * (i / 220) ** 1.3)
        draw.rectangle([(0, IMG_H - 220 + i), (IMG_W, IMG_H - 220 + i + 1)], fill=(0, 0, 0, a))
    cx, yb = IMG_W // 2, IMG_H - 168
    sub = f"{title}  ·  {album}" if (title and album) else (title or album)
    centered_text(canvas, cx, yb, "♫ TOCANDO AGORA", get_font(False, 24), accent, blur=4)
    centered_text(canvas, cx, yb + 34, ellipsize(artist, get_font(True, 50), IMG_W - 120),
                  get_font(True, 50), (255, 255, 255), blur=6)
    if sub:
        centered_text(canvas, cx, yb + 98, ellipsize(sub, get_font(False, 30), IMG_W - 120),
                      get_font(False, 30), (224, 224, 224))


def fit_recipe(probe, recipe, max_w, max_h):
    """Largest font size (31 to 20) at which title + wrapped lines fit the height."""
    for body in range(31, 19, -1):
        title_px = int(body * 1.32)
        bf = get_font(False, body)
        line_h = int(body * 1.55)
        wrapped = []
        for ln in recipe["lines"]:
            wrapped += wrap_line(probe, "•  " + ln, bf, max_w)
        if int(title_px * 1.7) + len(wrapped) * line_h <= max_h:
            return get_font(True, title_px), bf, line_h, title_px, wrapped
    # 20px floor: still overflowing, so truncate and mark the remainder
    body = 20
    title_px = int(body * 1.32)
    bf = get_font(False, body)
    line_h = int(body * 1.55)
    wrapped = []
    for ln in recipe["lines"]:
        wrapped += wrap_line(probe, "•  " + ln, bf, max_w)
    fit = max((max_h - int(title_px * 1.7)) // line_h - 1, 0)
    extra = len(wrapped) - fit
    return get_font(True, title_px), bf, line_h, title_px, wrapped[:fit] + [f"… +{extra} passos"]


def draw_recipe_square(canvas, box, recipe, accent):
    x, y, w, h = box
    ImageDraw.Draw(canvas, "RGBA").rounded_rectangle(
        [x, y, x + w, y + h], radius=26, fill=(0, 0, 0, 150),
        outline=accent + (120,), width=2)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    pad = 38
    tf, bf, line_h, title_px, lines = fit_recipe(probe, recipe, w - 2 * pad, h - 2 * pad)
    px, py = x + pad, y + 30
    draw_soft_text(canvas, (px, py), recipe["title"], tf, fill=(255, 255, 255))
    py += int(title_px * 1.7)
    for ln in lines:
        draw_soft_text(canvas, (px, py), ln, bf, fill=(238, 238, 238), blur=4)
        py += line_h


def make_frame(bg_img, artist, title, album="", current_temp=None):
    accent = dominant_color(bg_img)
    canvas = blurred_background(bg_img, blur=46, darken=110)
    draw = ImageDraw.Draw(canvas, "RGBA")

    # Soft top scrim behind the clock
    for i in range(110):
        draw.rectangle([(0, i), (IMG_W, i + 1)], fill=(0, 0, 0, int(130 * (1 - i / 110))))
    draw_clock(canvas, accent, current_temp)

    recipe = load_recipe_overlay()
    if recipe:
        # Two equal squares: cover (left) + recipe (right)
        lx = (IMG_W - (2 * SQUARE + SQUARE_GAP)) // 2
        rounded_card(canvas, bg_img, (lx, SQUARE_Y, SQUARE, SQUARE), radius=26, accent=accent)
        draw_recipe_square(canvas, (lx + SQUARE + SQUARE_GAP, SQUARE_Y, SQUARE, SQUARE),
                           recipe, accent)
    else:
        # No recipe: centered cover
        cx = (IMG_W - SQUARE) // 2
        rounded_card(canvas, bg_img, (cx, SQUARE_Y, SQUARE, SQUARE), radius=26, accent=accent)

    draw_bottom_bar(canvas, accent, artist, title, album)

    canvas.convert("RGB").save(TMP_FILE, "JPEG", quality=92)
    os.replace(TMP_FILE, OUT_FILE)


running = True


def stop(sig, frame):
    global running
    print("[musica] signal received, shutting down...")
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

    # 1. Album art from the public YouTube Music URL (entity_picture).
    # If the current cover exists, use only that. This avoids cycling to poor
    # artist/fallback images while a correct cover is available.
    if entity_pic.startswith("http"):
        ep = entity_pic.replace("w544-h544", "w1920-h1080").replace("size=512", "size=1080")
        img = fetch_image(ep)
        if img:
            images = [img]
            image_source = "album art"
            print("[img] album art ok; using only the current cover")

    # 2. YouTube thumbnail (maxres or hq), only if the cover failed.
    if not images and video_id:
        for q in ["maxresdefault", "hqdefault"]:
            img = fetch_image(f"https://img.youtube.com/vi/{video_id}/{q}.jpg")
            if img:
                # Skip the generic YouTube thumbnail (all black/gray)
                arr = list(img.getdata())
                if len(set(arr[::500])) > 10:
                    images = [img]
                    image_source = f"youtube {q}"
                    print(f"[img] youtube {q} ok")
                    break

    # 3. Artist images from Deezer, only if cover and YouTube both failed.
    if not images:
        images = fetch_deezer_images(artist, max_images=4)
        if images:
            image_source = "deezer artist"

    if not images:
        print("[musica] no images, using fallback")
        fb = Image.new("RGB", (IMG_W, IMG_H), (15, 15, 25))
        images = [fb]

    print(f"[musica] {len(images)} image(s), source={image_source}, cycle {INTERVAL}s")

    idx = 0

    while running:
        if time.time() - temp_time > 1800:
            current_temp = fetch_current_temp()
            temp_time = time.time()
        try:
            make_frame(images[idx % len(images)], artist, title, album, current_temp)
        except Exception as e:
            print(f"[musica] frame error: {e}")
        idx += 1
        for _ in range(INTERVAL):
            if not running:
                break
            time.sleep(1)

    print("[musica] stopped.")


if __name__ == "__main__":
    main()
