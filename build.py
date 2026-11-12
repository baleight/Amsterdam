#!/usr/bin/env python3
"""Genera sito/index.html dall'itinerario markdown + luoghi.json + opere.json.
Genera anche mangiare.csv / mangiare.kml da importare in Google My Maps.
Nessuna dipendenza esterna.

Uso:  python build.py

Sintassi extra nel .md (leggibile anche in Obsidian):
  | ↳ 10:00-12:00 · Se piove | testo |   riga alternativa allo slot sopra (pulsante ⇄)
  #### Piano A — Etichetta · sottotitolo    piani alternativi dell'intera giornata
  [[mangiare]]                              pulsante che apre la scheda Mangiare
  **Nome luogo** in grassetto               se è in luoghi.json → pulsanti Maps/Citymapper
                                            (+ galleria opere se il luogo è in opere.json)
"""
import csv
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote, unquote

HERE = Path(__file__).resolve().parent
SRC = next(HERE.parent.glob("Itinerario Amsterdam*.md"))
OUT = HERE / "index.html"

LDATA = json.loads((HERE / "luoghi.json").read_text(encoding="utf-8"))
LUOGHI = LDATA["luoghi"]
MYMAPS_MID = LDATA.get("mymaps_mid", "").strip()
UNICA_MID = LDATA.get("mymaps_unica_mid", "").strip()
OPERE = {k: v for k, v in json.loads((HERE / "opere.json").read_text(encoding="utf-8")).items() if not k.startswith("_")}

KNMI = "https://www.knmi.nl/nederland-nu/weer/verwachtingen"

CATS = [  # chiave, etichetta, icona, colore, icona KML
    ("ristorante", "Ristoranti", "🍽️", "#c8501e", "red"),
    ("street-food", "Street food", "🍟", "#d99a00", "ylw"),
    ("mercato", "Mercati", "🧺", "#2e8b57", "grn"),
    ("supermercato", "Supermercati", "🛒", "#2a6fdb", "blu"),
    ("dolci-caffè", "Dolci e caffè", "🍰", "#b0459a", "purple"),
]
CAT = {c[0]: c for c in CATS}

VCATS = [  # mappa visite: chiave, etichetta, icona, colore, icona KML, id luoghi
    ("museo", "Musei", "🖼️", "#c8501e", "red",
     ["vgm", "rijks", "stedelijk", "rembrandthuis", "olhos", "moco"]),
    ("luogo", "Luoghi e quartieri", "📌", "#2e8b57", "grn",
     ["museumplein", "concertgebouw", "vondelpark", "spiegel", "bloemenmarkt", "begijnhof", "9straatjes", "westerkerk",
      "annefrank", "brouwersgracht", "dam", "paleis", "oudekerk", "singel7", "nieuwendijk", "nieuwmarkt", "zuiderkerk",
      "staalmeesters", "rembrandtplein", "magerebrug", "nemo", "oba", "adam", "olofssteeg", "damrak"]),
    ("gita", "Gite fuori città", "🚂", "#b0459a", "purple",
     ["inntel", "zaanse", "dekat", "catharina", "klompen"]),
    ("trasporti", "Hotel e trasporti", "🏨", "#2a6fdb", "blu",
     ["hotel", "centraal", "zuid", "schiphol", "zaandam", "zaanse-bus", "zaandijk"]),
]
VCAT_OF = {i: v for v in VCATS for i in v[5]}
VISITE = [p for p in LUOGHI if p["id"] in VCAT_OF]


def mymap(mid, title):
    return (f'<div class="map"><iframe src="https://www.google.com/maps/d/embed?mid={esc(mid)}" '
            f'loading="lazy" title="{esc(title)}" allow="geolocation"></iframe></div>'
            f'<p><a class="eat" href="https://www.google.com/maps/d/viewer?mid={esc(mid)}" target="_blank" rel="noopener">'
            f'🗺️ Apri la mappa a tutto schermo (con la tua posizione)</a></p>')

APPS = [
    ("Citymapper", "🚇", "https://citymapper.com/amsterdam"),
    ("NS treni", "🚆", "https://www.ns.nl/en/journeyplanner/"),
    ("9292", "🗺️", "https://9292.nl/en"),
    ("GVB tram", "🚋", "https://www.gvb.nl/en"),
    ("Google Maps", "📍", "https://www.google.com/maps/dir/?api=1&travelmode=transit"),
    ("Bus 397", "✈️", "https://www.connexxion.nl/en/our-routes/special-routes/amsterdam-airport-express"),
]

# alias → luogo (match esatto o per prefisso del testo in grassetto)
ALIAS = {}
for p in LUOGHI:
    for a in [p["nome"], *p.get("alias", [])]:
        ALIAS.setdefault(a, p)
ALIAS_BY_LEN = sorted(ALIAS, key=len, reverse=True)


def esc(s):
    return html.escape(str(s), quote=True)


def gmaps(p):
    return f'https://www.google.com/maps/dir/?api=1&destination={p["lat"]}%2C{p["lng"]}&travelmode=transit'


def citymapper(p):
    return (f'https://citymapper.com/directions?endcoord={p["lat"]}%2C{p["lng"]}'
            f'&endname={quote(p["nome"])}&endaddress={quote(p.get("indirizzo", ""))}')


def nav_chips(p):
    return (f'<span class="nav"><a class="chip" href="{esc(gmaps(p))}" target="_blank" rel="noopener">📍 Maps</a>'
            f'<a class="chip" href="{esc(citymapper(p))}" target="_blank" rel="noopener">🚇 Citymapper</a></span>')


def commons_thumb(f, w=500):
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(f)}?width={w}"


def commons_page(f):
    return f"https://commons.wikimedia.org/wiki/File:{quote(f.replace(' ', '_'))}"


