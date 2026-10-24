# -*- coding: utf-8 -*-
"""
Hub mobile : web app légère (une page HTML + API JSON) servie par le Pi
sur le port 8550 (Tailscale : http://100.124.227.50:8550, public via
Funnel : https://pictorsomni.taild63b02.ts.net).

Serveur Python stdlib, aucune dépendance web : la page (index.html) fait
tout le rendu, ce fichier ne sert que les données. Mêmes sources que Hub :
Notion (Data/notion_rest.py) pour les cartes et l'agenda, hub_sync pour
l'ordre des cartes et les listes.
"""


import datetime
import hashlib
import hmac
import http.cookies
import io
import json
import os
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "Data"))
import CONSTANTS  # noqa: E402
import hub_sync  # noqa: E402
import meta_ai  # noqa: E402
from ai_tools import (  # noqa: E402
    _gemini_generate_image, _gemini_refine_image_prompt)
from PIL import Image  # noqa: E402
import notion_rest  # noqa: E402
import rss_feeds  # noqa: E402


KANBAN_DS = "34f4c64b-5c00-4415-99cb-76234faecef1"
# Couleurs : celles de Hub (CONSTANTS.COLOR_*).
C = CONSTANTS
BLUE, VIOLET, GREEN = C.COLOR_BLUE, C.COLOR_VIOLET, C.COLOR_GREEN
YELLOW, ORANGE, RED, PINK = (C.COLOR_YELLOW, C.COLOR_ORANGE, C.COLOR_RED,
                             C.COLOR_PINK)
BG, CARD, GREY = C.COLOR_DARK, C.COLOR_GREY, C.COLOR_LIGHT_GREY
ETATS = [("À faire", BLUE), ("En cours / en attente", VIOLET),
         ("A commander", YELLOW), ("Commandé", ORANGE), ("Terminé", GREEN)]
# Badges des cartes, mêmes valeurs et couleurs que Hub (défaut en 1er).
FLAGS = [
    ("Payé ?", {"Non payé": RED, "Payé": GREEN}),
    ("Prévenir ?", {"Viendra d'office": PINK, "Appeler quand prêt": BLUE,
                    "Pas de messagerie": ORANGE, "Prévenu": GREEN}),
    ("Projet ?", {"Pas de projet": GREY, "Faire projet": BLUE,
                  "Projet envoyé": YELLOW, "Projet validé": VIOLET,
                  "Fichiers prêts": VIOLET}),
]
AGENDA = [("Studio", "ae971f83-22d1-4d53-8972-4c6302c6d371", BLUE),
          ("Reportage", "42f7bb5c-84f2-416a-aad0-8aad7b1ea51a", VIOLET),
          ("Location", "23f887c8-202a-4e37-91e1-812a4a6c7472", GREEN)]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
         "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


HOME = os.path.expanduser("~")
IA_DIR = os.path.join(HOME, "IA")
# Galerie : images IA seulement (retour user : pas les projets clients).
GALLERY_ROOTS = [IA_DIR,
                 os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "Generated")]
BRIEFING = os.path.join(HOME, "briefing.md")  # écrit par Claude le matin
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")
FORMATS = [("1:1", "Carré"), ("2:3", "Portrait"), ("3:2", "Paysage")]
_thumbs = {}


def list_images():
    """Toutes les images des GALLERY_ROOTS, les plus récentes d'abord."""
    found = {}
    for root in GALLERY_ROOTS:
        for d, _dirs, files in os.walk(root):
            for f in files:
                if f.lower().endswith(IMG_EXT):
                    path = os.path.realpath(os.path.join(d, f))
                    try:
                        found[path] = os.path.getmtime(path)
                    except OSError:
                        pass
    return sorted(found, key=found.get, reverse=True)


