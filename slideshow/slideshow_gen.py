import os
#!/usr/bin/env python3
import json, random, os, time, urllib.request, datetime

FOTOS_DIR  = "/media/media/Picures"
OUT_FILE   = "/config/www/current.jpg"
TMP_IMG    = "/config/www/.current_tmp.jpg"
FOTOS_JSON = "/media/media/Picures/fotos.json"
LAT, LON   = float(os.environ.get("WEATHER_LAT","40.7128")), float(os.environ.get("WEATHER_LON","-74.0060"))  # defina suas coordenadas
INTERVAL   = 25

FONT_DIR  = "/usr/local/lib/python3.14/site-packages/aioslimproto/font"
FONT_BOLD = os.path.join(FONT_DIR, "DejaVu-Sans-Bold.ttf")
FONT_REG  = os.path.join(FONT_DIR, "DejaVu-Sans.ttf")

from PIL import Image, ImageDraw, ImageFont
from PIL.ExifTags import TAGS, GPSTAGS

def get_font(bold=False, size=48):
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)
    except:
        return ImageFont.load_default()

WMO = {
    0:"Ceu limpo", 1:"Princ. limpo", 2:"Parc. nublado", 3:"Nublado",
    45:"Nevoa", 51:"Garoa leve", 61:"Chuva leve", 63:"Chuva moderada",
    65:"Chuva forte", 80:"Pancadas leves", 81:"Pancadas mod.",
    82:"Pancadas fortes", 95:"Trovoada", 96:"Trovoada c/ granizo",
}

def fetch_weather():
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
        f"&current=temperature_2m"
        f"&timezone=America%2FSao_Paulo&forecast_days=3"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
        print(f"[clima] ok: {data['daily']['weathercode']}")
        return data
    except Exception as e:
        print(f"[clima] falhou: {e}")
        return None

def shadow_white(draw, pos, text, font):
    x, y = pos
    for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2),(0,3),(3,0),(-3,0),(0,-3)]:
        draw.text((x+dx, y+dy), text, font=font, fill=(0,0,0,200))
    draw.text((x, y), text, font=font, fill=(255,255,255))

def shadow_yellow(draw, pos, text, font):
    x, y = pos
    for dx, dy in [(-2,-2),(2,-2),(-2,2),(2,2),(0,3),(3,0),(-3,0),(0,-3)]:
        draw.text((x+dx, y+dy), text, font=font, fill=(0,0,0,200))
    draw.text((x, y), text, font=font, fill=(255, 220, 60))

# ── EXIF + Reverse Geocoding ────────────────────────────────────────────────

_geocache = {}

def _dms_to_decimal(dms, ref):
    try:
        d, m, s = float(dms[0]), float(dms[1]), float(dms[2])
        val = d + m / 60 + s / 3600
        if ref in ('S', 'W'):
            val = -val
        return val
    except Exception:
        return None

def reverse_geocode(lat, lon):
    key = (round(lat, 1), round(lon, 1))
    if key in _geocache:
        return _geocache[key]
    try:
        url = (
            f"https://api.bigdatacloud.net/data/reverse-geocode-client"
            f"?latitude={lat}&longitude={lon}&localityLanguage=pt"
        )
        with urllib.request.urlopen(url, timeout=8) as r:
            data = json.loads(r.read())
        city = (
            data.get("locality") or
            data.get("city") or
            data.get("principalSubdivision") or ""
        )
        _geocache[key] = city
        print(f"[geo] {lat:.2f},{lon:.2f} → {city}")
        return city
    except Exception as e:
        print(f"[geo] falhou: {e}")
        _geocache[key] = ""
        return ""

def get_photo_meta(foto_path):
    """Returns (date_str, city_str, folder_name). Empty strings if unavailable."""
    date_str = ""
    city_str = ""
    folder_name = os.path.basename(os.path.dirname(foto_path.rstrip(os.sep)))
    try:
        img = Image.open(foto_path)
        # Suporta _getexif() legado e getexif() novo
        try:
            raw_exif = img._getexif()
        except Exception:
            raw_exif = None
        if raw_exif is None:
            try:
                raw_exif = dict(img.getexif())
            except Exception:
                raw_exif = None
        img.close()

        if not raw_exif:
            return date_str, city_str, folder_name

        for tag_id, value in raw_exif.items():
            tag_name = TAGS.get(tag_id, "")

            if tag_name == "DateTimeOriginal" and not date_str:
                try:
                    dt = datetime.datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                    date_str = dt.strftime("%d/%m/%Y")
                except Exception:
                    pass

            elif tag_name == "GPSInfo" and not city_str:
                try:
                    gps = {GPSTAGS.get(k, k): v for k, v in value.items()}
                    lat = _dms_to_decimal(gps.get("GPSLatitude", (0,0,0)),
                                          gps.get("GPSLatitudeRef", "N"))
                    lon = _dms_to_decimal(gps.get("GPSLongitude", (0,0,0)),
                                          gps.get("GPSLongitudeRef", "E"))
                    if lat is not None and lon is not None:
                        city_str = reverse_geocode(lat, lon)
                except Exception as e:
                    print(f"[meta-gps] {e}")

    except Exception as e:
        print(f"[meta] {foto_path}: {e}")

    return date_str, city_str, folder_name