VIDEO = {}  # le foto e i video dei luoghi ora stanno in "Foto e video.md"


def gallery(pid):
    items = OPERE.get(pid)
    if not items:
        return ""
    foto = all(o.get("foto") for o in items)
    figs = "".join(
        f'<figure><a href="{esc(commons_page(o["file"]))}" target="_blank" rel="noopener">'
        f'<img loading="lazy" src="{esc(commons_thumb(o["file"]))}" alt="{esc(o["titolo"])}"></a>'
        f'<figcaption><b>{esc(o["titolo"])}</b>'
        + ("" if foto else f'<br>{esc(o["autore"])}{", " + esc(o["anno"]) if o.get("anno") else ""}')
        + '</figcaption></figure>'
        for o in items
    )
    video = ""
    if pid in VIDEO:
        video = (f'<p><a class="chip" href="https://www.youtube.com/results?search_query={quote(VIDEO[pid])}" '
                 f'target="_blank" rel="noopener">▶️ Guarda i video su YouTube</a></p>')
    label = f"📷 Foto · {len(items)}" if foto else f"🖼️ Cosa vedrai · {len(items)} opere"
    return f'<details class="gal"><summary>{label}</summary><div class="grid">{figs}</div>{video}</details>'


def match_places(raw):
    found = []
    for b in re.findall(r"\*\*(.+?)\*\*", raw):
        b = b.strip().rstrip(".:,")
        p = ALIAS.get(b)
        if not p:
            for a in ALIAS_BY_LEN:
                if b.startswith(a) and (len(b) == len(a) or not b[len(a)].isalnum()):
                    p = ALIAS[a]
                    break
        if p and p not in found:
            found.append(p)
    return found


# ---------- foto e video di riferimento (dal file "Foto e video.md") ----------
# Sotto "## Nome luogo" una riga per elemento:
#   - https://...                    link (Commons, YouTube, Instagram, TikTok, immagine, altro)
#   - Titolo: https://...            con titolo
#   - [Titolo](https://...)          sintassi markdown
#   - ![[foto.jpg]]                  foto locale (cercata nella cartella del viaggio, copiata in sito/foto/)

MEDIA_MD = HERE.parent / "Foto e video.md"
FOTO_DIR = HERE / "foto"
IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")
VID_EXT = (".mp4", ".mov", ".webm", ".m4v")
MEDIA, MEDIA_WARN = {}, []


def find_place(name):
    n = name.strip().lower()
    return next((p for a, p in ALIAS.items() if a.lower() == n), None)


def classify(url, title=""):
    u = url.strip()
    m = re.match(r"https?://commons\.wikimedia\.org/wiki/File:(.+)$", u)
    if m:
        f = unquote(m.group(1)).replace("_", " ")
        return {"k": "img", "thumb": commons_thumb(f, 400), "big": commons_thumb(f, 1400), "href": u, "t": title}
    m = re.search(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([\w-]{11})", u)
    if m:
        return {"k": "yt", "thumb": f"https://img.youtube.com/vi/{m.group(1)}/mqdefault.jpg", "href": u, "t": title or "Video"}
    if "youtube.com/results" in u:
        return {"k": "link", "ic": "▶️", "href": u, "t": title or "Video su YouTube"}
    if "instagram.com" in u:
        return {"k": "link", "ic": "📱", "href": u, "t": title or ("Reel Instagram" if "/reel" in u else "Post Instagram")}
    if "tiktok.com" in u:
        return {"k": "link", "ic": "🎵", "href": u, "t": title or "TikTok"}
    if u.lower().split("?")[0].endswith(IMG_EXT):
        return {"k": "img", "thumb": u, "big": u, "href": u, "t": title}
    return {"k": "link", "ic": "🔗", "href": u, "t": title or "Link"}


def local_file(name, title=""):
    name = unquote(name).strip()
    cands = [f for f in HERE.parent.rglob(Path(name).name)
             if f.is_file() and FOTO_DIR not in f.parents and "reel" not in f.parts]
    if not cands:
        MEDIA_WARN.append(f"file non trovato: {name}")
        return None
    src = cands[0]
    FOTO_DIR.mkdir(exist_ok=True)
    dst = FOTO_DIR / src.name
    if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, dst)
    rel = "foto/" + quote(dst.name)
    if dst.suffix.lower() in VID_EXT:
        return {"k": "link", "ic": "🎬", "href": rel, "t": title or "Video"}
    return {"k": "img", "thumb": rel, "big": rel, "href": rel, "t": title}


if MEDIA_MD.exists():
    cur = None
    for ln in MEDIA_MD.read_text(encoding="utf-8").splitlines():
        s = ln.strip()
        m = re.match(r"^##\s+(.+)$", s)
        if m:
            cur = find_place(m.group(1))
            if not cur:
                MEDIA_WARN.append(f"luogo non riconosciuto: {m.group(1)}")
            continue
        if s.startswith("#"):
            cur = None
            continue
        if not cur or not s.startswith(("-", "*", "!")):
            continue
        s = re.sub(r"^[-*]\s+", "", s)
        item = None
        m = re.match(r"!\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", s)
        if m:
            item = local_file(m.group(1))
        else:
            m = re.match(r"!?\[([^\]]*)\]\(([^)]+)\)", s) or re.match(r"(?:(.+?):\s+)?((?:https?://)\S+)", s)
            if m:
                title, url = (m.group(1) or "").strip(), m.group(2).strip()
                item = classify(url, title) if url.startswith("http") else local_file(url, title)
        if item:
            MEDIA.setdefault(cur["id"], []).append(item)


def media_of(places):
    out = []
    for p in places:
        out += MEDIA.get(p["id"], [])
    return out


