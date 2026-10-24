# -*- coding: utf-8 -*-
"""
Hub mobile : Tâches + Agenda pour iPhone / iPad, en web app servie par le
Pi (Tailscale, http://100.124.227.50:8550 : le nom court ne résout pas
sur iOS → « Ajouter à l'écran d'accueil »).

Mêmes données que Hub : Notion (Data/notion_rest.py) pour les cartes et
l'agenda, ordre manuel des cartes partagé via le Pi (hub_sync
"kanban_ordre"). Rien n'est dupliqué : Hub reste l'outil complet.
"""

__version__ = "2.10.115"

import asyncio
import base64
import hashlib
import hmac
import datetime
import io
import json
import os
import subprocess
import sys
import threading
import time
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "Data"))
import flet as ft  # noqa: E402
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


def thumb(path, size=360):
    """Vignette JPEG (data URI), en cache par (chemin, date)."""
    key = (path, os.path.getmtime(path), size)
    if key not in _thumbs:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((size, size))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
        # Data URI : des bytes bruts ne s'affichent pas en web (galerie
        # vide sur iPhone).
        _thumbs[key] = ("data:image/jpeg;base64,"
                        + base64.b64encode(buf.getvalue()).decode())
    return _thumbs[key]


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


# Accès public (Tailscale Funnel) → mot de passe, retenu par l'appareil.
# Le mot de passe vit uniquement sur le Pi (~/.hub_mobile_pass).
PASS_FILE = os.path.join(HOME, ".hub_mobile_pass")
_FAILS = {"n": 0}


def _token():
    try:
        with open(PASS_FILE, encoding="utf-8") as f:
            secret = f.read().strip()
    except OSError:
        return None, None
    return secret, hashlib.sha256(
        ("hub-mobile:" + secret).encode()).hexdigest()