# ── Composite ───────────────────────────────────────────────────────────────

def make_composite(foto_path, weather, photo_meta=("", "")):
    img = Image.open(foto_path).convert("RGB")
    img.thumbnail((1920, 1080), Image.LANCZOS)
    canvas = Image.new("RGB", (1920, 1080), (0, 0, 0))
    canvas.paste(img, ((1920 - img.width) // 2, (1080 - img.height) // 2))
    draw = ImageDraw.Draw(canvas, "RGBA")

    for i in range(180):
        draw.line([(0, i), (1920, i)], fill=(0, 0, 0, int(150*(1-i/180))))
    for i in range(180):
        draw.line([(0, 900+i), (1920, 900+i)], fill=(0, 0, 0, int(170*(i/180))))

    DIAS = ["Seg","Ter","Qua","Qui","Sex","Sab","Dom"]
    now  = datetime.datetime.now()
    hora = now.strftime("%H:%M")
    data = f"{DIAS[now.weekday()]}, {now.day}"

    f_hora = get_font(bold=True,  size=78)
    f_data = get_font(bold=False, size=42)
    shadow_white(draw, (48, 30), hora, f_hora)
    hora_w = draw.textlength(hora, font=f_hora)
    shadow_white(draw, (48 + hora_w + 24, 52), data, f_data)
    if weather and "current" in weather:
        temp_str = f"{round(weather['current']['temperature_2m'])}°"
        f_temp = get_font(bold=True, size=42)
        data_w = draw.textlength(data, font=f_data)
        shadow_white(draw, (48 + hora_w + 24 + data_w + 18, 52), temp_str, f_temp)

    # ── Superior direito: data + cidade da foto ──────────────────────────
    date_taken, city, folder_name = (photo_meta + ("", "", ""))[:3]
    if date_taken or city or folder_name:
        f_meta_city = get_font(bold=True,  size=34)
        f_meta_date = get_font(bold=False, size=28)
        f_meta_folder = get_font(bold=False, size=24)
        PAD_RIGHT = 48
        y = 30
        if city:
            w = draw.textlength(city, font=f_meta_city)
            shadow_white(draw, (1920 - w - PAD_RIGHT, y), city, f_meta_city)
            y += 44
        if date_taken:
            w = draw.textlength(date_taken, font=f_meta_date)
            shadow_white(draw, (1920 - w - PAD_RIGHT, y), date_taken, f_meta_date)
            y += 36
        if folder_name:
            w = draw.textlength(folder_name, font=f_meta_folder)
            shadow_white(draw, (1920 - w - PAD_RIGHT, y), folder_name, f_meta_folder)

    if weather:
        d = weather["daily"]
        labels = ["Hoje", "Amanha", "Depois"]

        def fonts_for(i):
            if i == 0:
                return get_font(True,27), get_font(True,39), get_font(False,22)
            return get_font(True,22), get_font(True,31), get_font(False,18)

        x_start = 900
        col_w   = 340
        ys = (892, 922, 965)

        for i in range(3):
            x = x_start + i * col_w
            fl, ft, fd = fonts_for(i)
            tmax = round(d["temperature_2m_max"][i])
            tmin = round(d["temperature_2m_min"][i])
            rain = d["precipitation_probability_max"][i]
            desc = WMO.get(d["weathercode"][i], "")
            shadow_yellow(draw, (x, ys[0]), labels[i],                fl)
            shadow_yellow(draw, (x, ys[1]), f"{tmax}° / {tmin}°",     ft)
            shadow_yellow(draw, (x, ys[2]), f"{desc}  {rain}% chuva", fd)

    canvas.save(TMP_IMG, "JPEG", quality=90)
    os.replace(TMP_IMG, OUT_FILE)

def main():
    with open(FOTOS_JSON) as f:
        fotos = json.load(f)
    random.shuffle(fotos)
    idx = 0
    weather = fetch_weather()
    weather_time = time.time() if weather else 0

    while True:
        refresh_interval = 1200 if weather else 60
        if time.time() - weather_time > refresh_interval:
            weather = fetch_weather()
            weather_time = time.time()

        foto = fotos[idx % len(fotos)]
        foto_path = os.path.join(FOTOS_DIR, foto)
        t0 = time.time()
        try:
            photo_meta = get_photo_meta(foto_path)
            make_composite(foto_path, weather, photo_meta)
            print(f"[{datetime.datetime.now():%H:%M:%S}] {'sem-clima' if not weather else 'ok'} {foto} | meta={photo_meta}")
        except Exception as e:
            print(f"Erro: {e}")

        elapsed = time.time() - t0
        idx += 1
        time.sleep(max(1, INTERVAL - elapsed))

if __name__ == "__main__":
    main()