def thumb_a(i, cls):
    alt = esc(i.get("t") or "")
    if i["k"] == "img":
        return (f'<a class="{cls} lb" href="{esc(i["href"])}" data-big="{esc(i["big"])}" target="_blank" rel="noopener">'
                f'<img loading="lazy" src="{esc(i["thumb"])}" alt="{alt}"></a>')
    return (f'<a class="{cls}" href="{esc(i["href"])}" target="_blank" rel="noopener">'
            f'<img loading="lazy" src="{esc(i["thumb"])}" alt="{alt}"><span class="play">▶</span></a>')


def side_thumb(items):
    vis = [i for i in items if i["k"] in ("img", "yt")]
    return thumb_a(vis[0], "side") if vis else ""


def media_box(items):
    vis = [i for i in items if i["k"] in ("img", "yt")]
    links = [i for i in items if i["k"] == "link"]
    chips = "".join(f'<a class="chip" href="{esc(i["href"])}" target="_blank" rel="noopener">{i["ic"]} {esc(i["t"])}</a>'
                    for i in links)
    if len(vis) <= 1:
        return f'<span class="nav">{chips}</span>' if chips else ""
    grid = "".join(thumb_a(i, "mt") for i in vis)
    return (f'<details class="gal"><summary>📷 Foto e video · {len(items)}</summary>'
            f'<div class="grid">{grid}</div>{"<p>" + chips + "</p>" if chips else ""}</details>')


def side(raw):
    return side_thumb(media_of(match_places(raw)))


def extras(raw):
    places = match_places(raw)
    if not places:
        return ""
    p = places[0]
    return nav_chips(p) + gallery(p["id"]) + media_box(media_of(places))


# ---------- mini renderer markdown ----------

EAT_BTN = '<a class="eat" href="#mappa" data-goto="mappa" data-f="g:cibo">🍴 Scegli sulla mappa</a>'


