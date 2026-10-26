# -*- coding: utf-8 -*-
"""
Hub mobile : web app légère (une page HTML + API JSON) servie par le Pi
sur le port 8550 (Tailscale : http://100.124.227.50:8550, public via
Funnel : https://pictorsomni.taild63b02.ts.net).

Serveur Python stdlib, aucune dépendance web : la page (index.html) fait
tout le rendu, ce fichier ne sert que les données. Mêmes sources que Hub :
le Pi (hub_sync, Notion en miroir) pour les cartes, leur ordre et les
listes ; Notion (Data/notion_rest.py) pour l'agenda.
"""


import datetime
import functools
import hashlib
import hmac
import http.cookies
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
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


def _tasks(tool, args):
    """Tâches stockées sur le Pi (hub-sync) ; Notion n'est qu'un miroir."""
    out = hub_sync.tasks_call(tool, args)
    if out.startswith("Erreur"):
        raise RuntimeError(out)
    return json.loads(out)


def _page_id(row):
    return row["url"].rsplit("/", 1)[-1]


def load_tasks():
    """Cartes dans l'ordre manuel de Hub ; jamais placées = en haut, les
    plus récentes d'abord (même règle que Hub._kanban_ordered)."""
    rows = _tasks("notion-query-data-sources", {})["results"]
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
        try:
            tasks = load_tasks()
            agenda = load_agenda(tasks=tasks)
        except Exception:
            if _DATA["tasks"] is None:
                raise
            # Notion injoignable : dernière version connue (l'heure
            # affichée dans l'app reste celle de cette version).
            return _DATA["tasks"], _DATA["agenda"], _DATA["at"]
        _DATA.update(tasks=tasks, agenda=agenda, at=time.time())
        _write_json(DATA_CACHE, _DATA)
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
    # Liste vide (réseau pas prêt au démarrage du Pi) : on réessaie.
    if not _NEWS["items"] or time.time() - _NEWS["at"] > max_age:
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
    """Contenu Markdown d'une page Notion (notes d'une carte / d'un rdv) ;
    Notion injoignable : celui de la sauvegarde du Pi."""
    try:
        text = _tasks("notion-fetch", {"id": page_id})["text"]
        return text.split("<content>\n", 1)[1].rsplit(
            "\n</content>", 1)[0].replace("<empty-block/>", "").strip()
    except Exception:  # pas une tâche : rendez-vous de l'agenda
        pass
    try:
        text = notion_rest._blocks_to_text(page_id)
    except Exception:
        return _backup_notes().get(page_id.replace("-", ""), "")
    return text.replace("<empty-block/>", "").strip()


# ── Sauvegarde complète de Notion sur le Pi (propriétés + notes) ──────
# Toutes les 6 h : backup/latest.json + une copie par jour (30 jours).
# Les notes ne sont relues que pour les pages modifiées depuis.
BACKUP_DIR = os.path.join(HOME, "notion_backup")
BACKUP_LATEST = os.path.join(BACKUP_DIR, "latest.json")
BACKUP_EVERY = 6 * 3600


def _backup_notes():
    data = _read_json(BACKUP_LATEST, {})
    return {_page_id(r): r.get("notes") or ""
            for src in data.get("sources", {}).values()
            for r in src.get("rows", [])}


def backup_notion():
    old = {}
    for src in _read_json(BACKUP_LATEST, {}).get("sources", {}).values():
        for r in src.get("rows", []):
            old[_page_id(r)] = r
    sources = {}
    for name, ds in [("Tâches", KANBAN_DS)] + [(n, d) for n, d, _c in AGENDA]:
        rows = _query(ds)
        for r in rows:
            prev = old.get(_page_id(r))
            if prev and prev.get("last_edited") == r.get("last_edited") \
                    and "notes" in prev:
                r["notes"] = prev["notes"]
                continue
            try:
                r["notes"] = _notes_live(_page_id(r))
            except Exception:
                if prev and "notes" in prev:  # garde l'ancienne version
                    r["notes"] = prev["notes"]
        sources[name] = {"data_source": ds, "rows": rows}
    os.makedirs(BACKUP_DIR, exist_ok=True)
    data = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
            "sources": sources}
    _write_json(BACKUP_LATEST, data)
    _write_json(os.path.join(BACKUP_DIR,
                             f"{datetime.date.today().isoformat()}.json"),
                data)
    days = sorted(f for f in os.listdir(BACKUP_DIR)
                  if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f))
    for f in days[:-30]:
        os.remove(os.path.join(BACKUP_DIR, f))


