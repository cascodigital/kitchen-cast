"""
cozinha — atendente de cozinha.
Lista receitas (fonte live: skcoz/receitas montado RO), recebe instrucoes pro Rolo,
arma a receita no HASS (modo musica) e delega a curadoria da playlist ao claude-worker.
User escolhe a receita, manda, ve o link da playlist pronta e da play.
"""
import os
import re
import glob
import time
import uuid
import shlex
import random
import threading
import unicodedata

import requests
import docker
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse

RECIPES_DIR = os.environ.get("RECIPES_DIR", "/recipes")
HASS_URL = os.environ.get("HASS_URL", "http://homeassistant.local:8123").rstrip("/")
HASS_TOKEN = os.environ.get("HASS_TOKEN", "")
WORKER = os.environ.get("WORKER_CONTAINER", "claude-worker")
YTM_MCP = os.environ.get("YTM_MCP_CONFIG", "/home/claude/ai/mcp/youtube-music/mcp-config.json")
MAX_TV_LINES = int(os.environ.get("MAX_TV_LINES", "12"))
YTM_AUTH_FILE = os.environ.get("YTM_AUTH_FILE", "/auth/ytmusic_auth.json")
QUICK_COUNT = int(os.environ.get("QUICK_COUNT", "5"))

app = FastAPI(title="cozinha")

# estado em memoria (1 worker uvicorn, 1 usuario)
JOBS = {}                      # job_id -> dict
PENDING_RECIPE = {"json": None}  # ultima receita armada, servida ao HASS via curl
_PL_CACHE = {"ts": 0, "items": []}  # cache da biblioteca de playlists do YT Music


# ---------------------------------------------------------------- playlists existentes
def get_existing_playlists():
    """Lista playlists tocaveis da biblioteca (cache 10min). Degrada para [] em erro."""
    if time.time() - _PL_CACHE["ts"] < 600 and _PL_CACHE["items"]:
        return _PL_CACHE["items"]
    try:
        from ytmusicapi import YTMusic
        yt = YTMusic(YTM_AUTH_FILE)
        items = []
        for p in yt.get_library_playlists(limit=200):
            pid = p.get("playlistId", "")
            title = p.get("title", "")
            # so playlists reais (PL...); fora Liked Music (LM), Episodes (SE), etc.
            if pid.startswith("PL") and title:
                items.append({"id": pid, "title": title})
        _PL_CACHE["ts"] = time.time()
        _PL_CACHE["items"] = items
        return items
    except Exception:
        return _PL_CACHE["items"]  # ultima boa, ou [] se nunca carregou


def quick_picks(n=QUICK_COUNT):
    items = get_existing_playlists()
    if not items:
        return []
    return random.sample(items, min(n, len(items)))


# ---------------------------------------------------------------- receitas
def prettify(rid: str) -> str:
    return rid.replace("_", " ").strip().title()


def emoji_for(rid: str) -> str:
    r = rid.lower()
    table = [
        (("bolo", "brownie", "cookie", "biscoito", "waffle", "doce", "amanteig"), "🍰"),
        (("cafe", "copo", "batido", "suco", "drink", "gelado"), "☕"),
        (("almondega", "carbonara", "massa", "panqueca", "guisado", "macarr"), "🍝"),
        (("salsichao", "linguica", "salsicha", "borrussia"), "🌭"),
        (("coracaozinho", "frango", "galinha", "carne", "bife"), "🍗"),
        (("pao", "pizza", "torta"), "🍞"),
        (("ovo", "omelete"), "🍳"),
    ]
    for keys, emo in table:
        if any(k in r for k in keys):
            return emo
    return "🍽️"


def list_recipes():
    out = []
    for p in sorted(glob.glob(os.path.join(RECIPES_DIR, "*.txt"))):
        rid = os.path.splitext(os.path.basename(p))[0]
        out.append({"id": rid, "title": prettify(rid), "path": p})
    return out


def recipe_path(rid: str):
    p = os.path.join(RECIPES_DIR, rid + ".txt")
    return p if os.path.isfile(p) else None


def recipe_lines(path: str):
    lines = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            s = raw.strip()
            if s.startswith("-"):
                s = s[1:].strip()
            if s:
                lines.append(s)
    return lines


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.lower()