def inline(text: str) -> str:
    codes = []

    def stash(m):
        codes.append(html.escape(m.group(1)))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = text.replace("&lt;br&gt;", "<br>")
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>',
        text,
    )
    text = re.sub(r"\s*—?\s*\[\[mangiare\]\]\s*—?\s*", f" {EAT_BTN} ", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", text)
    return text.strip()


def split_row(line: str):
    line = line.strip().strip("|")
    return [c.strip() for c in line.split("|")]


def slot_rows(body):
    """Raggruppa le righe ↳ con la riga precedente. Ritorna liste di (ora, testo, etichetta)."""
    groups = []
    for r in body:
        t = r[0].strip()
        txt = r[1] if len(r) > 1 else ""
        if t.startswith("↳") and groups:
            rest = t[1:].strip()
            if "·" in rest:
                tm, lb = (x.strip() for x in rest.split("·", 1))
            else:
                tm, lb = groups[-1][0][0], rest
            groups[-1].append((tm, txt, lb))
        else:
            groups.append([(t, txt, "Piano originale")])
    return groups


def slot_html(g):
    if len(g) == 1:
        tm, txt, _ = g[0]
        return f"<tr><td>{inline(tm)}</td><td>{side(txt)}{inline(txt)}{extras(txt)}</td></tr>"
    times, opts = [], []
    for k, (tm, txt, lb) in enumerate(g):
        on = " on" if k == 0 else ""
        times.append(f'<span class="opt{on}" data-o="{k}">{inline(tm)}</span>')
        badge = f'<span class="altlab">⇄ {esc(lb)}</span>' if k else ""
        opts.append(f'<div class="opt{on}" data-o="{k}" data-l="{esc(lb)}">{badge}{side(txt)}{inline(txt)}{extras(txt)}</div>')
    return (f'<tr class="alt" data-i="0"><td>{"".join(times)}</td><td>{"".join(opts)}'
            f'<button class="swap" type="button">⇄ <span>{esc(g[1][2])}</span></button></td></tr>')


def render(lines, checklist=False, enrich=False) -> str:
    out = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()
        if not s:
            i += 1
        elif s == "---":
            i += 1
        elif s.startswith("#"):
            m = re.match(r"(#+)\s+(.*)", s)
            lvl = min(len(m.group(1)) + 1, 6)
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [split_row(r) for r in rows]
            body = [c for c in cells if not all(re.fullmatch(r":?-{3,}:?", x) for x in c)]
            head, body = body[0], body[1:]
            has_head = any(h for h in head)
            t = ['<div class="tw"><table>']
            if has_head:
                t.append("<thead><tr>" + "".join(f"<th>{inline(h)}</th>" for h in head) + "</tr></thead>")
            else:
                body = [head] + body
            t.append("<tbody>")
            if enrich and all(len(r) == 2 for r in body):
                t.extend(slot_html(g) for g in slot_rows(body))
            else:
                for r in body:
                    t.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
        elif s.startswith(">"):
            block = []
            while i < n and lines[i].strip().startswith(">"):
                block.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + render(block) + "</blockquote>")
        elif re.match(r"^\s*[-*]\s+", line) or re.match(r"^\s*\d+\.\s+", line):
            ordered = bool(re.match(r"^\s*\d+\.\s+", line))
            tag = "ol" if ordered else "ul"
            items = []
            pat = r"^\s*\d+\.\s+" if ordered else r"^\s*[-*]\s+"
            while i < n and re.match(pat, lines[i]):
                items.append(re.sub(pat, "", lines[i]))
                i += 1
            if checklist and not ordered:
                lis = "".join(
                    f'<li class="chk"><label><input type="checkbox" data-k="{k}"> <span>{inline(t)}</span></label></li>'
                    for k, t in enumerate(items)
                )
            else:
                lis = "".join(f"<li>{inline(t)}</li>" for t in items)
            out.append(f"<{tag}>{lis}</{tag}>")
        else:
            para = []
            while i < n and lines[i].strip() and not re.match(r"^\s*([#|>]|[-*]\s|\d+\.\s|---$)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + inline(" ".join(para)) + "</p>")
    return "\n".join(out)


# ---------- parsing del documento ----------

text = SRC.read_text(encoding="utf-8")
lines = text.splitlines()

title = "Amsterdam"
subtitle_lines = []
sections = []  # (num, title, [lines])
cur = None
for ln in lines:
    if ln.startswith("# ") and not sections and cur is None:
        title = ln[2:].strip()
        continue
    m = re.match(r"^## (\d+)\.\s+(.*)", ln)
    if m:
        cur = (int(m.group(1)), m.group(2).strip(), [])
        sections.append(cur)
        continue
    if cur is None:
        subtitle_lines.append(ln)
    else:
        cur[2].append(ln)

subtitle_html = "".join(
    f"<p>{inline(l.strip().strip('_'))}</p>" for l in subtitle_lines if l.strip() and l.strip() != "---"
)

# giorni: split per ### dentro la sezione 4
days = []
sec4 = next(s for s in sections if s[0] == 4)
sec4_intro = []
dcur = None
for ln in sec4[2]:
    if ln.startswith("### "):
        t = ln[4:].strip()
        m = re.search(r"(\d{1,2})\s+novembre", t)
        dcur = {"title": t, "day": int(m.group(1)) if m else 0, "lines": []}
        days.append(dcur)
    elif dcur is not None:
        dcur["lines"].append(ln)
    else:
        sec4_intro.append(ln)

PLAN_RE = re.compile(r"^####\s+(Piano|Opzione)\s+([A-Z])\s*[—–-]\s*(.*)")


def day_html(d):
    intro, plans = [], []
    for ln in d["lines"]:
        m = PLAN_RE.match(ln)
        if m:
            plans.append({"kind": m.group(1), "k": m.group(2), "t": m.group(3).strip(), "lines": []})
        elif plans:
            plans[-1]["lines"].append(ln)
        else:
            intro.append(ln)
    head = (f'<div class="dh"><h2>{inline(d["title"])}</h2>'
            f'<a class="wx" href="{KNMI}" target="_blank" rel="noopener" aria-label="Meteo ufficiale KNMI" title="Meteo KNMI">⛅</a></div>')
    body = render(intro, enrich=True)
    if plans:
        btns, secs = [], []
        for p in plans:
            short, _, sub = p["t"].partition("·")
            full = f'{p["kind"]} {p["k"]} — {short.strip()}' + (f" · {sub.strip()}" if sub else "")
            btns.append(f'<button class="sg" type="button" data-p="{p["k"]}"><b>{p["k"]}</b> {inline(short.strip())}</button>')
            secs.append(f'<section class="plan" data-p="{p["k"]}"><h3>{inline(full)}</h3>{render(p["lines"], enrich=True)}</section>')
        body += f'<div class="plans" data-key="plan-{d["day"]}"><div class="seg">{"".join(btns)}</div>{"".join(secs)}</div>'
    return f'<article class="day" data-day="{d["day"]}">{head}{body}</article>'


def sec_html(num, label, body, **kw):
    return f'<section class="blk"><h2>{inline(label)}</h2>{render(body, **kw)}</section>'


def pick(nums):
    return "".join(
        sec_html(s[0], s[1], s[2], **({"checklist": True} if s[0] == 10 else {}))
        for s in sections
        if s[0] in nums
    )


def pill_label(t):
    m = re.search(r"([A-Za-zì]+)\s+(\d{1,2})\s+novembre", t)
    return html.escape(f"{m.group(1)[:3]} {m.group(2)}") if m else html.escape(t[:12])


def apps_html(mini=False):
    cls = "apps mini" if mini else "apps"
    return f'<div class="{cls}">' + "".join(
        f'<a class="app" href="{esc(u)}" target="_blank" rel="noopener"><span class="ic">{ic}</span><span>{esc(n)}</span></a>'
        for n, ic, u in APPS
    ) + "</div>"


# ---------- scheda Mappa: una sola mappa con posti da visitare e cibo ----------

FOOD = [p for p in LUOGHI if p["cat"] in CAT]


def place_li(p, grp, cat, ic, lb, col):
    meta = " · ".join(x for x in [p.get("indirizzo"), p.get("orari")] if x)
    return (f'<li data-grp="{grp}" data-cat="{cat}" data-lat="{p["lat"]}" data-lng="{p["lng"]}">'
            f'{side_thumb(MEDIA.get(p["id"], []))}'
            f'<span class="dist"></span><span class="nm">{ic} {esc(p["nome"])}</span>'
            f'<span class="badge" style="background:{col}">{esc(lb)}</span>'
            f'{"<div class=meta>" + esc(meta) + "</div>" if meta else ""}'
            f'{"<div>" + esc(p["nota"]) + "</div>" if p.get("nota") else ""}{nav_chips(p)}</li>')


ALL_ITEMS = ([place_li(p, "visita", "v-" + v[0], v[2], v[1], v[3])
              for v in VCATS for p in VISITE if VCAT_OF[p["id"]][0] == v[0]]
             + [place_li(p, "cibo", p["cat"], CAT[p["cat"]][2], CAT[p["cat"]][1], CAT[p["cat"]][3]) for p in FOOD])

if UNICA_MID:
    map_block = mymap(UNICA_MID, "Mappa di Amsterdam")
elif MYMAPS_MID:
    map_block = ('<p class="legend">Per ora qui c\'è la mappa del cibo. Per avere tutto in una mappa sola: importa '
                 '<code>mappa.kml</code> su mymaps.google.com e incolla il link.</p>'
                 + mymap(MYMAPS_MID, "Mappa dei posti dove mangiare"))
else:
    map_block = ('<div class="map ph"><b>🗺️ La mappa comparirà qui.</b><br>'
                 'Si crea una volta sola importando <code>mappa.kml</code> su mymaps.google.com.</div>')

filters = ('<button class="fc on" type="button" data-f="">Tutti</button>'
           '<button class="fc" type="button" data-f="g:visita">📌 Da visitare</button>'
           '<button class="fc" type="button" data-f="g:cibo">🍴 Mangiare</button>'
           + "".join(f'<button class="fc" type="button" data-f="{k}">{ic} {esc(lb)}</button>' for k, lb, ic, _, _ in CATS))
map_tab = (
    f'<section class="blk"><h2>🗺️ Mappa</h2>{map_block}'
    f'<div class="tools"><button id="near" class="fc" type="button">📍 Vicino a me</button><span id="nearmsg"></span></div>'
    f'<div class="filters">{filters}</div>'
    f'<ul class="places">{"".join(ALL_ITEMS)}</ul></section>'
)
sec8 = next((s for s in sections if s[0] == 8), None)
eat_tab = sec_html(8, sec8[1], sec8[2]) if sec8 else ""

# ---------- composizione ----------

day_tabs = "".join(
    f'<button class="pill" data-day="{d["day"]}">{pill_label(d["title"])}</button>' for d in days
)
day_panels = "".join(day_html(d) for d in days)

TABS = [
    ("giorni", "📅", "Giorni", f'<div class="pills">{day_tabs}</div>{day_panels}'
     f'<div class="legend">{render(sec4_intro)}</div>'),
    ("mappa", "🗺️", "Mappa", map_tab),
    ("mangiare", "🍴", "Mangiare", eat_tab),
    ("app", "📱", "App", f'<section class="blk"><h2>📱 App e link</h2>{apps_html()}</section>' + pick({7})),
    ("prenota", "🎟️", "Prenota", pick({6})),
    ("info", "ℹ️", "Info", pick({1, 2, 3, 9, 10})),
]

nav = "".join(
    f'<button class="nb" data-tab="{k}"><span class="ic">{ic}</span><span>{lb}</span></button>'
    for k, ic, lb, _ in TABS
)
panes = "".join(f'<main class="pane" id="p-{k}">{body}</main>' for k, _, _, body in TABS)

page = f"""<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Amsterdam 17-21 novembre</title>
<meta name="description" content="Itinerario Amsterdam 17-21 novembre 2026: giorni, mappa del cibo, trasporti, prenotazioni.">
<meta name="theme-color" content="#c8501e">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<style>
:root {{
  --bg:#faf6f0; --surface:#ffffff; --ink:#1f1a17; --muted:#6b6058; --line:#e6ddd2;
  --accent:#c8501e; --accent-ink:#ffffff; --soft:#fbe9df; --warn:#fff4d6;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#16120f; --surface:#211b17; --ink:#f1e9e1; --muted:#a89b90; --line:#362d27;
    --accent:#ff8a57; --accent-ink:#1a0f09; --soft:#3a251a; --warn:#3a3114;
  }}
}}
:root[data-theme="dark"] {{
  --bg:#16120f; --surface:#211b17; --ink:#f1e9e1; --muted:#a89b90; --line:#362d27;
  --accent:#ff8a57; --accent-ink:#1a0f09; --soft:#3a251a; --warn:#3a3114;
}}
* {{ box-sizing:border-box; }}
html {{ -webkit-text-size-adjust:100%; }}
body {{
  margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  padding-bottom:calc(72px + env(safe-area-inset-bottom));
}}
header {{ padding:20px 16px 8px; max-width:760px; margin:0 auto; }}
header h1 {{ font-size:1.5rem; line-height:1.2; margin:0 0 6px; }}
header .sub p {{ margin:2px 0; color:var(--muted); font-size:.9rem; }}
.hbtn {{ float:right; display:flex; gap:6px; margin-left:8px; }}
#theme, .wx {{ background:var(--surface); border:1px solid var(--line); color:var(--ink); border-radius:10px;
  padding:4px 8px; font-size:1.1rem; line-height:1.4; cursor:pointer; text-decoration:none; }}
.pane {{ display:none; max-width:760px; margin:0 auto; padding:8px 16px 24px; }}
.pane.on {{ display:block; }}
h2 {{ font-size:1.25rem; line-height:1.25; margin:1.4em 0 .5em; }}
h3 {{ font-size:1.05rem; margin:1.2em 0 .4em; }}
h4 {{ font-size:1rem; margin:1em 0 .3em; }}
p {{ margin:.5em 0; }}
a {{ color:var(--accent); }}
code {{ background:var(--soft); padding:1px 5px; border-radius:4px; font-size:.9em; }}
ul,ol {{ padding-left:1.3em; margin:.5em 0; }}
li {{ margin:.3em 0; }}
li.chk {{ list-style:none; margin-left:-1.3em; }}
li.chk label {{ display:flex; gap:10px; align-items:flex-start; cursor:pointer; }}
li.chk input {{ margin-top:.35em; width:18px; height:18px; accent-color:var(--accent); flex:none; }}
li.chk input:checked + span {{ text-decoration:line-through; color:var(--muted); }}
blockquote {{ margin:.8em 0; padding:.2em 14px; background:var(--warn); border-left:4px solid var(--accent); border-radius:6px; }}
.tw {{ overflow-x:auto; margin:.8em 0; border:1px solid var(--line); border-radius:10px; background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; font-size:.93rem; }}
th,td {{ padding:8px 10px; text-align:left; vertical-align:top; border-bottom:1px solid var(--line); }}
th {{ background:var(--soft); font-weight:600; white-space:nowrap; }}
tr:last-child td {{ border-bottom:0; }}
.day table td:first-child {{ white-space:nowrap; font-variant-numeric:tabular-nums; color:var(--accent); font-weight:600; width:1%; }}
.pills {{ display:flex; gap:8px; overflow-x:auto; padding:8px 0; position:sticky; top:0; background:var(--bg); z-index:5; }}
.pill {{ flex:none; border:1px solid var(--line); background:var(--surface); color:var(--ink);
  border-radius:999px; padding:8px 14px; font:inherit; font-size:.9rem; cursor:pointer; }}
.pill.on {{ background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }}
.pill.today::after {{ content:" •"; }}
.day {{ display:none; }}
.day.on {{ display:block; }}
.dh {{ display:flex; align-items:flex-start; justify-content:space-between; gap:10px; }}
.dh h2 {{ margin-top:.8em; }}
.dh .wx {{ margin-top:.7em; font-size:1.4rem; flex:none; }}
.seg {{ display:flex; gap:6px; overflow-x:auto; margin:12px 0 4px; padding-bottom:2px; }}
.sg {{ flex:1 0 auto; border:1px solid var(--line); background:var(--surface); color:var(--ink); border-radius:12px;
  padding:9px 12px; font:inherit; font-size:.88rem; cursor:pointer; }}
.sg b {{ display:inline-block; min-width:1.4em; }}
.sg.on {{ background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }}
.plan {{ display:none; }}
.plan.on {{ display:block; }}
.alt .opt:not(.on) {{ display:none; }}
.alt span.opt.on {{ display:inline; }}
.altlab {{ display:inline-block; font-size:.78rem; font-weight:600; background:var(--warn); color:var(--ink);
  padding:2px 8px; border-radius:6px; margin-bottom:4px; }}
.swap {{ display:inline-flex; gap:4px; margin-top:8px; border:1px dashed var(--accent); color:var(--accent); background:var(--soft);
  border-radius:999px; padding:6px 12px; font:inherit; font-size:.84rem; font-weight:600; cursor:pointer; }}
.eat {{ display:inline-block; background:var(--accent); color:var(--accent-ink); text-decoration:none; border-radius:999px;
  padding:3px 12px; font-size:.84rem; font-weight:600; margin:2px 2px; white-space:nowrap; }}
.nav {{ display:block; }}
.chip {{ display:inline-block; border:1px solid var(--line); border-radius:999px; padding:3px 10px; font-size:.8rem;
  text-decoration:none; color:var(--ink); background:var(--bg); margin:6px 6px 0 0; white-space:nowrap; }}
.gal summary {{ cursor:pointer; color:var(--accent); font-weight:600; margin-top:8px; font-size:.9rem; }}
.gal .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(96px,1fr)); gap:8px; margin-top:8px; }}
.gal figure {{ margin:0; }}
.gal img {{ width:100%; aspect-ratio:1; object-fit:cover; border-radius:8px; background:var(--soft); display:block; }}
.gal figcaption {{ font-size:.75rem; line-height:1.3; margin-top:4px; color:var(--muted); white-space:normal; }}
.apps {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:12px 0; }}
.app {{ display:flex; flex-direction:column; align-items:center; gap:2px; padding:10px 4px; border:1px solid var(--line);
  border-radius:12px; background:var(--surface); text-decoration:none; color:var(--ink); font-size:.8rem; font-weight:600; text-align:center; }}
.app .ic {{ font-size:1.4rem; }}
.apps.mini {{ display:flex; overflow-x:auto; gap:6px; margin:0 0 4px; }}
.apps.mini .app {{ flex:none; flex-direction:row; gap:5px; padding:5px 10px; font-size:.78rem; border-radius:999px; }}
.apps.mini .ic {{ font-size:1rem; }}
.legend {{ font-size:.85rem; color:var(--muted); }}
.map {{ border:1px solid var(--line); border-radius:12px; overflow:hidden; background:var(--soft); margin:.6em 0; }}
.map iframe {{ display:block; width:100%; height:65vh; border:0; }}
.map.ph {{ padding:16px; font-size:.92rem; }}
details.vmap {{ border:1px solid var(--line); border-radius:12px; background:var(--surface); padding:0 12px; margin:10px 0; }}
details.vmap > summary {{ cursor:pointer; font-weight:600; padding:12px 0; }}
details.vmap .map iframe {{ height:60vh; }}
.tools {{ display:flex; align-items:center; gap:10px; margin:10px 0 0; font-size:.85rem; color:var(--muted); }}
.filters {{ display:flex; gap:6px; overflow-x:auto; margin:10px 0; padding-bottom:2px; }}
.fc {{ flex:none; border:1px solid var(--line); background:var(--surface); color:var(--ink); border-radius:999px;
  padding:6px 12px; font:inherit; font-size:.84rem; cursor:pointer; }}
.fc.on {{ background:var(--accent); color:var(--accent-ink); border-color:var(--accent); }}
.places {{ list-style:none; padding:0; margin:0; }}
.places li {{ border:1px solid var(--line); border-radius:12px; padding:10px 12px; margin:8px 0; background:var(--surface); font-size:.92rem; }}
.places .nm {{ font-weight:600; }}
.places .badge {{ font-size:.7rem; padding:1px 8px; border-radius:999px; color:#fff; margin-left:6px; vertical-align:2px; white-space:nowrap; }}
.places .meta {{ font-size:.8rem; color:var(--muted); }}
.places .dist {{ float:right; font-size:.8rem; color:var(--accent); font-weight:600; margin-left:8px; }}
.blk {{ border-top:1px solid var(--line); }}
.blk:first-child {{ border-top:0; }}
nav {{ position:fixed; bottom:0; left:0; right:0; display:flex; background:var(--surface);
  border-top:1px solid var(--line); padding-bottom:env(safe-area-inset-bottom); z-index:10; }}
.nb {{ flex:1; background:none; border:0; color:var(--muted); padding:8px 2px 6px; font:inherit;
  font-size:.7rem; display:flex; flex-direction:column; align-items:center; gap:2px; cursor:pointer; min-width:0; }}
.nb .ic {{ font-size:1.3rem; line-height:1; }}
.nb.on {{ color:var(--accent); font-weight:600; }}
.pills, .apps.mini, .seg, .filters {{ scrollbar-width:none; }}
.pills::-webkit-scrollbar, .apps.mini::-webkit-scrollbar, .seg::-webkit-scrollbar, .filters::-webkit-scrollbar {{ display:none; }}
a.side, a.mt {{ position:relative; display:block; }}
a.side {{ float:right; width:96px; margin:2px 0 6px 10px; }}
a.side img, a.mt img {{ width:100%; aspect-ratio:4/3; object-fit:cover; border-radius:8px; background:var(--soft); display:block; }}
.gal .grid a.mt img {{ aspect-ratio:1; }}
.play {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#fff;
  font-size:1.5rem; text-shadow:0 1px 6px rgba(0,0,0,.7); pointer-events:none; }}
.places li::after, .day td::after {{ content:""; display:block; clear:both; }}
#lb {{ position:fixed; inset:0; background:rgba(0,0,0,.92); display:none; align-items:center; justify-content:center;
  z-index:50; padding:16px; cursor:zoom-out; }}
#lb.on {{ display:flex; }}
#lb img {{ max-width:100%; max-height:88vh; border-radius:8px; }}
#lb span {{ position:absolute; top:12px; right:16px; color:#fff; font-size:1.6rem; }}
@media (min-width:700px) {{ body {{ font-size:17px; }} a.side {{ width:150px; }} }}
</style>
</head>
<body>
<header>
  <div class="hbtn">
    <a class="wx" href="{KNMI}" target="_blank" rel="noopener" aria-label="Meteo ufficiale KNMI" title="Meteo KNMI">⛅</a>
    <button id="theme" aria-label="Cambia tema">◐</button>
  </div>
  <h1>{inline(title)}</h1>
  <div class="sub">{subtitle_html}</div>
</header>
{panes}
<nav>{nav}</nav>
<div id="lb" role="dialog" aria-label="Foto"><span>✕</span><img alt=""></div>
<script>
(function () {{
  var $ = function (s, r) {{ return (r || document).querySelector(s); }};
  var $$ = function (s, r) {{ return Array.prototype.slice.call((r || document).querySelectorAll(s)); }};
  function get(k) {{ try {{ return localStorage.getItem(k); }} catch (e) {{ return null; }} }}
  function set(k, v) {{ try {{ localStorage.setItem(k, v); }} catch (e) {{}} }}

  function showTab(t) {{
    if (!document.getElementById('p-' + t)) t = 'giorni';
    $$('.pane').forEach(function (p) {{ p.classList.toggle('on', p.id === 'p-' + t); }});
    $$('.nb').forEach(function (b) {{ b.classList.toggle('on', b.dataset.tab === t); }});
    set('tab', t); window.scrollTo(0, 0);
  }}
  function showDay(d) {{
    $$('.day').forEach(function (p) {{ p.classList.toggle('on', p.dataset.day === String(d)); }});
    $$('.pill').forEach(function (b) {{ b.classList.toggle('on', b.dataset.day === String(d)); }});
    set('day', d);
  }}
  $$('.nb').forEach(function (b) {{ b.onclick = function () {{ showTab(b.dataset.tab); }}; }});
  $$('.pill').forEach(function (b) {{ b.onclick = function () {{ showDay(b.dataset.day); window.scrollTo(0, 0); }}; }});
  $$('[data-goto]').forEach(function (a) {{
    a.onclick = function (e) {{ e.preventDefault(); showTab(a.dataset.goto);
      var fb = a.dataset.f && $('.filters .fc[data-f="' + a.dataset.f + '"]'); if (fb) fb.click(); }};
  }});

  // piani di giornata (A/B/C)
  $$('.plans').forEach(function (box) {{
    var key = box.dataset.key;
    function pick(p) {{
      $$('.sg', box).forEach(function (b) {{ b.classList.toggle('on', b.dataset.p === p); }});
      $$('.plan', box).forEach(function (s) {{ s.classList.toggle('on', s.dataset.p === p); }});
      set(key, p);
    }}
    $$('.sg', box).forEach(function (b) {{ b.onclick = function () {{ pick(b.dataset.p); }}; }});
    var saved = get(key);
    pick(saved && $('.plan[data-p="' + saved + '"]', box) ? saved : $('.plan', box).dataset.p);
  }});

  // alternative per singolo slot
  $$('tr.alt').forEach(function (tr) {{
    var opts = $$('div.opt', tr), n = opts.length, btn = $('.swap span', tr);
    $('.swap', tr).onclick = function () {{
      var i = (parseInt(tr.dataset.i, 10) + 1) % n;
      tr.dataset.i = i;
      $$('.opt', tr).forEach(function (o) {{ o.classList.toggle('on', o.dataset.o === String(i)); }});
      btn.textContent = i === n - 1 && n > 1 ? 'Torna al piano originale' : opts[(i + 1) % n].dataset.l;
    }};
  }});

  // foto a schermo intero
  var lb = $('#lb'), lbi = $('#lb img');
  $$('a.lb').forEach(function (a) {{
    a.onclick = function (e) {{ e.preventDefault(); lbi.src = a.dataset.big; lbi.alt = $('img', a).alt; lb.classList.add('on'); }};
  }});
  lb.onclick = function () {{ lb.classList.remove('on'); lbi.src = ''; }};

  // filtri e vicinanza nella scheda Mappa
  var curF = '';
  $$('.filters .fc').forEach(function (b) {{
    b.onclick = function () {{
      curF = b.dataset.f;
      $$('.filters .fc').forEach(function (x) {{ x.classList.toggle('on', x === b); }});
      $$('#p-mappa .places li').forEach(function (li) {{
        var ok = !curF || (curF.indexOf('g:') === 0 ? li.dataset.grp === curF.slice(2) : li.dataset.cat === curF);
        li.style.display = ok ? '' : 'none';
      }});
    }};
  }});
  function km(a, b, c, d) {{
    var R = 6371, r = Math.PI / 180, x = (c - a) * r, y = (d - b) * r;
    var h = Math.sin(x / 2) * Math.sin(x / 2) + Math.cos(a * r) * Math.cos(c * r) * Math.sin(y / 2) * Math.sin(y / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }}
  var near = $('#near'), msg = $('#nearmsg');
  if (near) near.onclick = function () {{
    if (!navigator.geolocation) {{ msg.textContent = 'Posizione non disponibile'; return; }}
    msg.textContent = 'Cerco la posizione…';
    navigator.geolocation.getCurrentPosition(function (pos) {{
      var la = pos.coords.latitude, lo = pos.coords.longitude, ul = $('#p-mappa .places');
      var lis = $$('#p-mappa .places li');
      lis.forEach(function (li) {{
        var d = km(la, lo, parseFloat(li.dataset.lat), parseFloat(li.dataset.lng));
        li.dataset.d = d;
        $('.dist', li).textContent = d < 1 ? Math.round(d * 1000 / 10) * 10 + ' m' : d.toFixed(1).replace('.', ',') + ' km';
      }});
      lis.sort(function (a, b) {{ return a.dataset.d - b.dataset.d; }}).forEach(function (li) {{ ul.appendChild(li); }});
      near.classList.add('on'); msg.textContent = 'Ordinati dal più vicino';
    }}, function () {{ msg.textContent = 'Permesso posizione negato'; }}, {{ enableHighAccuracy: true, timeout: 10000 }});
  }};

  var now = new Date();
  var isTrip = now.getFullYear() === 2026 && now.getMonth() === 10 && now.getDate() >= 17 && now.getDate() <= 21;
  var first = $('.pill');
  var firstDay = first ? first.dataset.day : '17';
  if (isTrip) {{ var tp = $('.pill[data-day="' + now.getDate() + '"]'); if (tp) tp.classList.add('today'); }}
  showDay(isTrip ? now.getDate() : (get('day') || firstDay));
  var hash = location.hash.replace('#', '');
  showTab(hash && document.getElementById('p-' + hash) ? hash : (isTrip ? 'giorni' : (get('tab') || 'giorni')));

  $$('li.chk input').forEach(function (c) {{
    var key = 'chk' + c.dataset.k;
    c.checked = get(key) === '1';
    c.onchange = function () {{ set(key, c.checked ? '1' : '0'); }};
  }});

  var root = document.documentElement;
  var th = get('theme'); if (th) root.dataset.theme = th;
  $('#theme').onclick = function () {{
    var dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
    root.dataset.theme = dark ? 'light' : 'dark'; set('theme', root.dataset.theme);
  }};

  if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0) {{
    navigator.serviceWorker.register('sw.js').catch(function () {{}});
  }}
}})();
</script>
</body>
</html>
"""

OUT.write_text(page, encoding="utf-8")

# ---------- export per Google My Maps: una sola mappa, un livello per categoria ----------
# mappa.kml (consigliato: ogni categoria diventa un livello) e mappa.csv.
# I vecchi mangiare.* e visitare.* non servono più.

LAYERS = ([(v[1], v[4], [p for p in VISITE if VCAT_OF[p["id"]][0] == v[0]]) for v in VCATS]
          + [(c[1], c[4], [p for p in FOOD if p["cat"] == c[0]]) for c in CATS])

with open(HERE / "mappa.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["Name", "Category", "Latitude", "Longitude", "Address", "Hours", "Notes"])
    for lb, _, ps in LAYERS:
        for p in ps:
            w.writerow([p["nome"], lb, p["lat"], p["lng"], p.get("indirizzo", ""), p.get("orari", ""), p.get("nota", "")])

kml = ['<?xml version="1.0" encoding="UTF-8"?>', '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
       "<name>Amsterdam 17-21 novembre</name>"]
for kcol in sorted({k for _, k, _ in LAYERS}):
    kml.append(f'<Style id="s-{kcol}"><IconStyle><Icon><href>http://maps.google.com/mapfiles/kml/paddle/{kcol}-circle.png</href></Icon></IconStyle></Style>')
for lb, kcol, ps in LAYERS:
    kml.append(f"<Folder><name>{esc(lb)}</name>")
    for p in ps:
        desc = " · ".join(x for x in [p.get("indirizzo"), p.get("orari"), p.get("nota")] if x)
        kml.append(f'<Placemark><name>{esc(p["nome"])}</name><description>{esc(desc)}</description>'
                   f'<styleUrl>#s-{kcol}</styleUrl><Point><coordinates>{p["lng"]},{p["lat"]},0</coordinates></Point></Placemark>')
    kml.append("</Folder>")
kml.append("</Document></kml>")
(HERE / "mappa.kml").write_text("\n".join(kml), encoding="utf-8")

n_alt = page.count('class="alt"')
n_gal = page.count('class="gal"')
print(f"OK: {OUT.name} ({len(page)//1024} KB), giorni={len(days)}, sezioni={len(sections)}, "
      f"luoghi cibo={len(FOOD)}, slot con alternative={n_alt}, gallerie={n_gal}, "
      f"visite={len(VISITE)}, mappa unica={'collegata' if UNICA_MID else 'da importare (mappa.kml)'}, "
      f"foto/video={sum(len(v) for v in MEDIA.values())} su {len(MEDIA)} luoghi", file=sys.stderr)
for w in MEDIA_WARN:
    print("  ⚠ Foto e video.md:", w, file=sys.stderr)