def _notes_live(page_id):
    # Notion : ~3 appels/s max ; 429 → on attend et on réessaie.
    for wait in (1, 5, 20, 60):
        time.sleep(0.4)
        try:
            return notion_rest._blocks_to_text(page_id).replace(
                "<empty-block/>", "").strip()
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise
            time.sleep(wait)
    raise RuntimeError("Notion : trop de requêtes")


def _backup_loop():
    while True:
        try:
            backup_notion()
        except Exception as exc:
            print(f"[Sauvegarde Notion] {exc}", flush=True)
        time.sleep(BACKUP_EVERY)


def _set_props(page_id, props):
    # Clés aplaties de la lecture (« date:Deadline:start ») → propriété.
    notion = {k.split(":")[1] if k.startswith("date:") else k: v
              for k, v in props.items()}
    _tasks("notion-update-page", {"page_id": page_id,
                                  "command": "update_properties",
                                  "properties": notion})
    for row in _DATA["tasks"] or []:
        if _page_id(row) == page_id:
            row.update(props)


# Corbeille des tâches partagée avec Hub (hub_sync « corbeille », même
# format que Hub._kanban_to_trash, gardée 365 jours).
_TRASH_PROPS = (("demande", "Demande"), ("etat", "Etat"),
                ("deadline", "date:Deadline:start"),
                ("telephone", "Téléphone"), ("email", "E-mail"),
                ("prix", "Prix"), ("projet", "Projet ?"),
                ("paye", "Payé ?"), ("prevenu", "Prévenir ?"),
                ("cree_le", "Créé le"))


_BASE_PROPS = {"Nom", "Date", "Téléphone", "E-mail", "Email"}
# Mêmes défauts et ordre des états que Hub (hub_agenda).
AGENDA_DEFAULTS = {"Studio": {"État": "Réservé"},
                   "Reportage": {"État": "Réservé"},
                   "Location": {"Etat": "Pas d'accompte"}}
_ORDER = ["Réservé", "En cours", "Terminé", "Prêt"]


@functools.lru_cache(maxsize=1)
def agenda_schema():
    """Champs propres à chaque type de rendez-vous (lu une fois)."""
    out = {}
    for name, ds, _c in AGENDA:
        fields = {}
        for prop, info in notion_rest.schema(ds).items():
            if prop in _BASE_PROPS or info["type"] not in (
                    "status", "select", "multi_select", "rich_text",
                    "number"):
                continue
            opts = info["options"]
            if info["type"] == "status":
                opts = sorted(opts, key=lambda o: _ORDER.index(o[0])
                              if o[0] in _ORDER else len(_ORDER))
            fields[prop] = {"type": info["type"], "options": opts,
                            "default": AGENDA_DEFAULTS[name].get(prop)}
        out[name] = fields
    return out


def load_trash():
    limit = (datetime.datetime.now() - datetime.timedelta(days=365)
             ).strftime("%Y-%m-%d %H:%M")
    return [t for t in hub_sync.get("corbeille") or []
            if t["deleted_at"] >= limit]


def delete_task(page_id):
    row = next((r for r in _DATA["tasks"] or []
                if _page_id(r) == page_id), {})
    entry = {"deleted_at": datetime.datetime.now().strftime(
        "%Y-%m-%d %H:%M"), "row": {"page_id": page_id, **{
            k: row.get(w) or "" for k, w in _TRASH_PROPS},
            "notes": _notes(page_id)}}
    hub_sync.put("corbeille", hub_sync.merge_trash([entry], load_trash()))
    _tasks("notion-trash-page", {"page_id": page_id})
    _DATA["tasks"] = [r for r in _DATA["tasks"] or []
                      if _page_id(r) != page_id]


