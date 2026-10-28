"""Who is who: canonical names, PGN spellings, and portrait photos.

Archives spell the same person many ways ("Carlsen,M", "Carlsen, Magnus",
"Kasparov, Gary"), so every star has a pattern list matched against the
normalised PGN name. The canonical name is what the video shows.

Portraits come from Wikipedia's lead image, and ONLY when that image lives on
Wikimedia Commons under a free licence. Non-free "fair use" uploads on enwiki
are skipped. Each photo's author and licence are saved beside it, because
CC BY / BY-SA require credit and the upload description prints it.

    data/longform/photos/<slug>.jpg      square, face-centred, 600x600
    data/longform/photos/credits.json    {slug: {file, author, license, url}}
"""

import io
import json
import re
import time
from pathlib import Path

import requests
from PIL import Image

from longform import lfconfig as C

PHOTO_DIR = C.DATA / "photos"
CREDITS = PHOTO_DIR / "credits.json"
UA = {"User-Agent": "TChessLongform/1.0 (https://tchess.app; optivio.apps@gmail.com)"}

# slug: (canonical name, Wikipedia title, [regexes on the normalised PGN name])
# The normalised name is lowercase, accents stripped, with spaces around a
# comma removed: "Carlsen, Magnus" -> "carlsen,magnus".
STARS = {
    # ── legends ──
    "anderssen": ("Adolf Anderssen", "Adolf Anderssen", [r"^anderssen,a"]),
    "kieseritzky": ("Lionel Kieseritzky", "Lionel Kieseritzky", [r"^kieseritzky"]),
    "dufresne": ("Jean Dufresne", "Jean Dufresne", [r"^dufresne"]),
    "morphy": ("Paul Morphy", "Paul Morphy", [r"^morphy"]),
    "steinitz": ("Wilhelm Steinitz", "Wilhelm Steinitz", [r"^steinitz"]),
    "bardeleben": ("Curt von Bardeleben", "Curt von Bardeleben", [r"bardeleben"]),
    "lasker": ("Emanuel Lasker", "Emanuel Lasker", [r"^lasker,em"]),
    "capablanca": ("José Raúl Capablanca", "José Raúl Capablanca", [r"^capablanca"]),
    "marshall": ("Frank Marshall", "Frank Marshall (chess player)", [r"^marshall,f"]),
    "alekhine": ("Alexander Alekhine", "Alexander Alekhine", [r"^alekhine,a", r"^aljechin"]),
    "reti": ("Richard Réti", "Richard Réti", [r"^reti,r"]),
    "rubinstein": ("Akiba Rubinstein", "Akiba Rubinstein", [r"^rubinstein,a"]),
    "rotlewi": ("Georg Rotlewi", "Georg Rotlewi", [r"^rotlewi"]),
    "botvinnik": ("Mikhail Botvinnik", "Mikhail Botvinnik", [r"^botvinnik"]),
    "keres": ("Paul Keres", "Paul Keres", [r"^keres"]),
    "smyslov": ("Vasily Smyslov", "Vasily Smyslov", [r"^smyslov"]),
    "tal": ("Mikhail Tal", "Mikhail Tal", [r"^tal,m"]),
    "petrosian": ("Tigran Petrosian", "Tigran Petrosian", [r"^petrosian,t"]),
    "spassky": ("Boris Spassky", "Boris Spassky", [r"^spassky"]),
    "fischer": ("Bobby Fischer", "Bobby Fischer", [r"^fischer,r(obert)?"]),
    "byrne_d": ("Donald Byrne", "Donald Byrne", [r"^byrne,d"]),
    "byrne_r": ("Robert Byrne", "Robert Byrne (chess player)", [r"^byrne,r"]),
    "korchnoi": ("Viktor Korchnoi", "Viktor Korchnoi", [r"^kor[ct]h?noi"]),
    "bronstein": ("David Bronstein", "David Bronstein", [r"^bronstein,d"]),
    "larsen": ("Bent Larsen", "Bent Larsen", [r"^larsen,b"]),
    "polugaevsky": ("Lev Polugaevsky", "Lev Polugaevsky", [r"^polugaevsky"]),
    "nezhmetdinov": ("Rashid Nezhmetdinov", "Rashid Nezhmetdinov", [r"^nezhmetdinov"]),
    "karpov": ("Anatoly Karpov", "Anatoly Karpov", [r"^karpov,a"]),
    "kasparov": ("Garry Kasparov", "Garry Kasparov", [r"^kasparov,g"]),
    "timman": ("Jan Timman", "Jan Timman", [r"^timman"]),
    "short": ("Nigel Short", "Nigel Short", [r"^short,n"]),
    "kramnik": ("Vladimir Kramnik", "Vladimir Kramnik", [r"^kramnik"]),
    "topalov": ("Veselin Topalov", "Veselin Topalov", [r"^topalov"]),
    "shirov": ("Alexei Shirov", "Alexei Shirov", [r"^shirov"]),
    "ivanchuk": ("Vassily Ivanchuk", "Vassily Ivanchuk", [r"^ivanchuk"]),
    "polgar": ("Judit Polgar", "Judit Polgár", [r"^polgar,j"]),
    "anand": ("Viswanathan Anand", "Viswanathan Anand", [r"^anand,v"]),
    "deepblue": ("Deep Blue", "Deep Blue (chess computer)", [r"deep ?blue"]),
    "karjakin": ("Sergey Karjakin", "Sergey Karjakin", [r"^karjakin"]),
    # ── modern ──
    "carlsen": ("Magnus Carlsen", "Magnus Carlsen", [r"^carlsen,m"]),
    "nakamura": ("Hikaru Nakamura", "Hikaru Nakamura", [r"^nakamura,h"]),
    "caruana": ("Fabiano Caruana", "Fabiano Caruana", [r"^caruana"]),
    "ding": ("Ding Liren", "Ding Liren", [r"^ding,? ?liren", r"^ding,l"]),
    "nepo": ("Ian Nepomniachtchi", "Ian Nepomniachtchi", [r"^nepomniachtchi"]),
    "gukesh": ("Gukesh D", "Gukesh Dommaraju", [r"^gukesh", r"^d,? ?gukesh", r"^dommaraju"]),
    "pragg": ("R Praggnanandhaa", "Rameshbabu Praggnanandhaa", [r"^praggnanandhaa"]),
    "arjun": ("Arjun Erigaisi", "Arjun Erigaisi", [r"^erigaisi"]),
    "abdusattorov": ("Nodirbek Abdusattorov", "Nodirbek Abdusattorov", [r"^abdusattorov"]),
    "firouzja": ("Alireza Firouzja", "Alireza Firouzja", [r"^firouzja"]),
    "so": ("Wesley So", "Wesley So", [r"^so,w"]),
    "mvl": ("Maxime Vachier-Lagrave", "Maxime Vachier-Lagrave", [r"^vachier"]),
    "aronian": ("Levon Aronian", "Levon Aronian", [r"^aronian"]),
    "giri": ("Anish Giri", "Anish Giri", [r"^giri,a"]),
    "mamedyarov": ("Shakhriyar Mamedyarov", "Shakhriyar Mamedyarov", [r"^mamedyarov"]),
    "duda": ("Jan-Krzysztof Duda", "Jan-Krzysztof Duda", [r"^duda,j"]),
    "rapport": ("Richard Rapport", "Richard Rapport", [r"^rapport"]),
    "keymer": ("Vincent Keymer", "Vincent Keymer", [r"^keymer"]),
    "weiyi": ("Wei Yi", "Wei Yi", [r"^wei,? ?yi$", r"^wei yi"]),
    "dominguez": ("Leinier Domínguez", "Leinier Domínguez", [r"^dominguez"]),
}