def shorten_tv_line(s: str, max_len=72) -> str:
    s = re.sub(r"\s+", " ", s).strip(" -•\t")
    if len(s) <= max_len:
        return s
    cut = s[:max_len + 1]
    for sep in ("; ", ". ", ", ", " - ", " ("):
        pos = cut.rfind(sep)
        if pos >= 36:
            return cut[:pos].rstrip(" ,;.-(") + "..."
    return s[:max_len - 3].rstrip(" ,;.-") + "..."


def split_tv_section(lines):
    """If the recipe file has a dedicated TV: block, trust it."""
    out = []
    in_tv = False
    for line in lines:
        norm = normalize_text(line).strip(":")
        if norm == "tv":
            in_tv = True
            continue
        if in_tv and norm in {"site", "web", "receita", "notas", "notes"}:
            break
        if in_tv:
            out.append(line)
    return out


INGREDIENT_RE = re.compile(
    r"(^|\b)(\d+([,.]\d+)?|meia|meio|uma|um|duas|dois)\s*"
    r"(g|kg|ml|l|xicar|colher|copo|lata|dente|unidade|pitada|tsp|tbsp|cup|oz|lb)?\b",
    re.I,
)
CRITICAL_WORDS = {
    "forno", "preaquecer", "pre-aquecer", "temperatura", "graus", "c",
    "min", "minuto", "hora", "fogo", "baixo", "medio", "alto",
    "virar", "mexer", "misturar", "bater", "assar", "cozinhar", "ferver",
    "refogar", "descansar", "marinar", "tampar", "destampar",
    "ponto", "teste", "pronto", "dourar", "rosado", "seco", "cremoso",
    "nao", "sem", "evite", "cuidado", "atencao", "risco",
}
NOISE_WORDS = {
    "ingredientes", "modo de preparo", "preparo", "observacoes", "observacao",
    "notas", "nota", "rendimento", "serve", "fonte", "link",
}


def score_tv_line(line: str, index: int):
    norm = normalize_text(line)
    if not norm or norm in NOISE_WORDS or norm.startswith(("http://", "https://")):
        return None

    score = 0
    kind = "other"
    if ":" in line and len(line.split(":", 1)[0]) <= 32:
        score += 25
        kind = "ingredient"
    if INGREDIENT_RE.search(norm):
        score += 30
        kind = "ingredient"
    hits = sum(1 for word in CRITICAL_WORDS if word in norm)
    if hits:
        score += 35 + min(hits, 3) * 8
        kind = "critical"
    if any(ch.isdigit() for ch in line):
        score += 8
    if len(line) > 120:
        score -= 8
    score -= index * 0.05
    return score, kind