def restore_task(page_id):
    """Sortie de la corbeille Notion (30 j), sinon recréée (comme Hub)."""
    trash = load_trash()
    entry = next(t for t in trash if t["row"]["page_id"] == page_id)
    try:
        _tasks("notion-restore-page", {"page_id": page_id})
    except Exception:
        row = entry["row"]
        props = {w.split(":")[1] if w.startswith("date:") else w: row[k]
                 for k, w in _TRASH_PROPS[:-1] if row.get(k)}
        _tasks("notion-create-pages", {"pages": [{"properties": props,
                                        "content": row.get("notes")}]})
    hub_sync.put("corbeille", [t for t in trash if t is not entry])
    load_data(force=True)


PROMPTS_FILE = CONSTANTS.state_file(".ai_prompts.json")  # = Hub
LASTCAT_FILE = os.path.join(HOME, ".hub_mobile_lastcat.json")


def _read_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    tmp = path + ".tmp"  # écriture atomique (fichiers partagés avec Hub)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
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
    size = max(64, min(1600, int(size)))
    return _thumb(path, os.path.getmtime(path), size)


@functools.lru_cache(maxsize=200)  # mémoire du Pi bornée
def _thumb(path, _mtime, size):
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((size, size))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
    return buf.getvalue()


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
    stamp = (datetime.datetime.now().strftime("%Y%m%d_%H%M%S_")
             + uuid.uuid4().hex[:4])
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
# Code météo → (icône Material Symbols, libellé).
WMO = {0: ("sunny", "Ensoleillé"), 1: ("partly_cloudy_day", "Plutôt ensoleillé"),
       2: ("partly_cloudy_day", "Partiellement nuageux"),
       3: ("cloud", "Couvert"),
       45: ("foggy", "Brouillard"), 48: ("foggy", "Brouillard givrant"),
       51: ("rainy_light", "Bruine"), 53: ("rainy_light", "Bruine"),
       55: ("rainy_light", "Bruine"), 61: ("rainy", "Pluie faible"),
       63: ("rainy", "Pluie"), 65: ("rainy_heavy", "Forte pluie"),
       66: ("weather_mix", "Pluie verglaçante"),
       67: ("weather_mix", "Pluie verglaçante"),
       71: ("weather_snowy", "Neige faible"), 73: ("weather_snowy", "Neige"),
       75: ("ac_unit", "Forte neige"), 77: ("weather_hail", "Grésil"),
       80: ("rainy", "Averses"), 81: ("rainy", "Averses"),
       82: ("rainy_heavy", "Fortes averses"),
       85: ("weather_snowy", "Averses de neige"),
       86: ("weather_snowy", "Averses de neige"),
       95: ("thunderstorm", "Orage"), 96: ("thunderstorm", "Orage et grêle"),
       99: ("thunderstorm", "Orage et grêle")}


def load_weather():
    today = datetime.date.today().isoformat()
    cached = _read_json(WEATHER_CACHE, {})
    # Icône ASCII = nom Material (les anciens caches avaient un emoji).
    if cached.get("date") == today and cached.get("icon", "").isascii():
        return cached
    lat, lon = WEATHER_AT
    url = ("https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat}&longitude={lon}&timezone=Europe%2FBrussels"
           "&forecast_days=1&daily=weather_code,temperature_2m_max,"
           "temperature_2m_min,precipitation_probability_max,"
           "wind_speed_10m_max")
    with urllib.request.urlopen(url, timeout=10) as r:
        d = json.load(r)["daily"]
    icon, label = WMO.get(d["weather_code"][0], ("thermostat", ""))
    data = {"date": today, "icon": icon, "label": label,
            "max": round(d["temperature_2m_max"][0]),
            "min": round(d["temperature_2m_min"][0]),
            "rain": d["precipitation_probability_max"][0],
            "wind": round(d["wind_speed_10m_max"][0])}
    _write_json(WEATHER_CACHE, data)
    return data


# ── Anecdotes du jour tirées des Actus (Gemini, une fois par jour) ─────
DIGEST_CACHE = os.path.join(HOME, ".hub_mobile_digest.json")
DIGEST_PROMPT = (
    "Voici les titres et résumés d'actus du jour (IA, photo, tech, Apple, "
    "podcasts). Choisis les 4 plus intéressantes pour un photographe "
    "passionné de tech et raconte chacune comme une anecdote vivante, en "
    "français, tutoiement, 2 phrases maximum, sans jargon inutile. "
    "Format Markdown strict : une puce par anecdote, qui commence par un "
    "emoji puis un court titre en gras, et finit par la source entre "
    "parenthèses puis le numéro de l'actu entre crochets, par exemple "
    "« (PetaPixel) [12] ». Rien d'autre.\n\n{items}")