_ACCENTS = str.maketrans("áàâäãåéèêëíìîïóòôöõúùûüñçÁÉÍÓÚÑ", "aaaaaaeeeeiiiiooooouuuuncAEIOUN")


def normalise(raw: str) -> str:
    s = (raw or "").translate(_ACCENTS).lower().strip()
    s = re.sub(r"^(comp|gm|im)\s+", "", s)
    s = re.sub(r"\s*,\s*", ",", s)
    return re.sub(r"\s+", " ", s)


def identify(raw: str) -> str | None:
    """PGN name -> star slug, or None for someone not on the list."""
    n = normalise(raw)
    for slug, (_, _, pats) in STARS.items():
        if any(re.search(p, n) for p in pats):
            return slug
    return None


def canonical(raw: str) -> str | None:
    slug = identify(raw)
    return STARS[slug][0] if slug else None


# ── Photos ────────────────────────────────────────────────────────────────

def credits() -> dict:
    return json.loads(CREDITS.read_text(encoding="utf-8")) if CREDITS.is_file() else {}


def photo_path(slug: str | None):
    if not slug:
        return None
    p = PHOTO_DIR / f"{slug}.jpg"
    return p if p.is_file() else None


_FREE = re.compile(r"^(cc[- ]by(-sa)?|cc0|public domain|pd|attribution|free art)", re.I)