async def main(page: ft.Page):
    secret, token = _token()
    prefs = ft.SharedPreferences()
    page.services.append(prefs)  # service non enregistré = appels muets
    if not secret:
        page.add(ft.Text("Mot de passe absent sur le Pi"))
        return
    try:
        saved = await prefs.get("hub_token")
    except Exception:
        saved = None
    if saved and hmac.compare_digest(str(saved), token):
        _app(page)
        return
    page.title = "Hub"
    page.bgcolor = C.COLOR_BACKGROUND
    page.theme_mode = ft.ThemeMode.DARK
    field = ft.TextField(label="Mot de passe", password=True,
                         can_reveal_password=True, autofocus=True,
                         capitalization=ft.TextCapitalization.NONE,
                         autocorrect=False,
                         border_radius=C.BUTTON_RADIUS, width=280)

    def _log(msg):
        with open(os.path.join(HOME, ".hub_mobile_login.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%H:%M:%S} {msg}\n")

    async def _login(e):
        _log(f"clic, valeur={len(field.value or '')} car.")
        # iOS met souvent une majuscule initiale : comparaison sans casse.
        # + caractères ambigus confondus (0/o, 1/l/i).
        amb = str.maketrans("oli", "011")
        typed = (field.value or "").strip().lower().translate(amb)
        if hmac.compare_digest(typed, secret.lower().translate(amb)):
            _FAILS["n"] = 0
            _log("accepté")
            try:
                await prefs.set("hub_token", token)
            except Exception as exc:
                _log(f"mémorisation impossible : {exc}")
            page.controls.clear()
            try:
                _app(page)
            except Exception:
                import traceback
                _log(traceback.format_exc())
            return
        _FAILS["n"] += 1
        await asyncio.sleep(min(2 * _FAILS["n"], 30))  # anti force brute
        _log(f"refusé ({len(typed)} car., attendu {len(secret)})")
        error.value = "Mot de passe incorrect"
        field.value = ""
        page.update()
    error = ft.Text("", color=C.COLOR_RED)
    field.on_submit = _login
    page.add(ft.SafeArea(ft.Container(ft.Column([
        ft.Text("Hub", size=28, weight=ft.FontWeight.BOLD), field, error,
        ft.FilledButton("Entrer", on_click=_login, width=280)],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=16),
        alignment=ft.Alignment(0, 0), padding=40), expand=True))


def _app(page: ft.Page):
    page.title = "Hub"
    page.bgcolor = C.COLOR_BACKGROUND
    page.theme_mode = ft.ThemeMode.DARK
    # Même thème que Hub : boutons arrondis à BUTTON_RADIUS.
    btn = ft.ButtonStyle(shape=ft.RoundedRectangleBorder(
        radius=C.BUTTON_RADIUS))
    page.dark_theme = page.theme = ft.Theme(
        button_theme=ft.ButtonTheme(style=btn),
        icon_button_theme=ft.IconButtonTheme(style=btn),
        outlined_button_theme=ft.OutlinedButtonTheme(style=btn),
        text_button_theme=ft.TextButtonTheme(style=btn),
        filled_button_theme=ft.FilledButtonTheme(style=btn),
        segmented_button_theme=ft.SegmentedButtonTheme(style=btn))
    page.padding = 0
    state = {"open": {"À faire"}, "tasks": [], "tab": 0, "images": [],
             "shown": 60, "source": None, "format": "1:1", "count": 1,
             "refine": True, "list_kind": "liste", "model": "gemini", "quality": "1K",
             "busy": False, "news": None, "news_cat": None,
             "picked": set()}

    status = ft.Text("", size=12, color=GREY)
    search = ft.TextField(
        hint_text="Rechercher une carte", prefix_icon=ft.Icons.SEARCH,
        border_radius=C.BUTTON_RADIUS, dense=True, on_change=lambda e: render(),
        content_padding=ft.Padding(12, 8, 12, 8))
    search.expand = True
    search_bar = ft.Container(ft.Row([search]),
                              padding=ft.Padding(12, 8, 12, 0))
    body = ft.ListView(expand=True, spacing=8,
                       padding=ft.Padding(12, 8, 12, 24))

    # ── Tâches ───────────────────────────────────────────────────────
    def _set_prop(row, prop, value):
        row[prop] = value
        _details(row)
        render()

        def _run():
            try:
                notion_rest._update({"page_id": _page_id(row),
                                     "command": "update_properties",
                                     "properties": {prop: value}})
            except Exception as exc:
                status.value = f"Erreur Notion : {exc}"
                render()
        threading.Thread(target=_run, daemon=True).start()

    def _set_etat(row, etat):
        sheet.open = False
        page.update()

        def _run():
            try:
                notion_rest._update({"page_id": _page_id(row),
                                     "command": "update_properties",
                                     "properties": {"Etat": etat}})
                row["Etat"] = etat
                state["open"] = {etat}
                status.value = f"Déplacé vers « {etat} »"
            except Exception as exc:
                status.value = f"Erreur Notion : {exc}"
            render()
        threading.Thread(target=_run, daemon=True).start()

    sheet = ft.BottomSheet(ft.Container(), bgcolor=CARD)
    page.overlay.append(sheet)

    def _details(row):
        info = []
        for label, key in (("Deadline", "date:Deadline:start"),
                           ("Téléphone", "Téléphone"), ("E-mail", "E-mail"),
                           ("Prix", "Prix"), ("Créé le", "Créé le")):
            value = row.get(key)
            if value not in (None, "", []):
                info.append(ft.Text(f"{label} : {value}", size=15))
        actions = []
        if row.get("Téléphone"):
            tel = "".join(c for c in row["Téléphone"] if c.isdigit() or c == "+")
            actions.append(ft.FilledButton(
                "Appeler", icon=ft.Icons.PHONE, url=f"tel:{tel}"))
        etats = [ft.OutlinedButton(
            e, on_click=lambda ev, e=e: _set_etat(row, e),
            style=ft.ButtonStyle(color=c)) for e, c in ETATS
            if e != (row.get("Etat") or "À faire")]
        flag_rows = []
        for prop, colors in FLAGS:
            cur = row.get(prop) or next(iter(colors))
            flag_rows += [ft.Text(prop, size=12, color=GREY), ft.Row([
                ft.Container(
                    ft.Text(v, size=13, color="#000000" if v == cur else c),
                    bgcolor=c if v == cur else None,
                    border=ft.Border.all(1, c), border_radius=14,
                    padding=ft.Padding(10, 4, 10, 4),
                    on_click=lambda e, p=prop, v=v: _set_prop(row, p, v))
                for v, c in colors.items()], wrap=True, spacing=6,
                run_spacing=6)]
        # Notes = contenu de la page Notion, chargé à la 1re ouverture.
        notes = ft.Markdown(
            row.get("_notes") or "", selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
            on_tap_link=_open_link)
        notes_box = ft.Container(
            ft.Column([ft.Text("Notes", size=12, color=GREY), notes],
                      spacing=4, tight=True),
            bgcolor=BG, border_radius=8, padding=10,
            visible=bool(row.get("_notes")))
        if "_notes" not in row:
            def _load_notes():
                try:
                    text = notion_rest._blocks_to_text(_page_id(row))
                except Exception:
                    text = ""
                row["_notes"] = text.replace("<empty-block/>", "").strip()
                notes.value = row["_notes"]
                notes_box.visible = bool(row["_notes"])
                page.update()
            threading.Thread(target=_load_notes, daemon=True).start()
        sheet.content = ft.Container(ft.Column([
            ft.Text(row.get("Demande") or "(sans titre)", size=18,
                    weight=ft.FontWeight.BOLD),
            *info, *flag_rows, notes_box, ft.Row(actions),
            ft.Text("Déplacer vers", size=12, color=GREY),
            ft.Row(etats, wrap=True, spacing=8, run_spacing=8),
        ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=20)
        sheet.open = True
        page.update()

    def _badge(text, color):
        # Pastille de Hub (_kanban_chip) : fond quasi plein, texte noir.
        return ft.Container(
            ft.Text(text, size=12, color=ft.Colors.BLACK,
                    weight=ft.FontWeight.W_600),
            bgcolor=ft.Colors.with_opacity(0.85, color), border_radius=4,
            padding=ft.Padding(6, 2, 6, 2))

    def _task_card(row, etat=False):
        """Comme dans Hub : titre, infos clés et badges Payé / Prévenir /
        Projet (« Pas de projet » masqué)."""
        deadline = row.get("date:Deadline:start") or ""
        badges = []
        if etat:
            name = row.get("Etat") or "À faire"
            badges.append(_badge(name, dict(ETATS).get(name, GREY)))
        for prop, colors in FLAGS:
            value = row.get(prop) or next(iter(colors))
            if value != "Pas de projet":
                badges.append(_badge(value, colors.get(value, GREY)))
        info = [x for x in (
            deadline and f"⏰ {day_label(deadline)}",
            row.get("Prix") not in (None, "") and f"{row['Prix']} €",
            row.get("Téléphone")) if x]
        return ft.Container(
            ft.Column([
                ft.Text(row.get("Demande") or "(sans titre)", size=16),
                *([ft.Text("  ·  ".join(info), size=13, color=GREY)]
                  if info else []),
                ft.Row(badges, wrap=True, spacing=6, run_spacing=6),
            ], spacing=6, tight=True),
            # Fond teinté selon l'état, comme les tuiles de Hub.
            bgcolor=ft.Colors.with_opacity(0.18, dict(ETATS).get(
                row.get("Etat") or "À faire", BLUE)),
            border_radius=8, padding=14, ink=True,
            on_click=lambda e: _details(row))

    def _etat_sections():
        """Une liste repliable par état, dans l'ordre manuel de Hub."""
        def _toggle(e):
            # Un seul tiroir ouvert à la fois (retour user).
            etat = e.control.data
            state["open"] = set() if etat in state["open"] else {etat}
            render()
        out = []
        for etat, color in ETATS:
            rows = [r for r in state["tasks"]
                    if (r.get("Etat") or "À faire") == etat]
            # En-tête comme les colonnes de Hub : bandeau plein, texte
            # noir. Pas d'ExpansionTile : il réserve une marge à droite.
            is_open = etat in state["open"]
            out.append(ft.Container(
                ft.Row([
                    ft.Text(f"{etat}  ({len(rows)})", color=ft.Colors.BLACK,
                            weight=ft.FontWeight.W_700, expand=True),
                    ft.Icon(ft.Icons.EXPAND_LESS if is_open
                            else ft.Icons.EXPAND_MORE,
                            color=ft.Colors.BLACK)]),
                bgcolor=ft.Colors.with_opacity(0.85, color),
                border_radius=6, padding=ft.Padding(12, 12, 8, 12),
                data=etat, on_click=_toggle, ink=True))
            if is_open:
                out.extend([_task_card(r) for r in rows] if rows else
                           [ft.Text("Rien ici", color=GREY)])
        return out

    # ── Agenda ───────────────────────────────────────────────────────
    def _event_card(start, source, color, row):
        hour = start[11:16] if len(start) > 10 else ""
        bits = [x for x in (row.get("Objets") and ", ".join(row["Objets"]),
                            row.get("État") or row.get("Etat"),
                            row.get("Téléphone")) if x]
        title = row.get("Nom") or row.get("Demande") or "—"
        return ft.Container(ft.Row([
            ft.Container(width=4, height=44, bgcolor=color, border_radius=2),
            ft.Column([ft.Text(f"{hour}  {title}".strip(),
                               size=16),
                       ft.Text(" · ".join([source, *bits]), size=13,
                               color=GREY)], spacing=2, tight=True,
                      expand=True)]),
            bgcolor=CARD, border_radius=10, padding=12,
            on_click=(lambda e: _details(row)) if source == "Tâche"
            else None)

    # ── IA ───────────────────────────────────────────────────────────
    prompt = ft.TextField(hint_text="Décris l'image…", multiline=True,
                          min_lines=3, max_lines=8,
                          border_radius=C.BUTTON_RADIUS)
    ia_status = ft.Text("", size=13, color=GREY)
    picker = ft.FilePicker()
    prompts_file = CONSTANTS.state_file(".ai_prompts.json")  # = Hub

    def _prompts():
        try:
            with open(prompts_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _prompts_save(paths, asked, refined):
        data = _prompts()
        for p in paths:
            data[os.path.normcase(p)] = {"asked": asked, "refined": refined}
        try:
            with open(prompts_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
    page.services.append(picker)

    async def _pick(e):
        files = await picker.pick_files(file_type=ft.FilePickerFileType.IMAGE,
                                        with_data=True)
        if files and files[0].bytes:
            os.makedirs(IA_DIR, exist_ok=True)
            path = os.path.join(IA_DIR, "source_" + datetime.datetime.now()
                                .strftime("%Y%m%d_%H%M%S_") + files[0].name)
            with open(path, "wb") as f:
                f.write(files[0].bytes)
            state["source"] = path
            render()

    def _generate(e):
        text = (prompt.value or "").strip()
        if not text or state["busy"]:
            return
        state["busy"] = True
        src = state["source"]
        src_bytes = open(src, "rb").read() if src else None
        n, aspect = state["count"], state["format"]
        quality = state["quality"]
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        kind = "edited" if src_bytes else "generated"
        muse = state["model"] == "muse"
        if muse:
            kind = "muse_" + kind
        gen = meta_ai.generate_image if muse else _gemini_generate_image
        os.makedirs(IA_DIR, exist_ok=True)

        def _run():
            refined = text
            if state["refine"] and not muse:
                ia_status.value = "✍️ Affinage de la demande…"
                page.update()
                try:
                    refined = _gemini_refine_image_prompt(
                        intent_prompt=text, user_request=text,
                        mode="edit_image" if src_bytes else "generate_image",
                        source_filename=os.path.basename(src or ""),
                        model=CONSTANTS.AI_IMAGE_REFINER_MODEL) or text
                except Exception:
                    pass
            ia_status.value = f"🎨 {n} image(s) en cours…"
            page.update()
            left = {"n": n, "err": [], "out": []}
            done = threading.Event()

            def _one(i):
                try:
                    msg, img = gen(
                        refined, input_image_bytes=src_bytes,
                        aspect_ratio=aspect, resolution=quality)
                except Exception as exc:
                    msg, img = str(exc), None
                if img:
                    out = os.path.join(IA_DIR, f"{kind}_{stamp}_{i + 1}.png")
                    with open(out, "wb") as f:
                        f.write(img)
                    left["out"].append(out)
                else:
                    left["err"].append(msg)
                left["n"] -= 1
                if left["n"] == 0:
                    done.set()
            for i in range(n):
                threading.Thread(target=_one, args=(i,), daemon=True).start()
            done.wait()
            _prompts_save(left["out"], text, refined)
            state["busy"] = False
            ia_status.value = ("Erreur : " + left["err"][0][:200]
                               if left["err"] else "")
            state["images"] = list_images()
            render()
        threading.Thread(target=_run, daemon=True).start()
        render()

    def _ia_view():
        def _seg(options, key, cast=str):
            def _on(e):
                state[key] = cast(next(iter(e.control.selected)))
                render()
            return ft.SegmentedButton(
                segments=[ft.Segment(value=str(v), label=ft.Text(t))
                          for v, t in options],
                selected=[str(state[key])], on_change=_on)
        src = state["source"]
        src_row = ft.Row([
            ft.OutlinedButton("Photo source", icon=ft.Icons.ADD_PHOTO_ALTERNATE,
                              on_click=_pick)])
        if src:
            src_row.controls = [
                ft.Image(src=thumb(src, 200), width=72, height=72,
                         fit=ft.BoxFit.COVER, border_radius=8),
                ft.Text(os.path.basename(src), size=12, color=GREY,
                        expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=lambda e: (
                    state.update(source=None), render()))]
        return [prompt, src_row,
                _seg([("gemini", "Gemini"), ("muse", "Muse")], "model"),
                _seg(FORMATS, "format"),
                *([] if state["model"] == "muse" else
                  [_seg([(q, q) for q in ("1K", "2K", "4K")], "quality")]),
                _seg([(n, f"×{n}") for n in (1, 2, 3, 4)], "count", int),
                ft.Switch(label="Affiner", value=state["refine"],
                          disabled=state["model"] == "muse",
                          on_change=lambda e: state.update(
                              refine=e.control.value)),
                ft.FilledButton("Générer", icon=ft.Icons.AUTO_AWESOME,
                                on_click=_generate, disabled=state["busy"],
                                height=48),
                ft.ProgressBar(visible=state["busy"]), ia_status,
                ft.Divider(height=16),
                *_gallery_view()]

    # ── Galerie ──────────────────────────────────────────────────────
    # Images IA (GALLERY_ROOTS). Tap = plein écran ; appui long =
    # sélection multiple → Supprimer.
    # Les fichiers vont dans la corbeille du Pi (gio trash), jamais rm.
    viewer = ft.BottomSheet(ft.Container(), bgcolor="#000000",
                            fullscreen=True, scrollable=True,
                            show_drag_handle=True)
    page.overlay.append(viewer)

    def _trash(paths):
        for p in paths:
            try:
                subprocess.run(["gio", "trash", p], check=True,
                               capture_output=True, timeout=10)
            except Exception as exc:
                status.value = f"Suppression impossible : {exc}"
        state["picked"].clear()
        state["images"] = list_images()
        viewer.open = False
        render()

    def _open_image(path):
        def _use(e):
            state["source"] = path
            viewer.open = False
            render()
            page.run_task(body.scroll_to, 0, None, None, 300)
        info = _prompts().get(os.path.normcase(path))

        def _again(e):
            prompt.value = info["asked"]
            viewer.open = False
            render()
            page.run_task(body.scroll_to, 0, None, None, 300)
        texts = []
        if info:
            texts.append(ft.Text("Demande : " + info["asked"], size=13,
                                 selectable=True))
            if info["refined"] != info["asked"]:
                texts.append(ft.Text("Affiné : " + info["refined"], size=12,
                                     color=GREY, selectable=True))
        viewer.content = ft.Container(ft.Column([
            ft.InteractiveViewer(
                ft.Image(src=thumb(path, 1600), fit=ft.BoxFit.CONTAIN),
                min_scale=1, max_scale=6, expand=True),
            ft.Text(os.path.relpath(path, HOME), size=12, color=GREY),
            *texts,
            ft.Row([
                ft.FilledButton("Modifier avec l'IA",
                                icon=ft.Icons.AUTO_AWESOME, on_click=_use),
                *([ft.OutlinedButton("Reprendre la demande",
                                     icon=ft.Icons.HISTORY, on_click=_again)]
                  if info else []),
                ft.OutlinedButton("Supprimer", icon=ft.Icons.DELETE_OUTLINE,
                                  style=ft.ButtonStyle(color=RED),
                                  on_click=lambda e: _trash([path]))],
                wrap=True),
        ], spacing=10, expand=True), padding=12, expand=True)
        viewer.open = True
        page.update()

    def _tile_tap(p):
        if state["picked"]:
            state["picked"] ^= {p}
            render()
        else:
            _open_image(p)

    def _tile_long(p):
        state["picked"] ^= {p}
        render()

    def _grid(paths):
        # Tuiles à taille fixe (3 par ligne sur iPhone) : avec
        # ResponsiveRow + aspect_ratio, elles faisaient 0 px de haut.
        cols = max(3, int((page.width or 390) // 160))
        side = ((page.width or 390) - 24 - 4 * (cols - 1)) // cols
        tiles = []
        for p in paths:
            try:
                data = thumb(p)
            except Exception:
                continue
            picked = p in state["picked"]
            tiles.append(ft.GestureDetector(
                ft.Container(
                    ft.Stack([
                        ft.Image(src=data, fit=ft.BoxFit.COVER, width=side,
                                 height=side,
                                 opacity=0.55 if picked else 1),
                        ft.Icon(ft.Icons.CHECK_CIRCLE, color=BLUE,
                                right=4, top=4, visible=picked)]),
                    width=side, height=side, border_radius=6,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE),
                on_tap=lambda e, p=p: _tile_tap(p),
                on_long_press_start=lambda e, p=p: _tile_long(p)))
        return ft.Row(tiles, wrap=True, spacing=4, run_spacing=4)

    def _gallery_view():
        imgs = state["images"]
        n = len(state["picked"])
        if n:
            head = ft.Row([
                ft.Text(f"{n} sélectionnée(s)", expand=True),
                ft.TextButton("Tout", on_click=lambda e: (
                    state["picked"].update(imgs[:state["shown"]]),
                    render())),
                ft.TextButton("Annuler", on_click=lambda e: (
                    state["picked"].clear(), render())),
                ft.FilledButton("Supprimer", icon=ft.Icons.DELETE_OUTLINE,
                                bgcolor=RED,
                                on_click=lambda e: _trash(
                                    list(state["picked"])))])
        else:
            head = ft.Text(f"Galerie · {len(imgs)} images  ·  appui long "
                           "pour sélectionner", size=14, color=GREY,
                           weight=ft.FontWeight.BOLD)
        out = [head, _grid(imgs[:state["shown"]])]
        if len(imgs) > state["shown"]:
            out.append(ft.TextButton("Plus", on_click=lambda e: (
                state.update(shown=state["shown"] + 60), render())))
        return out

    # ── Listes (todo + prix, mêmes données que Hub via hub_sync) ─────
    LIST_COLORS = [BLUE, VIOLET, GREEN, C.COLOR_YELLOW_GREEN, C.COLOR_MINT,
                   YELLOW, ORANGE, RED, PINK, C.COLOR_BLUE_DARK]
    NEW_CAT = "＋ Nouvelle catégorie…"

    def _list_load():
        try:
            for name in ("liste", "prix"):
                state[name] = hub_sync.get(name) or []
        except Exception as exc:
            status.value = f"Listes injoignables : {exc}"
        render()

    def _list_save(name):
        try:
            hub_sync.put(name, state[name])
        except Exception as exc:
            status.value = f"Pas enregistré : {exc}"
        render()

    def _last_cats(name=None, value=None):
        """Dernière catégorie choisie par liste, gardée entre sessions."""
        path = os.path.join(HOME, ".hub_mobile_lastcat.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if name:
            data[name] = value
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
            except OSError:
                pass
        return data

    def _list_toggle(row, value):
        row["fait"] = str(value)
        _list_save("liste")

    def _list_edit(name, row=None):
        """Fiche d'ajout / d'édition : toutes les colonnes de la liste,
        catégorie obligatoire (existante ou nouvelle)."""
        rows = state[name]
        cols = []
        for r in rows:
            cols += [k for k in r if k not in cols]
        cols = [c for c in cols if c not in ("catégorie", "fait")] or (
            ["tâche"] if name == "liste" else ["article", "prix"])
        cats = list(dict.fromkeys(
            str(r.get("catégorie", "")).strip() for r in rows
            if str(r.get("catégorie", "")).strip()))
        last = _last_cats().get(name)
        cur = (row or {}).get("catégorie") or (
            last if last in cats else
            (str(rows[-1].get("catégorie", "")).strip() or None)
            if rows else None)
        new_cat = ft.TextField(label="Nouvelle catégorie", visible=False,
                               border_radius=C.BUTTON_RADIUS)
        cat = ft.Dropdown(
            label="Catégorie", value=cur, width=150,
            border_radius=C.BUTTON_RADIUS,
            options=[ft.DropdownOption(c) for c in cats + [NEW_CAT]])

        def _cat_changed(e):
            new_cat.visible = cat.value == NEW_CAT
            page.update()
        cat.on_select = _cat_changed
        fields = {c: ft.TextField(
            label=c.capitalize(), value=str((row or {}).get(c, "") or ""),
            multiline=True, min_lines=1, max_lines=6,
            border_radius=C.BUTTON_RADIUS) for c in cols}

        def _ok(e):
            category = (new_cat.value or "").strip() \
                if cat.value == NEW_CAT else cat.value
            if not category:
                cat.error_text = "Obligatoire"
                page.update()
                return
            target = row if row is not None else {}
            target["catégorie"] = category
            for c, f in fields.items():
                target[c] = f.value or ""
            if row is None:
                if name == "liste":
                    target["fait"] = "False"
                rows.append(target)
            _last_cats(name, category)
            list_sheet.open = False
            _list_save(name)

        def _del(e):
            rows.remove(row)
            list_sheet.open = False
            _list_save(name)
        list_sheet.content = ft.Container(ft.Column([
            # Catégorie à gauche puis le texte, comme dans Hub.
            ft.Row([cat, ft.Container(list(fields.values())[0],
                                      expand=True)],
                   vertical_alignment=ft.CrossAxisAlignment.START),
            new_cat, *list(fields.values())[1:],
            ft.Row([
                ft.FilledButton("Enregistrer", icon=ft.Icons.CHECK,
                                on_click=_ok),
                *([ft.OutlinedButton("Supprimer",
                                     icon=ft.Icons.DELETE_OUTLINE,
                                     style=ft.ButtonStyle(color=RED),
                                     on_click=_del)] if row else [])])],
            tight=True, spacing=12, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=20)
        list_sheet.open = True
        page.update()

    list_sheet = ft.BottomSheet(ft.Container(), bgcolor=CARD,
                                scrollable=True)
    page.overlay.append(list_sheet)

    def _list_view():
        name = state["list_kind"]
        rows = state.get(name)
        out = [ft.SegmentedButton(
            segments=[ft.Segment(value="liste", label=ft.Text("À faire")),
                      ft.Segment(value="prix", label=ft.Text("Prix"))],
            selected=[name], on_change=lambda e: (state.update(
                list_kind=next(iter(e.control.selected))), render()))]
        if rows is None:
            threading.Thread(target=_list_load, daemon=True).start()
            state[name] = []
            return out + [ft.ProgressRing()]
        cats = list(dict.fromkeys(
            str(r.get("catégorie", "")).strip() for r in rows))
        out.append(ft.FilledButton(
            "Ajouter", icon=ft.Icons.ADD,
            on_click=lambda e: _list_edit(name)))
        for i, cat in enumerate(cats):
            color = LIST_COLORS[i % len(LIST_COLORS)]
            out.append(ft.Container(
                ft.Text((cat or "Sans catégorie").upper(),
                        weight=ft.FontWeight.W_600,
                        text_align=ft.TextAlign.CENTER),
                alignment=ft.Alignment(0, 0), border_radius=6,
                bgcolor=ft.Colors.with_opacity(0.25, color),
                padding=ft.Padding(10, 8, 10, 8)))
            for r in rows:
                if str(r.get("catégorie", "")).strip() != cat:
                    continue
                if name == "liste":
                    done = str(r.get("fait")).lower() in ("true", "1")
                    content = ft.Row([
                        ft.Checkbox(value=done, on_change=lambda e, r=r:
                                    _list_toggle(r, e.control.value)),
                        ft.Text(r.get("tâche", ""), expand=True,
                                color=GREY if done else None,
                                style=ft.TextStyle(
                                    decoration=ft.TextDecoration.LINE_THROUGH)
                                if done else None)])
                else:
                    content = ft.Row([
                        ft.Text(r.get("article", ""), expand=True),
                        ft.Text(str(r.get("prix", "")),
                                weight=ft.FontWeight.W_600)])
                out.append(ft.Container(content, bgcolor=CARD,
                                        border_radius=8, ink=True,
                                        on_click=lambda e, r=r:
                                        _list_edit(name, r),
                                        padding=ft.Padding(8, 4, 12, 4)))
        return out

    # ── Briefing ─────────────────────────────────────────────────────
    async def _open_link(e):
        await ft.UrlLauncher().launch_url(e.data)

    def _briefing_view():
        try:
            with open(BRIEFING, encoding="utf-8") as f:
                text = f.read()
            when = datetime.datetime.fromtimestamp(os.path.getmtime(BRIEFING))
        except OSError:
            return [ft.Text("Pas encore de briefing", color=GREY)]
        return [ft.Text(f"{day_label(when.date().isoformat())} à "
                        f"{when:%H:%M}", size=12, color=GREY),
                ft.Container(ft.Markdown(
                    text, selectable=True,
                    extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
                    on_tap_link=_open_link),
                    bgcolor=CARD, border_radius=10, padding=14)]

    # ── Actus (mêmes flux que l'onglet Actus de Hub) ─────────────────
    CAT_COLORS = dict(zip(rss_feeds.CATEGORIES, [VIOLET, BLUE, GREEN, GREY,
                                                 ORANGE]))

    def _load_news(e=None):
        state["news"] = []

        def _run():
            try:
                state["news"] = load_news()
            except Exception as exc:
                status.value = f"Actus : {exc}"
            render()
        # Pas de render() ici : appelé depuis render() (_news_view), un
        # rendu imbriqué mélangeait les onglets (actu affichée dans Tâches).
        threading.Thread(target=_run, daemon=True).start()

    def _news_card(it):
        when = it.get("date")
        meta = " · ".join(x for x in (
            it.get("source"), when and when.astimezone().strftime(
                "%d/%m %H:%M")) if x)
        row = [ft.Column([
            ft.Text(it.get("title") or "", size=15,
                    weight=ft.FontWeight.W_500, max_lines=3),
            ft.Text(meta, size=12,
                    color=CAT_COLORS.get(it.get("category"), GREY)),
        ], spacing=4, tight=True, expand=True)]
        if it.get("image"):
            row.append(ft.Image(src=it["image"], width=72, height=72,
                                fit=ft.BoxFit.COVER, border_radius=8,
                                error_content=ft.Container()))
        return ft.Container(ft.Row(row, spacing=10), bgcolor=CARD,
                            border_radius=10, padding=12,
                            on_click=lambda e, it=it: _read(it))

    def _read(it):
        """Lecteur plein écran (comme la colonne de droite de Hub) : résumé
        RSS tout de suite, article complet chargé en fond."""
        md = ft.Markdown(
            it.get("full") or it.get("summary") or "", selectable=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_FLAVORED,
            on_tap_link=_open_link)
        loading = ft.Text("Chargement de l'article…", size=12, color=GREY,
                          italic=True,
                          visible="full" not in it
                          and it.get("category") != "Podcasts")
        when = it.get("date")
        viewer.content = ft.Container(ft.Column([
            ft.Text(it.get("title") or "", size=20,
                    weight=ft.FontWeight.BOLD),
            ft.Text(" · ".join(x for x in (
                it.get("source"), when and when.astimezone().strftime(
                    "%d/%m %H:%M")) if x), size=12,
                color=CAT_COLORS.get(it.get("category"), GREY)),
            loading, md,
            ft.OutlinedButton("Ouvrir dans Safari", icon=ft.Icons.OPEN_IN_NEW,
                              on_click=lambda e: page.run_task(
                                  _launch, it.get("link"))),
        ], spacing=10, scroll=ft.ScrollMode.AUTO, expand=True),
            padding=16, expand=True)
        viewer.open = True
        page.update()
        if loading.visible:
            def _work():
                it["full"] = rss_feeds.fetch_article_text(it["link"])
                if it["full"]:
                    md.value = it["full"]
                loading.visible = False
                page.update()
            threading.Thread(target=_work, daemon=True).start()

    async def _launch(url):
        if url:
            await ft.UrlLauncher().launch_url(url)

    def _news_view():
        if state["news"] is None:
            _load_news()
        items = state["news"] or []
        if not items:
            return [ft.ProgressRing(), ft.Text("Chargement des flux…",
                                               color=GREY)]

        def _pick(e):
            c = e.control.data
            state["news_cat"] = None if state["news_cat"] == c else c
            render()
        chips = ft.Row([ft.Chip(
            label=ft.Text(c), data=c, selected=state["news_cat"] == c,
            selected_color=CAT_COLORS[c] + "55", on_select=_pick)
            for c in rss_feeds.CATEGORIES], scroll=ft.ScrollMode.AUTO,
            spacing=6)
        shown = [it for it in items if state["news_cat"] in
                 (None, it.get("category"))][:80]
        return [chips, *[_news_card(it) for it in shown]]

    # ── Rendu / chargement ───────────────────────────────────────────
    render_lock = threading.RLock()

    def render():
        # Rendus concurrents (fils de chargement + clics) : un à la fois,
        # sinon la liste se remplit avec le contenu de deux onglets.
        with render_lock:
            _render()

    def _render():
        search_bar.visible = state["tab"] == 0
        body.controls = []
        if state["tab"] == 0:
            q = _fold(search.value).strip()
            if q:
                rows = [r for r in state["tasks"] if q in _fold(" ".join(
                    str(r.get(k) or "") for k in (
                        "Demande", "Téléphone", "E-mail", "Etat")))]
                body.controls += [_task_card(r, etat=True) for r in rows] \
                    or [ft.Text("Aucune carte", color=GREY)]
            else:
                body.controls += _etat_sections()
        elif state["tab"] == 5:
            body.controls += _list_view()
        elif state["tab"] == 4:
            body.controls += _news_view()
        elif state["tab"] == 3:
            body.controls += _briefing_view()
        elif state["tab"] == 2:
            body.controls += _ia_view()
        else:
            last = None
            for start, source, color, row in state.get("agenda", []):
                label = day_label(start)
                if label != last:
                    body.controls.append(ft.Text(label, size=14,
                                                 color=GREY,
                                                 weight=ft.FontWeight.BOLD))
                    last = label
                body.controls.append(_event_card(start, source, color, row))
            if last is None:
                body.controls.append(ft.Text("Rien les 60 prochains jours",
                                             color=GREY))
        body.controls.insert(0, status)
        page.update()

    def refresh(e=None):
        """Bouton = rechargement forcé ; sinon cache (< 1 h)."""
        force = e is not None
        if force:
            state["liste"] = state["prix"] = None
        status.value = "Chargement…"
        page.update()

        def _run():
            try:
                tasks, agenda, at = load_data(force=force)
                state["tasks"], state["agenda"] = tasks, agenda
                state["images"] = list_images()
                if force and state["tab"] == 4:
                    state["news"] = load_news(max_age=0)
                status.value = ("Mis à jour à " + datetime.datetime
                                .fromtimestamp(at).strftime("%H:%M"))
            except Exception as exc:
                status.value = f"Erreur : {exc}"
            render()
        threading.Thread(target=_run, daemon=True).start()

    def _tab(e):
        state["tab"] = NAV[e.control.selected_index][0]
        if state["tab"] == 5:  # relu à chaque visite : Hub a pu écrire
            state["liste"] = state["prix"] = None
        render()

    page.appbar = ft.AppBar(
        title=ft.Text("Hub"), bgcolor=BG,
        actions=[ft.IconButton(ft.Icons.REFRESH, on_click=refresh)])
    # Ordre d'affichage (retour user) → identifiant interne de l'onglet.
    NAV = [(0, ft.Icons.VIEW_KANBAN_OUTLINED, "Tâches"),
           (1, ft.Icons.CALENDAR_MONTH_OUTLINED, "Agenda"),
           (5, ft.Icons.CHECKLIST, "Listes"),
           (2, ft.Icons.AUTO_AWESOME_OUTLINED, "IA"),
           (3, ft.Icons.WB_SUNNY_OUTLINED, "Briefing"),
           (4, ft.Icons.RSS_FEED_OUTLINED, "Actus")]
    page.navigation_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=icon, label=label)
            for _, icon, label in NAV],
        on_change=_tab, bgcolor=CARD)
    page.add(ft.SafeArea(ft.Column([search_bar, body], spacing=0,
                                   expand=True), expand=True))
    refresh()

    def _hourly():
        # Session ouverte : rechargement automatique toutes les heures.
        while True:
            time.sleep(DATA_TTL)
            try:
                refresh(None)
            except Exception:
                return  # session fermée
    threading.Thread(target=_hourly, daemon=True).start()


if __name__ == "__main__":
    _load_data_cache()
    threading.Thread(target=load_news, daemon=True).start()
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0",
           assets_dir=os.path.join(os.path.dirname(
               os.path.abspath(__file__)), "assets"),
           port=int(os.environ.get("HUB_MOBILE_PORT", 8550)))