_DIGEST_RUN = {"busy": False, "failed_at": 0.0}
_DIGEST_LOCK = threading.Lock()


def load_digest():
    """Anecdotes du jour, écrites en tâche de fond (une seule à la fois,
    nouvel essai 30 min après un échec) : l'accueil n'attend pas."""
    today = datetime.date.today().isoformat()
    cached = _read_json(DIGEST_CACHE, {})
    # Icône ASCII = nom Material (les anciens caches avaient un emoji).
    if cached.get("date") == today and cached.get("icon", "").isascii():
        return cached
    with _DIGEST_LOCK:
        if not _DIGEST_RUN["busy"] and \
                time.time() - _DIGEST_RUN["failed_at"] > 1800:
            _DIGEST_RUN["busy"] = True
            threading.Thread(target=_make_digest, args=(today,),
                             daemon=True).start()
        busy = _DIGEST_RUN["busy"]
    return {"date": today, "text": "", "pending": busy}


def _make_digest(today):
    try:
        data = _build_digest(today)
    except Exception:
        data = {}
    with _DIGEST_LOCK:
        _DIGEST_RUN["busy"] = False
        if not data.get("text"):
            _DIGEST_RUN["failed_at"] = time.time()


def _build_digest(today):
    items = load_news()[:40]
    if not items:
        return {"date": today, "text": ""}
    lines = "\n".join(
        f"{i}. [{it.get('source')}] {it.get('title')} : "
        f"{(it.get('summary') or '')[:300]}" for i, it in enumerate(items))
    try:  # Claude sur le Pi : Gemini réservé aux images
        text = hub_sync.ask_claude(DIGEST_PROMPT.format(items=lines))
    except Exception:
        text = ""
    # Une entrée cliquable par anecdote : « [n] » → l'actu d'origine.
    entries = []
    for line in (text or "").splitlines():
        m = re.search(r"\s*\[(\d+)\]\s*$", line)
        if not line.startswith("- ") or not m or \
                int(m.group(1)) >= len(items):
            continue
        it = items[int(m.group(1))]
        entries.append({"md": line[2:m.start()], "item": {
            **{k: it.get(k) for k in ("title", "link", "category",
                                      "source", "summary", "image")},
            "date": it["date"].isoformat() if it.get("date") else None}})
    data = {"date": today, "text": (text or "").strip(),
            "entries": entries}
    if data["text"]:
        _write_json(DIGEST_CACHE, data)
    return data