def _fold(text):
    """Minuscules sans accents, pour la recherche."""
    text = unicodedata.normalize("NFD", str(text or "").lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _query(ds):
    return notion_rest._query(
        {"data": {"data_source_url": f"collection://{ds}"}})["results"]


def _page_id(row):
    return row["url"].rsplit("/", 1)[-1]


def load_tasks():
    """Cartes dans l'ordre manuel de Hub ; jamais placées = en haut, les
    plus récentes d'abord (même règle que Hub._kanban_ordered)."""
    rows = _query(KANBAN_DS)
    try:
        order = hub_sync.get("kanban_ordre", timeout=5) or []
    except Exception:
        order = []
    pos = {pid: i for i, pid in enumerate(order)}
    new = sorted((r for r in rows if _page_id(r) not in pos),
                 key=lambda r: r.get("Créé le") or "", reverse=True)
    old = sorted((r for r in rows if _page_id(r) in pos),
                 key=lambda r: pos[_page_id(r)])
    return new + old


_NEWS = {"items": None, "at": 0}
# Tâches + Agenda gardés sur le Pi (et sur disque) : l'app s'ouvre sur la
# dernière version connue, rechargée toutes les heures ou au bouton.
DATA_TTL = 3600
DATA_CACHE = os.path.join(HOME, ".hub_mobile_cache.json")
_DATA = {"tasks": None, "agenda": None, "at": 0}


def _load_data_cache():
    try:
        with open(DATA_CACHE, encoding="utf-8") as f:
            _DATA.update(json.load(f))
    except (OSError, ValueError):
        pass


def load_data(force=False):
    """(tasks, agenda, at) depuis le cache s'il a moins d'une heure."""
    if force or _DATA["tasks"] is None or \
            time.time() - _DATA["at"] > DATA_TTL:
        tasks = load_tasks()
        _DATA.update(tasks=tasks, agenda=load_agenda(tasks=tasks),
                     at=time.time())
        try:
            with open(DATA_CACHE, "w", encoding="utf-8") as f:
                json.dump(_DATA, f, ensure_ascii=False)
        except OSError:
            pass
    return _DATA["tasks"], _DATA["agenda"], _DATA["at"]


NEWS_CACHE = os.path.join(HOME, ".hub_mobile_news.json")


def load_news(max_age=DATA_TTL):
    """Flux Actus partagés entre sessions, gardés 1 h (et sur disque)."""
    if _NEWS["items"] is None:
        try:
            with open(NEWS_CACHE, encoding="utf-8") as f:
                saved = json.load(f)
            for it in saved["items"]:
                it["date"] = (datetime.datetime.fromisoformat(it["date"])
                              if it.get("date") else None)
            _NEWS.update(saved)
        except (OSError, ValueError, KeyError):
            pass
    if _NEWS["items"] is None or time.time() - _NEWS["at"] > max_age:
        _NEWS["items"] = rss_feeds.fetch_all_feeds()
        _NEWS["at"] = time.time()
        try:
            with open(NEWS_CACHE, "w", encoding="utf-8") as f:
                json.dump({"at": _NEWS["at"], "items": [
                    {**it, "date": it["date"].isoformat()
                     if it.get("date") else None}
                    for it in _NEWS["items"]]}, f, ensure_ascii=False)
        except OSError:
            pass
    return _NEWS["items"]


def load_agenda(days=60, tasks=()):
    """Rendez-vous des 3 sources + tâches non terminées avec deadline
    (celles en retard aussi, en tête de liste)."""
    today = datetime.date.today().isoformat()
    end = (datetime.date.today() + datetime.timedelta(days)).isoformat()
    events = []
    for name, ds, color in AGENDA:
        for r in _query(ds):
            start = r.get("date:Date:start") or ""
            if today <= start[:10] <= end:
                events.append((start, name, color, r))
    for r in tasks:
        start = r.get("date:Deadline:start") or ""
        if start and start[:10] <= end and r.get("Etat") != "Terminé":
            events.append((start, "Tâche", YELLOW, r))
    return sorted(events, key=lambda e: e[0])


def day_label(iso):
    d = datetime.date.fromisoformat(iso[:10])
    delta = (d - datetime.date.today()).days
    base = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return {0: "Aujourd'hui", 1: "Demain"}.get(delta, base.capitalize())


assert day_label(datetime.date.today().isoformat()) == "Aujourd'hui"



def _notes(page_id):
    """Contenu Markdown d'une page Notion (notes d'une carte / d'un rdv)."""
    try:
        text = notion_rest._blocks_to_text(page_id)
    except Exception:
        text = ""
    return text.replace("<empty-block/>", "").strip()


def _set_props(page_id, props):
    # Clés aplaties de la lecture (« date:Deadline:start ») → propriété.
    notion = {k.split(":")[1] if k.startswith("date:") else k: v
              for k, v in props.items()}
    notion_rest._update({"page_id": page_id, "command": "update_properties",
                         "properties": notion})
    for row in _DATA["tasks"] or []:
        if _page_id(row) == page_id:
            row.update(props)


PROMPTS_FILE = CONSTANTS.state_file(".ai_prompts.json")  # = Hub
LASTCAT_FILE = os.path.join(HOME, ".hub_mobile_lastcat.json")


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:
        pass


def _in_gallery(path):
    """Chemin réel sous une des GALLERY_ROOTS, sinon None."""
    real = os.path.realpath(path)
    for root in GALLERY_ROOTS:
        root = os.path.realpath(root)
        if os.path.commonpath([real, root]) == root and \
                os.path.isfile(real):
            return real
    return None


def thumb_jpeg(path, size):
    key = (path, os.path.getmtime(path), size)
    if key not in _thumbs:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
        _thumbs[key] = buf.getvalue()
    return _thumbs[key]


# ── Génération IA (tâche de fond, la page interroge /api/job) ─────────
_JOBS = {}


def _generate(job, text, src, model, aspect, quality, count, refine):
    muse = model == "muse"
    src_bytes = None
    if src:
        with open(src, "rb") as f:
            src_bytes = f.read()
    kind = ("muse_" if muse else "") + ("edited" if src_bytes
                                        else "generated")
    gen = meta_ai.generate_image if muse else _gemini_generate_image
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(IA_DIR, exist_ok=True)
    refined = text
    if refine and not muse:
        job["status"] = "✍️ Affinage de la demande…"
        try:
            refined = _gemini_refine_image_prompt(
                intent_prompt=text, user_request=text,
                mode="edit_image" if src_bytes else "generate_image",
                source_filename=os.path.basename(src or ""),
                model=CONSTANTS.AI_IMAGE_REFINER_MODEL) or text
        except Exception:
            pass
    job["status"] = f"🎨 {count} image(s) en cours…"
    out, err = [], []

    def _one(i):
        try:
            msg, img = gen(refined, input_image_bytes=src_bytes,
                           aspect_ratio=aspect, resolution=quality)
        except Exception as exc:
            msg, img = str(exc), None
        if img:
            path = os.path.join(IA_DIR, f"{kind}_{stamp}_{i + 1}.png")
            with open(path, "wb") as f:
                f.write(img)
            out.append(path)
        else:
            err.append(msg)
    threads = [threading.Thread(target=_one, args=(i,), daemon=True)
               for i in range(count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    data = _read_json(PROMPTS_FILE, {})
    for p in out:
        data[os.path.normcase(p)] = {"asked": text, "refined": refined}
    _write_json(PROMPTS_FILE, data)
    job.update(done=True, images=out,
               status=("Erreur : " + err[0][:200]) if err else "")


# ── Météo du jour (Open-Meteo, sans clé) : relue une fois par jour ─────
# Magasin : Leuze (5310 Éghezée).
WEATHER_AT = (50.54635, 4.9063)
WEATHER_CACHE = os.path.join(HOME, ".hub_mobile_weather.json")
# Codes WMO → (emoji, libellé)
WMO = {0: ("☀️", "Ensoleillé"), 1: ("🌤️", "Plutôt ensoleillé"),
       2: ("⛅", "Partiellement nuageux"), 3: ("☁️", "Couvert"),
       45: ("🌫️", "Brouillard"), 48: ("🌫️", "Brouillard givrant"),
       51: ("🌦️", "Bruine"), 53: ("🌦️", "Bruine"), 55: ("🌦️", "Bruine"),
       61: ("🌧️", "Pluie faible"), 63: ("🌧️", "Pluie"),
       65: ("🌧️", "Forte pluie"), 66: ("🌧️", "Pluie verglaçante"),
       67: ("🌧️", "Pluie verglaçante"), 71: ("🌨️", "Neige faible"),
       73: ("🌨️", "Neige"), 75: ("❄️", "Forte neige"),
       77: ("🌨️", "Grésil"), 80: ("🌦️", "Averses"),
       81: ("🌦️", "Averses"), 82: ("⛈️", "Fortes averses"),
       85: ("🌨️", "Averses de neige"), 86: ("🌨️", "Averses de neige"),
       95: ("⛈️", "Orage"), 96: ("⛈️", "Orage et grêle"),
       99: ("⛈️", "Orage et grêle")}


def load_weather():
    today = datetime.date.today().isoformat()
    cached = _read_json(WEATHER_CACHE, {})
    if cached.get("date") == today:
        return cached
    lat, lon = WEATHER_AT
    url = ("https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat}&longitude={lon}&timezone=Europe%2FBrussels"
           "&forecast_days=1&daily=weather_code,temperature_2m_max,"
           "temperature_2m_min,precipitation_probability_max,"
           "wind_speed_10m_max")
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.load(r)["daily"]
    icon, label = WMO.get(d["weather_code"][0], ("🌡️", ""))
    data = {"date": today, "icon": icon, "label": label,
            "max": round(d["temperature_2m_max"][0]),
            "min": round(d["temperature_2m_min"][0]),
            "rain": d["precipitation_probability_max"][0],
            "wind": round(d["wind_speed_10m_max"][0])}
    _write_json(WEATHER_CACHE, data)
    return data


# ── Mot de passe (accès public via Funnel) ────────────────────────────
PASS_FILE = os.path.join(HOME, ".hub_mobile_pass")
LOGIN_LOG = os.path.join(HOME, ".hub_mobile_login.log")
_FAILS = {"n": 0}
_AMBIGUOUS = str.maketrans("oli", "011")


def _secret():
    try:
        with open(PASS_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _token(secret):
    return hashlib.sha256(("hub-mobile:" + secret).encode()).hexdigest()


def _log(msg):
    with open(LOGIN_LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")


def _password_ok(typed, secret):
    # iOS met souvent une majuscule initiale : comparaison sans casse,
    # caractères ambigus confondus (0/o, 1/l/i).
    def norm(s):
        return s.strip().lower().translate(_AMBIGUOUS)
    return hmac.compare_digest(norm(typed), norm(secret))


# ── Serveur ───────────────────────────────────────────────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/manifest.json": ("manifest.json", "application/manifest+json")}
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".webp": "image/webp"}
COOKIE = "hub_token"


def _json_default(obj):
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    return str(obj)


class Handler(BaseHTTPRequestHandler):
    server_version = "Hub"

    def log_message(self, fmt, *args):
        pass  # journal muet : seules les connexions vont dans LOGIN_LOG

    # Réponses
    def _send(self, body, ctype, code=200, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200, headers=None):
        self._send(json.dumps(data, ensure_ascii=False,
                              default=_json_default).encode(),
                   "application/json; charset=utf-8", code, headers)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _authed(self):
        secret = _secret()
        if not secret:
            return False
        jar = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        got = jar[COOKIE].value if COOKIE in jar else ""
        return hmac.compare_digest(got, _token(secret))

    # Routage
    def do_GET(self):
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        if url.path in STATIC:
            name, ctype = STATIC[url.path]
            with open(os.path.join(HERE, name), "rb") as f:
                return self._send(f.read(), ctype,
                                  headers={"Cache-Control": "no-cache"})
        if url.path.startswith("/assets/"):
            path = os.path.realpath(os.path.join(HERE, url.path[1:]))
            if path.startswith(os.path.join(HERE, "assets")) and \
                    os.path.isfile(path):
                with open(path, "rb") as f:
                    return self._send(f.read(), MIME.get(
                        os.path.splitext(path)[1], "application/octet-stream"))
            return self._json({"error": "introuvable"}, 404)
        if url.path == "/api/auth":
            return self._json({"ok": self._authed()})
        if not self._authed():
            return self._json({"error": "auth"}, 401)
        try:
            return self._get(url.path, q)
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def do_POST(self):
        url = urllib.parse.urlsplit(self.path)
        if url.path == "/api/login":
            return self._login()
        if not self._authed():
            return self._json({"error": "auth"}, 401)
        try:
            if url.path == "/api/upload":
                return self._upload(urllib.parse.unquote(
                    self.headers.get("X-Name", "photo.jpg")))
            return self._post(url.path, json.loads(self._body() or b"{}"))
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def _login(self):
        secret = _secret()
        typed = json.loads(self._body() or b"{}").get("password", "")
        if secret and _password_ok(typed, secret):
            _FAILS["n"] = 0
            _log("accepté")
            cookie = (f"{COOKIE}={_token(secret)}; Max-Age=31536000; "
                      "Path=/; HttpOnly; SameSite=Lax")
            return self._json({"ok": True}, headers={"Set-Cookie": cookie})
        _FAILS["n"] += 1
        time.sleep(min(2 * _FAILS["n"], 30))  # anti force brute
        _log(f"refusé ({len(typed)} car.)")
        return self._json({"ok": False}, 403)

    def _upload(self, name):
        os.makedirs(IA_DIR, exist_ok=True)
        name = os.path.basename(name) or "photo.jpg"
        path = os.path.join(IA_DIR, "source_" + datetime.datetime.now()
                            .strftime("%Y%m%d_%H%M%S_") + name)
        with open(path, "wb") as f:
            f.write(self._body())
        return self._json({"path": path})

    def _get(self, path, q):
        if path == "/api/data":
            tasks, agenda, at = load_data(force=q.get("force") == "1")
            return self._json({"tasks": tasks, "agenda": agenda, "at": at})
        if path == "/api/notes":
            return self._json({"text": _notes(q["id"])})
        if path == "/api/lists":
            return self._json({n: hub_sync.get(n) or []
                               for n in ("liste", "prix")} | {
                "lastcat": _read_json(LASTCAT_FILE, {})})
        if path == "/api/images":
            prompts = _read_json(PROMPTS_FILE, {})
            return self._json([
                {"path": p, "name": os.path.relpath(p, HOME),
                 "prompt": prompts.get(os.path.normcase(p))}
                for p in list_images()])
        if path == "/api/img":
            real = _in_gallery(q.get("p", ""))
            if not real:
                return self._json({"error": "introuvable"}, 404)
            return self._send(thumb_jpeg(real, int(q.get("s", 360))),
                              "image/jpeg",
                              headers={"Cache-Control": "max-age=86400"})
        if path == "/api/job":
            return self._json(_JOBS.get(q.get("id"), {"done": True}))
        if path == "/api/weather":
            return self._json(load_weather())
        if path == "/api/briefing":
            try:
                with open(BRIEFING, encoding="utf-8") as f:
                    text = f.read()
                when = os.path.getmtime(BRIEFING)
            except OSError:
                text, when = "", None
            return self._json({"text": text, "at": when})
        if path == "/api/news":
            items = load_news(max_age=0 if q.get("force") == "1"
                              else DATA_TTL)
            return self._json({"items": items[:300],
                               "categories": rss_feeds.CATEGORIES})
        if path == "/api/article":
            return self._json({"text": rss_feeds.fetch_article_text(
                q.get("url", ""))})
        return self._json({"error": "inconnu"}, 404)

    def _post(self, path, data):
        if path == "/api/task":
            _set_props(data["id"], data["props"])
            return self._json({"ok": True})
        if path == "/api/list":
            name = data["name"]
            if name not in ("liste", "prix"):
                raise ValueError(name)
            rows = hub_sync.sync_put(name, data.get("base"), data["rows"])
            if data.get("category"):
                cats = _read_json(LASTCAT_FILE, {})
                cats[name] = data["category"]
                _write_json(LASTCAT_FILE, cats)
            return self._json({"rows": rows})
        if path == "/api/generate":
            src = data.get("source")
            if src and not _in_gallery(src):
                raise ValueError("source hors galerie")
            job_id = uuid.uuid4().hex
            job = _JOBS[job_id] = {"done": False, "status": "…"}
            threading.Thread(target=_generate, daemon=True, args=(
                job, data["prompt"].strip(), src, data.get("model"),
                data.get("format", "1:1"), data.get("quality", "1K"),
                max(1, min(4, int(data.get("count", 1)))),
                bool(data.get("refine")))).start()
            return self._json({"id": job_id})
        if path == "/api/trash":
            for p in data["paths"]:
                real = _in_gallery(p)
                if real:  # corbeille du Pi, jamais rm
                    subprocess.run(["gio", "trash", real], check=True,
                                   capture_output=True, timeout=10)
            return self._json({"ok": True})
        return self._json({"error": "inconnu"}, 404)


def main():
    _load_data_cache()
    threading.Thread(target=load_news, daemon=True).start()
    port = int(os.environ.get("HUB_MOBILE_PORT", 8550))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