def _commons_info(filename: str) -> dict | None:
    # Asked through en.wikipedia, not commons.wikimedia.org: this network
    # resets connections to Commons, and enwiki's API serves the same
    # imageinfo for shared files. imagerepository tells the two apart —
    # "shared" is Commons (free), "local" is an enwiki upload (usually fair use).
    r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=30, params={
        "action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
        "iiprop": "url|extmetadata", "format": "json"})
    pages = r.json().get("query", {}).get("pages", {})
    for p in pages.values():
        if "imageinfo" not in p or p.get("imagerepository") != "shared":
            return None
        ii = p["imageinfo"][0]
        md = ii.get("extmetadata", {})
        lic = md.get("LicenseShortName", {}).get("value", "")
        # "Attribution" is the credit line the uploader asked for, when they
        # gave one; "Artist" is often a paragraph in several languages.
        raw = md.get("Attribution", {}).get("value") or md.get("Artist", {}).get("value", "")
        author = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw)).strip()
        if len(author) > 90:
            author = author[:87].rsplit(" ", 1)[0] + "…"
        return {"url": ii["url"], "page": ii.get("descriptionurl", ""),
                "license": lic, "author": author or "Unknown author"}
    return None


def _face_square(img: Image.Image, size: int = 600) -> Image.Image:
    """Square crop centred on the largest face; top-centre if none is found."""
    import cv2
    import numpy as np
    arr = np.array(img.convert("L"))
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    scale = 800 / max(arr.shape)
    small = cv2.resize(arr, None, fx=scale, fy=scale) if scale < 1 else arr
    # A real head in a portrait is big; small hits are pattern on a jacket or
    # someone in the background, and cropping to one of those is worse than
    # the plain top-centre fallback.
    min_face = int(min(small.shape) * 0.12)
    faces = cascade.detectMultiScale(small, 1.1, 6, minSize=(min_face, min_face))
    w, h = img.size
    if len(faces):
        fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        k = 1 / scale if scale < 1 else 1
        cx, cy, fw = (fx + fw / 2) * k, (fy + fh / 2) * k, fw * k
        side = min(w, h, fw * 2.6)          # head and shoulders
        cy += fw * 0.18                     # a little room for the chin
    else:
        side = min(w, h)
        cx, cy = w / 2, side / 2
    x0 = max(0, min(w - side, cx - side / 2))
    y0 = max(0, min(h - side, cy - side / 2))
    return img.crop((x0, y0, x0 + side, y0 + side)).resize((size, size), Image.LANCZOS)


def recrop(log=print):
    """Re-cut every portrait from its cached original (no network)."""
    for raw in sorted((PHOTO_DIR / "raw").glob("*")):
        img = Image.open(raw).convert("RGB")
        _face_square(img).save(PHOTO_DIR / f"{raw.stem}.jpg", quality=90)
    log("  recropped")


def fetch(slugs=None, force=False, log=print) -> dict:
    """Download free-licensed portraits for the given stars (default: all)."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    cred = credits()
    for slug in (slugs or STARS):
        if slug in cred and photo_path(slug) and not force:
            continue
        name, title, _ = STARS[slug]
        try:
            r = requests.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=30, params={
                "action": "query", "titles": title, "prop": "pageimages",
                "piprop": "name", "format": "json", "redirects": 1})
            page = next(iter(r.json()["query"]["pages"].values()))
            filename = page.get("pageimage")
            if not filename:
                log(f"  {slug:14} no lead image")
                continue
            info = _commons_info(filename)
            if not info:
                log(f"  {slug:14} skipped — {filename} is not on Commons (likely non-free)")
                continue
            if not _FREE.search(info["license"]):
                log(f"  {slug:14} skipped — licence {info['license']!r}")
                continue
            raw_dir = PHOTO_DIR / "raw"
            raw_dir.mkdir(exist_ok=True)
            raw_path = raw_dir / f"{slug}{Path(filename).suffix.lower()}"
            if not raw_path.is_file():
                raw_path.write_bytes(requests.get(info["url"], headers=UA, timeout=60).content)
            img = Image.open(io.BytesIO(raw_path.read_bytes())).convert("RGB")
            _face_square(img).save(PHOTO_DIR / f"{slug}.jpg", quality=90)
            cred[slug] = {"name": name, "file": filename, "author": info["author"],
                          "license": info["license"], "source": info["page"]}
            CREDITS.write_text(json.dumps(cred, indent=2, ensure_ascii=False), encoding="utf-8")
            log(f"  {slug:14} ok  ({info['license']}, {info['author'][:40]})")
            time.sleep(0.5)
        except Exception as e:
            log(f"  {slug:14} failed: {e.__class__.__name__}: {e}")
    return cred