# ── Mot de passe (accès public via Funnel) ────────────────────────────
PASS_FILE = os.path.join(HOME, ".hub_mobile_pass")
LOGIN_LOG = os.path.join(HOME, ".hub_mobile_login.log")
_FAILS = {"n": 0, "at": 0.0}
# Un essai à la fois : des essais en parallèle attendent leur tour.
_LOGIN_LOCK = threading.Lock()
MAX_BODY = 50 * 1024 * 1024  # upload photo
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
        if n > MAX_BODY:
            raise ValueError("fichier trop lourd")
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
            if url.path == "/api/attach":  # fichier joint à une tâche
                q = dict(urllib.parse.parse_qsl(url.query))
                hub_sync.file_req("PUT", q["id"], q["n"], self._body(),
                                  timeout=300)
                return self._json({"ok": True})
            if url.path == "/api/upload":
                return self._upload(urllib.parse.unquote(
                    self.headers.get("X-Name", "photo.jpg")))
            return self._post(url.path, json.loads(self._body() or b"{}"))
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)

    def _login(self):
        secret = _secret()
        typed = json.loads(self._body() or b"{}").get("password", "")
        with _LOGIN_LOCK:  # anti force brute
            if time.time() - _FAILS["at"] > 900:  # 15 min calmes
                _FAILS["n"] = 0
            if _FAILS["n"]:
                time.sleep(min(2 * _FAILS["n"], 30))
            ok = bool(secret) and _password_ok(typed, secret)
            if ok:
                _FAILS["n"] = 0
            else:
                _FAILS["n"] += 1
                _FAILS["at"] = time.time()
        if ok:
            _log("accepté")
            # ponytail: pas de « Secure », l'accès Tailscale est en http
            cookie = (f"{COOKIE}={_token(secret)}; Max-Age=31536000; "
                      "Path=/; HttpOnly; SameSite=Lax")
            return self._json({"ok": True}, headers={"Set-Cookie": cookie})
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
        if path == "/api/files":
            return self._json(hub_sync.list_files(q["id"]))
        if path == "/api/file":
            return self._send(
                hub_sync.file_req("GET", q["id"], q["n"]),
                mimetypes.guess_type(q["n"])[0] or "application/octet-stream")
        if path == "/api/agendaschema":
            return self._json(agenda_schema())
        if path == "/api/corbeille":
            return self._json(load_trash())
        if path == "/api/claudemodes":
            return self._json([[m[0], m[2]] for m in hub_sync.CLAUDE_MODES])
        if path == "/api/digest":
            return self._json(load_digest())
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
            # Seulement les liens des flux : pas de file:// ni de service
            # interne du Pi.
            url = q.get("url", "")
            if url not in {it.get("link") for it in load_news()}:
                return self._json({"error": "lien inconnu"}, 404)
            return self._json({"text": rss_feeds.fetch_article_text(url)})
        return self._json({"error": "inconnu"}, 404)

    def _post(self, path, data):
        if path == "/api/claude":
            mode = hub_sync.CLAUDE_MODES[int(data["mode"])][1]
            return self._json({"text": hub_sync.ask_claude(
                hub_sync.claude_prompt(data["text"].strip(), mode))})
        if path == "/api/task":
            _set_props(data["id"], data["props"])
            return self._json({"ok": True})
        if path == "/api/newtask":
            pid = _tasks("notion-create-pages", {"pages": [{"properties": {
                "Demande": data["demande"].strip(),
                "Etat": "À faire"}}]})["ids"][0]
            load_data(force=True)
            return self._json({"id": pid})
        if path == "/api/newevent":
            ds = dict((n, d) for n, d, _c in AGENDA)[data["source"]]
            start = data["date"]
            if data.get("heure"):  # heure locale du Pi (Bruxelles)
                start = datetime.datetime.fromisoformat(
                    f"{start}T{data['heure']}").astimezone().isoformat(
                    timespec="minutes")
            props = {"Nom": data["nom"].strip(), "Date": start,
                     "Téléphone": data.get("tel", "").strip(),
                     # Locations nomme sa propriété « Email ».
                     ("Email" if data["source"] == "Location" else
                      "E-mail"): data.get("mail", "").strip()}
            props.update(data.get("extra") or {})
            if data.get("id"):  # modification : champs vidés compris
                notion_rest._update({"page_id": data["id"],
                                     "command": "update_properties",
                                     "properties": props})
                if "notes" in data:
                    notion_rest._update({"page_id": data["id"],
                                         "command": "replace_content",
                                         "new_str": data["notes"].strip()})
            else:
                notion_rest._create({"parent": {"data_source_id": ds},
                                     "pages": [{"properties": {
                                         k: v for k, v in props.items()
                                         if v},
                                         "content": data.get(
                                             "notes", "").strip()}]})
            load_data(force=True)
            return self._json({"ok": True})
        if path == "/api/delevent":
            notion_rest._trash({"page_id": data["id"]})
            load_data(force=True)
            return self._json({"ok": True})
        if path == "/api/detach":
            hub_sync.file_req("DELETE", data["id"], data["n"])
            return self._json({"ok": True})
        if path == "/api/deltask":
            delete_task(data["id"])
            return self._json({"ok": True})
        if path == "/api/restore":
            restore_task(data["id"])
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
            for old in [k for k, j in _JOBS.items() if j["done"]][:-20]:
                _JOBS.pop(old, None)  # garde les 20 derniers terminés
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
    threading.Thread(target=_backup_loop, daemon=True).start()
    port = int(os.environ.get("HUB_MOBILE_PORT", 8550))
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