def condense_recipe_for_tv(lines, max_lines=MAX_TV_LINES):
    tv_lines = split_tv_section(lines)
    if tv_lines:
        return [shorten_tv_line(s) for s in tv_lines if shorten_tv_line(s)][:max_lines]

    candidates = []
    seen = set()
    for idx, line in enumerate(lines):
        short = shorten_tv_line(line)
        key = normalize_text(short)
        if not short or key in seen:
            continue
        scored = score_tv_line(short, idx)
        if not scored:
            continue
        score, kind = scored
        seen.add(key)
        candidates.append({"line": short, "score": score, "kind": kind, "index": idx})

    ingredients = sorted(
        [c for c in candidates if c["kind"] == "ingredient"],
        key=lambda c: (-c["score"], c["index"]),
    )[: max_lines // 2]
    critical = sorted(
        [c for c in candidates if c["kind"] == "critical"],
        key=lambda c: (-c["score"], c["index"]),
    )[: max_lines - len(ingredients)]

    chosen = {id(c): c for c in ingredients + critical}
    if len(chosen) < max_lines:
        for c in sorted(candidates, key=lambda c: (-c["score"], c["index"])):
            chosen[id(c)] = c
            if len(chosen) >= max_lines:
                break

    return [c["line"] for c in sorted(chosen.values(), key=lambda c: c["index"])[:max_lines]]


def build_recipe_json(rid: str, path: str):
    lines = recipe_lines(path)
    return {
        "enabled": True,
        "title": prettify(rid).upper(),
        "lines": condense_recipe_for_tv(lines),
    }


# ---------------------------------------------------------------- HASS arm
def hass_call(domain: str, service: str, data=None):
    r = requests.post(
        f"{HASS_URL}/api/services/{domain}/{service}",
        headers={"Authorization": f"Bearer {HASS_TOKEN}"},
        json=data or {},
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def arm_recipe(recipe_json: dict):
    # 1) deixa a receita pendente para o HASS puxar via curl
    PENDING_RECIPE["json"] = recipe_json
    # 2) HASS faz curl do /api/pending_recipe -> /config/music_recipe.json
    hass_call("shell_command", "fetch_music_recipe")
    time.sleep(1.5)
    # 3) liga gate + inicia janela de 30min
    hass_call("input_boolean", "turn_on", {"entity_id": "input_boolean.recipe_armed"})
    hass_call("timer", "start", {"entity_id": "timer.skcoz_recipe_window"})


# ---------------------------------------------------------------- playlist (IA)
PLAYLIST_TOOLS = (
    "mcp__youtube-music__search_songs,"
    "mcp__youtube-music__get_recommendations,"
    "mcp__youtube-music__create_playlist,"
    "mcp__youtube-music__add_playlist_items"
)
URL_RE = re.compile(r"https://music\.youtube\.com/playlist\?list=[\w-]+")
ID_RE = re.compile(r"\b((?:PL|VL|RDCL)[\w-]{10,}|list=([\w-]{10,}))\b")


def make_playlist(title: str, instructions: str) -> str:
    vibe = instructions.strip() or "escolha pela vibe da receita e pela hora do dia"
    prompt = (
        f"Voce e o Rolo, DJ. Crie UMA playlist no YouTube Music para cozinhar '{title}'. "
        f"Vibe pedida: {vibe}. "
        "Use mcp__youtube-music__search_songs e get_recommendations para escolher ~15 faixas coerentes "
        "com a vibe pedida e o historico musical disponivel; respeite o pedido do usuario. "
        f"Crie com mcp__youtube-music__create_playlist (titulo 'Cozinha: {title}') e adicione as faixas "
        "com add_playlist_items. Ao terminar responda SOMENTE a URL no formato "
        "https://music.youtube.com/playlist?list=<id> , nada mais."
    )
    bash = (
        "cd ~ && timeout 280 claude -p "
        + shlex.quote(prompt)
        + f" --mcp-config {shlex.quote(YTM_MCP)} --dangerously-skip-permissions --allowedTools {PLAYLIST_TOOLS}"
    )
    dcli = docker.from_env()
    container = dcli.containers.get(WORKER)
    res = container.exec_run(["bash", "-lc", bash], user="claude", demux=False)
    out = (res.output or b"").decode("utf-8", "replace")

    m = URL_RE.search(out)
    if m:
        return m.group(0)
    m = ID_RE.search(out)
    if m:
        pid = m.group(2) or m.group(1)
        return f"https://music.youtube.com/playlist?list={pid}"
    raise RuntimeError("playlist URL nao encontrada no output do worker:\n" + out[-800:])


# ---------------------------------------------------------------- job runner
def run_job(job_id: str):
    job = JOBS[job_id]
    try:
        job["step"] = "armando receita na TV..."
        arm_recipe(job["recipe_json"])
        job["armed"] = True

        job["step"] = "Rolo montando a playlist (pode levar ~1-2 min)..."
        url = make_playlist(job["title"], job["instructions"])
        job["playlist_url"] = url
        job["step"] = "pronto"
        job["status"] = "done"
    except Exception as e:  # noqa
        job["status"] = "error"
        job["error"] = str(e)
        job["step"] = "falhou"


# ---------------------------------------------------------------- HTML
PAGE_HEAD = """
<meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1,viewport-fit=cover'>
<meta name=theme-color content='#17120f'>
<link rel=preconnect href='https://fonts.googleapis.com'>
<link rel=preconnect href='https://fonts.gstatic.com' crossorigin>
<link href='https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap' rel=stylesheet>
<style>
:root{
  color-scheme:dark;
  --bg:#17120f; --card:#221b16; --card2:#2a2019; --line:#3a2e25;
  --cream:#f5ede1; --muted:#b3a294; --honey:#f5b13d; --honey2:#ffce6b;
  --coral:#ff5d4e; --grape:#c2a9ff; --grape-bg:#241d2f; --grape-line:#3c3052;
  --serif:'Fraunces',Georgia,'Times New Roman',serif;
  --sans:'Inter',system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  font-family:var(--sans);margin:0;color:var(--cream);
  background:
    radial-gradient(1100px 480px at 50% -8%, rgba(245,177,61,.14), transparent 60%),
    radial-gradient(700px 400px at 90% 0%, rgba(255,93,78,.08), transparent 55%),
    var(--bg);
  background-attachment:fixed;min-height:100vh;
  line-height:1.5;letter-spacing:.1px;
}
a{-webkit-tap-highlight-color:transparent}
header{
  position:sticky;top:0;z-index:10;
  padding:16px 20px;display:flex;align-items:center;justify-content:space-between;
  background:rgba(23,18,15,.78);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--line);
}
header .brand{font-family:var(--serif);font-weight:700;font-size:21px;letter-spacing:.2px;display:flex;align-items:center;gap:8px}
header .brand .dot{font-size:20px}
header a.nav{color:var(--honey);text-decoration:none;font-size:14px;font-weight:600;opacity:.9}
.wrap{max-width:640px;margin:0 auto;padding:22px 18px calc(40px + env(safe-area-inset-bottom))}
.tagline{font-family:var(--serif);font-size:26px;font-weight:600;margin:6px 0 2px}
.sub{color:var(--muted);font-size:14px;margin:0 0 20px}
.muted{color:var(--muted);font-size:13px}
.ok{color:#86d68a}.err{color:#ff9b90}

/* grid de receitas */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(146px,1fr));gap:13px}
.card{
  position:relative;display:flex;flex-direction:column;gap:8px;
  background:linear-gradient(180deg,var(--card2),var(--card));
  border:1px solid var(--line);border-radius:18px;padding:18px 16px;
  text-decoration:none;color:var(--cream);
  transition:transform .12s ease,border-color .15s ease,box-shadow .15s ease;
  box-shadow:0 1px 0 rgba(255,255,255,.02) inset;
}
.card .emj{font-size:34px;line-height:1}
.card .ttl{font-weight:600;font-size:15.5px}
.card .go{color:var(--muted);font-size:12px;margin-top:auto}
.card:hover{transform:translateY(-3px);border-color:rgba(245,177,61,.55);box-shadow:0 10px 26px -14px rgba(245,177,61,.4)}
.card:active{transform:scale(.98)}

/* pagina da receita */
.back{display:inline-block;color:var(--muted);text-decoration:none;font-size:14px;margin-bottom:10px}
.rtitle{font-family:var(--serif);font-weight:700;font-size:30px;line-height:1.1;margin:2px 0 16px;display:flex;align-items:center;gap:12px}
.rtitle .emj{font-size:30px}
.ficha{
  background:linear-gradient(180deg,#241d17,#1f1813);
  border:1px solid var(--line);border-radius:16px;padding:6px 18px;margin:0 0 26px;
  box-shadow:0 16px 40px -28px rgba(0,0,0,.8);
}
.ficha ul{list-style:none;margin:0;padding:0}
.ficha li{padding:11px 0;border-bottom:1px solid rgba(255,255,255,.05);font-size:15px;padding-left:18px;position:relative}
.ficha li:last-child{border-bottom:0}
.ficha li::before{content:'';position:absolute;left:0;top:18px;width:6px;height:6px;border-radius:50%;background:var(--honey);opacity:.8}
.section{font-family:var(--serif);font-size:19px;font-weight:600;margin:0 0 6px;display:flex;align-items:center;gap:8px}
label.lbl{display:block;color:var(--muted);font-size:13.5px;margin:0 0 9px}
textarea{
  width:100%;min-height:88px;resize:vertical;background:#1b1510;color:var(--cream);
  border:1px solid var(--line);border-radius:14px;padding:13px 14px;font:inherit;font-size:16px;
  transition:border-color .15s,box-shadow .15s;
}
textarea::placeholder{color:#7c6e60}
textarea:focus{outline:0;border-color:var(--honey);box-shadow:0 0 0 3px rgba(245,177,61,.18)}
button{
  width:100%;margin-top:13px;padding:16px;border:0;border-radius:14px;cursor:pointer;
  background:linear-gradient(180deg,var(--honey2),var(--honey));color:#2a1d05;
  font:inherit;font-size:16.5px;font-weight:700;letter-spacing:.2px;
  box-shadow:0 10px 24px -12px rgba(245,177,61,.7);transition:transform .1s,filter .15s;
}
button:hover{filter:brightness(1.04)}
button:active{transform:scale(.985)}
.or{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:12px;margin:26px 0 12px;text-transform:uppercase;letter-spacing:.14em}
.or::before,.or::after{content:'';flex:1;height:1px;background:var(--line)}

/* atalhos de playlist */
.quickwrap{display:flex;flex-direction:column;gap:9px}
.quick{
  display:flex;align-items:center;gap:13px;
  background:var(--grape-bg);border:1px solid var(--grape-line);border-radius:13px;
  padding:12px 14px;color:#ece4ff;text-decoration:none;font-weight:600;font-size:15px;
  transition:transform .1s,border-color .15s,background .15s;
}
.quick .pb{flex:none;width:34px;height:34px;border-radius:50%;display:grid;place-items:center;
  background:linear-gradient(180deg,#7c5cff,#5e3fe0);color:#fff;font-size:13px;box-shadow:0 6px 14px -6px rgba(124,92,255,.8)}
.quick .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.quick .ch{color:var(--grape);opacity:.6}
.quick:hover{border-color:rgba(124,92,255,.6);background:#28203a}
.quick:active{transform:scale(.99)}

/* status / cook */
.statebox{
  background:linear-gradient(180deg,var(--card2),var(--card));border:1px solid var(--line);
  border-radius:18px;padding:26px 20px;text-align:center;
}
.spinner{width:54px;height:54px;margin:4px auto 16px;border-radius:50%;
  border:5px solid rgba(245,177,61,.16);border-top-color:var(--honey);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.statebox .step{font-size:15.5px;color:var(--cream)}
.hint{color:var(--muted);font-size:13px;margin-top:14px}
.result{margin-top:14px}
.done-emoji{font-size:40px}
.play{
  display:flex;align-items:center;justify-content:center;gap:10px;
  background:linear-gradient(180deg,#ff6f60,var(--coral));color:#fff;
  padding:17px;border-radius:15px;text-decoration:none;font-weight:700;font-size:17.5px;margin-top:14px;
  box-shadow:0 14px 30px -12px rgba(255,93,78,.7);transition:transform .1s,filter .15s;
}
.play:hover{filter:brightness(1.05)}
.play:active{transform:scale(.985)}
.badge{display:inline-flex;align-items:center;gap:6px;background:rgba(134,214,138,.12);color:#9bdd9e;
  border:1px solid rgba(134,214,138,.3);border-radius:999px;padding:6px 12px;font-size:13px;font-weight:600;margin-top:6px}
</style>
"""


def page(title, body, show_nav=True):
    nav = "<a class=nav href='/'>↺ receitas</a>" if show_nav else "<span></span>"
    return HTMLResponse(
        f"<!doctype html><html lang=pt><head>{PAGE_HEAD}<title>{title}</title></head><body>"
        f"<header><div class=brand><span class=dot>🍳</span> cozinha</div>{nav}</header>"
        f"<div class=wrap>{body}</div></body></html>"
    )


@app.get("/", response_class=HTMLResponse)
def home():
    cards = "".join(
        f"<a class=card href='/r/{r['id']}'>"
        f"<span class=emj>{emoji_for(r['id'])}</span>"
        f"<span class=ttl>{r['title']}</span>"
        f"<span class=go>ver receita →</span></a>"
        for r in list_recipes()
    )
    return page(
        "cozinha",
        "<h1 class=tagline>O que vai pra panela hoje?</h1>"
        "<p class=sub>Escolhe a receita — eu armo ela na TV e o Rolo cuida da trilha.</p>"
        f"<div class=grid>{cards}</div>",
        show_nav=False,
    )


@app.get("/r/{rid}", response_class=HTMLResponse)
def recipe_view(rid: str):
    p = recipe_path(rid)
    if not p:
        return page("?", "<p class=err>Receita nao encontrada.</p>")
    lines = recipe_lines(p)
    ficha = "".join(f"<li>{line}</li>" for line in lines)
    picks = quick_picks()
    quick_html = ""
    if picks:
        links = "".join(
            f"<a class=quick href='/quick?rid={rid}&list={pk['id']}'>"
            f"<span class=pb>▶</span><span class=nm>{pk['title']}</span><span class=ch>›</span></a>"
            for pk in picks
        )
        quick_html = (
            "<div class=or>ou toca já uma</div>"
            "<p class=muted style='margin:-2px 0 12px'>Arma a receita e abre a playlist na hora — sem esperar o Rolo.</p>"
            f"<div class=quickwrap>{links}</div>"
        )
    return page(
        prettify(rid),
        "<a class=back href='/'>← receitas</a>"
        f"<h1 class=rtitle><span class=emj>{emoji_for(rid)}</span>{prettify(rid)}</h1>"
        f"<div class=ficha><ul>{ficha}</ul></div>"
        "<h2 class=section>🎧 Trilha sonora</h2>"
        "<form method=post action='/cook'>"
        f"<input type=hidden name=rid value='{rid}'>"
        "<label class=lbl>Vibe pro Rolo — deixa vazio e ele escolhe pela receita e pela hora:</label>"
        "<textarea name=instructions placeholder='ex: rock anos 2000 pra animar, ou algo calmo pra um domingo'></textarea>"
        "<button type=submit>Enviar — armar receita + montar playlist nova</button>"
        "</form>"
        f"{quick_html}",
    )


@app.get("/quick")
def quick(rid: str, list: str):
    p = recipe_path(rid)
    if not p:
        return page("?", "<p class=err>Receita nao encontrada.</p>")
    try:
        arm_recipe(build_recipe_json(rid, p))  # arme rapido; se falhar, ainda deixa tocar
    except Exception:
        pass
    return RedirectResponse(f"https://music.youtube.com/playlist?list={list}", status_code=302)


@app.post("/cook", response_class=HTMLResponse)
def cook(rid: str = Form(...), instructions: str = Form("")):
    p = recipe_path(rid)
    if not p:
        return page("?", "<p class=err>Receita nao encontrada.</p>")
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {
        "status": "running",
        "step": "iniciando...",
        "title": prettify(rid),
        "instructions": instructions or "",
        "recipe_json": build_recipe_json(rid, p),
        "playlist_url": None,
        "armed": False,
        "error": None,
    }
    threading.Thread(target=run_job, args=(job_id,), daemon=True).start()
    return page(
        "Preparando...",
        f"<a class=back href='/r/{rid}'>← {prettify(rid)}</a>"
        f"<h1 class=rtitle><span class=emj>{emoji_for(rid)}</span>{prettify(rid)}</h1>"
        "<div class=statebox id=status>"
        "  <div class=spinner id=spin></div>"
        "  <div class=step id=step>iniciando...</div>"
        "  <div class=hint>A receita aparece na TV da cozinha assim que você der play (janela de 30 min).</div>"
        "</div>"
        "<div class=result id=result></div>"
        "<script>"
        f"const jid='{job_id}';"
        "async function tick(){"
        " try{const r=await fetch('/job/'+jid);var j=await r.json();}catch(e){setTimeout(tick,2500);return;}"
        " const step=document.getElementById('step'); if(step) step.textContent=j.step;"
        " if(j.status==='done'){"
        "  document.getElementById('status').innerHTML="
        "   '<div class=done-emoji>🎶</div><div class=step><b>Tudo pronto!</b></div>'"
        "   +(j.armed?'<div class=badge>✓ receita armada na TV</div>':'');"
        "  document.getElementById('result').innerHTML="
        "   '<a class=play href=\"'+j.playlist_url+'\" target=_blank>▶ Abrir playlist e dar PLAY</a>'"
        "   +'<p class=hint>Depois do play na sala, a receita brota na TV da cozinha.</p>';"
        "  return;}"
        " if(j.status==='error'){"
        "  document.getElementById('status').innerHTML="
        "   '<div class=done-emoji>😕</div><div class=step class=err>'+(j.armed?'Receita armada, mas a playlist falhou':'Algo falhou')+'</div>';"
        "  document.getElementById('result').innerHTML='<p class=hint>'+(j.error||'').slice(0,300)+'</p>';"
        "  return;}"
        " setTimeout(tick,2500);}"
        "tick();"
        "</script>",
    )


@app.get("/job/{job_id}")
def job_status(job_id: str):
    j = JOBS.get(job_id)
    if not j:
        return JSONResponse({"status": "error", "step": "job inexistente", "error": "not found"}, 404)
    return {
        "status": j["status"],
        "step": j["step"],
        "playlist_url": j["playlist_url"],
        "armed": j["armed"],
        "error": j["error"],
    }


@app.get("/api/pending_recipe")
def pending_recipe():
    """HASS faz curl daqui para /config/music_recipe.json."""
    if not PENDING_RECIPE["json"]:
        return JSONResponse({"error": "nenhuma receita pendente"}, 404)
    return JSONResponse(PENDING_RECIPE["json"])


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    return "ok"
