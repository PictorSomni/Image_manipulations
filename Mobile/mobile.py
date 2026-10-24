# -*- coding: utf-8 -*-
"""
Hub mobile : Tâches + Agenda pour iPhone / iPad, en web app servie par le
Pi (Tailscale, http://100.124.227.50:8550 : le nom court ne résout pas
sur iOS → « Ajouter à l'écran d'accueil »).

Mêmes données que Hub : Notion (Data/notion_rest.py) pour les cartes et
l'agenda, ordre manuel des cartes partagé via le Pi (hub_sync
"kanban_ordre"). Rien n'est dupliqué : Hub reste l'outil complet.
"""

__version__ = "2.10.87"

import base64
import datetime
import io
import os
import sys
import threading
import unicodedata

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "Data"))
import flet as ft  # noqa: E402
import CONSTANTS  # noqa: E402
import hub_sync  # noqa: E402
from ai_tools import (  # noqa: E402
    _gemini_generate_image, _gemini_refine_image_prompt)
from PIL import Image  # noqa: E402
import notion_rest  # noqa: E402
import rss_feeds  # noqa: E402

KANBAN_DS = "34f4c64b-5c00-4415-99cb-76234faecef1"
ETATS = [("À faire", "#5B9BD5"), ("En cours / en attente", "#B388FF"),
         ("A commander", "#E5C07B"), ("Commandé", "#E59866"),
         ("Terminé", "#98C379")]
AGENDA = [("Studio", "ae971f83-22d1-4d53-8972-4c6302c6d371", "#5B9BD5"),
          ("Reportage", "42f7bb5c-84f2-416a-aad0-8aad7b1ea51a", "#B388FF"),
          ("Location", "23f887c8-202a-4e37-91e1-812a4a6c7472", "#98C379")]
BG, CARD, GREY = "#1E1F24", "#2A2C33", "#9AA0A6"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi",
         "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]


HOME = os.path.expanduser("~")
IA_DIR = os.path.join(HOME, "IA")
# Galerie : dossiers d'images du Pi (pas les sites web / modules en dev).
GALLERY_ROOTS = [IA_DIR, os.path.join(HOME, "Pictures"),
                 os.path.join(HOME, "partage"),
                 os.path.join(HOME, "hub_inbox"),
                 os.path.join(HOME, "Documents", "Studio C"),
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


def load_news(max_age=900):
    """Flux Actus partagés entre sessions, rechargés après 15 min."""
    import time
    if _NEWS["items"] is None or time.time() - _NEWS["at"] > max_age:
        _NEWS["items"] = rss_feeds.fetch_all_feeds()
        _NEWS["at"] = time.time()
    return _NEWS["items"]


def load_agenda(days=60):
    today = datetime.date.today().isoformat()
    end = (datetime.date.today() + datetime.timedelta(days)).isoformat()
    events = []
    for name, ds, color in AGENDA:
        for r in _query(ds):
            start = r.get("date:Date:start") or ""
            if today <= start[:10] <= end:
                events.append((start, name, color, r))
    return sorted(events, key=lambda e: e[0])


def day_label(iso):
    d = datetime.date.fromisoformat(iso[:10])
    delta = (d - datetime.date.today()).days
    base = f"{JOURS[d.weekday()]} {d.day} {MOIS[d.month - 1]}"
    return {0: "Aujourd'hui", 1: "Demain"}.get(delta, base.capitalize())


assert day_label(datetime.date.today().isoformat()) == "Aujourd'hui"


def main(page: ft.Page):
    page.title = "Hub"
    page.bgcolor = BG
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 0
    state = {"open": {"À faire"}, "tasks": [], "tab": 0, "images": [],
             "shown": 60, "source": None, "format": "1:1", "count": 1,
             "busy": False, "news": None, "news_cat": None}

    status = ft.Text("", size=12, color=GREY)
    search = ft.TextField(
        hint_text="Rechercher une carte", prefix_icon=ft.Icons.SEARCH,
        border_radius=24, dense=True, on_change=lambda e: render(),
        content_padding=ft.Padding(12, 8, 12, 8))
    search_bar = ft.Container(search, padding=ft.Padding(12, 8, 12, 0))
    body = ft.ListView(expand=True, spacing=8,
                       padding=ft.Padding(12, 8, 12, 24))

    # ── Tâches ───────────────────────────────────────────────────────
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
                           ("Prix", "Prix"), ("Projet", "Projet ?"),
                           ("Payé", "Payé ?"), ("Créé le", "Créé le")):
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
        sheet.content = ft.Container(ft.Column([
            ft.Text(row.get("Demande") or "(sans titre)", size=18,
                    weight=ft.FontWeight.BOLD),
            *info, ft.Row(actions),
            ft.Text("Déplacer vers", size=12, color=GREY),
            ft.Row(etats, wrap=True, spacing=8, run_spacing=8),
        ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO),
            padding=20)
        sheet.open = True
        page.update()

    def _task_card(row, etat=False):
        deadline = row.get("date:Deadline:start") or ""
        sub = []
        if etat:
            name = row.get("Etat") or "À faire"
            sub.append(ft.Text(name, size=13,
                               color=dict(ETATS).get(name, GREY)))
        if deadline:
            sub.append(ft.Text(f"⏰ {day_label(deadline)}", size=13,
                               color="#E5C07B"))
        if row.get("Téléphone"):
            sub.append(ft.Text(row["Téléphone"], size=13, color=GREY))
        return ft.Container(
            ft.Column([ft.Text(row.get("Demande") or "(sans titre)",
                               size=16), *sub], spacing=4, tight=True),
            bgcolor=CARD, border_radius=10, padding=14, ink=True,
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
            out.append(ft.ExpansionTile(
                title=ft.Text(f"{etat}  ({len(rows)})", color=color,
                              weight=ft.FontWeight.BOLD),
                data=etat, expanded=etat in state["open"],
                on_change=_toggle, maintain_state=True,
                controls_padding=ft.Padding(0, 0, 0, 8),
                controls=[ft.Column(
                    [_task_card(r) for r in rows], spacing=8,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH)]
                if rows else
                [ft.Text("Rien ici", color=GREY)]))
        return out

    # ── Agenda ───────────────────────────────────────────────────────
    def _event_card(start, source, color, row):
        hour = start[11:16] if len(start) > 10 else ""
        bits = [x for x in (row.get("Objets") and ", ".join(row["Objets"]),
                            row.get("État") or row.get("Etat"),
                            row.get("Téléphone")) if x]
        return ft.Container(ft.Row([
            ft.Container(width=4, height=44, bgcolor=color, border_radius=2),
            ft.Column([ft.Text(f"{hour}  {row.get('Nom') or '—'}".strip(),
                               size=16),
                       ft.Text(" · ".join([source, *bits]), size=13,
                               color=GREY)], spacing=2, tight=True,
                      expand=True)]),
            bgcolor=CARD, border_radius=10, padding=12)

    # ── IA ───────────────────────────────────────────────────────────
    prompt = ft.TextField(hint_text="Décris l'image…", multiline=True,
                          min_lines=3, max_lines=8, border_radius=10)
    ia_status = ft.Text("", size=13, color=GREY)
    picker = ft.FilePicker()
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
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        kind = "edited" if src_bytes else "generated"
        os.makedirs(IA_DIR, exist_ok=True)

        def _run():
            ia_status.value = "✍️ Affinage de la demande…"
            page.update()
            try:
                refined = _gemini_refine_image_prompt(
                    intent_prompt=text, user_request=text,
                    mode="edit_image" if src_bytes else "generate_image",
                    source_filename=os.path.basename(src or ""),
                    model=CONSTANTS.AI_IMAGE_REFINER_MODEL)
            except Exception:
                refined = text
            ia_status.value = f"🎨 {n} image(s) en cours…"
            page.update()
            left = {"n": n, "err": []}
            done = threading.Event()

            def _one(i):
                try:
                    msg, img = _gemini_generate_image(
                        refined, input_image_bytes=src_bytes,
                        aspect_ratio=aspect, resolution="1K")
                except Exception as exc:
                    msg, img = str(exc), None
                if img:
                    with open(os.path.join(
                            IA_DIR, f"{kind}_{stamp}_{i + 1}.png"),
                            "wb") as f:
                        f.write(img)
                else:
                    left["err"].append(msg)
                left["n"] -= 1
                if left["n"] == 0:
                    done.set()
            for i in range(n):
                threading.Thread(target=_one, args=(i,), daemon=True).start()
            done.wait()
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
                _seg(FORMATS, "format"),
                _seg([(n, f"×{n}") for n in (1, 2, 3, 4)], "count", int),
                ft.FilledButton("Générer", icon=ft.Icons.AUTO_AWESOME,
                                on_click=_generate, disabled=state["busy"],
                                height=48),
                ft.ProgressBar(visible=state["busy"]), ia_status,
                ft.Divider(height=16),
                *_gallery_view()]

    # ── Galerie ──────────────────────────────────────────────────────
    def _open_image(path):
        def _use(e):
            state["source"] = path
            sheet.open = False
            render()
            page.run_task(body.scroll_to, 0, None, None, 300)
        sheet.content = ft.Container(ft.Column([
            ft.Image(src=thumb(path, 1400), fit=ft.BoxFit.CONTAIN),
            ft.Text(os.path.relpath(path, HOME), size=12, color=GREY),
            ft.FilledButton("Modifier avec l'IA", icon=ft.Icons.AUTO_AWESOME,
                            on_click=_use),
        ], tight=True, spacing=10, scroll=ft.ScrollMode.AUTO), padding=16)
        sheet.open = True
        page.update()

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
            tiles.append(ft.Container(
                ft.Image(src=data, fit=ft.BoxFit.COVER, width=side,
                         height=side),
                width=side, height=side, border_radius=6,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                on_click=lambda e, p=p: _open_image(p)))
        return ft.Row(tiles, wrap=True, spacing=4, run_spacing=4)

    def _gallery_view():
        imgs = state["images"]
        out = [ft.Text(f"Galerie · {len(imgs)} images", size=14,
                       color=GREY, weight=ft.FontWeight.BOLD),
               _grid(imgs[:state["shown"]])]
        if len(imgs) > state["shown"]:
            out.append(ft.TextButton("Plus", on_click=lambda e: (
                state.update(shown=state["shown"] + 60), render())))
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
    CAT_COLORS = dict(zip(rss_feeds.CATEGORIES, ["#B388FF", "#5B9BD5",
                                                 "#98C379", GREY, "#E59866"]))

    def _load_news(e=None):
        state["news"] = []

        def _run():
            try:
                state["news"] = load_news()
            except Exception as exc:
                status.value = f"Actus : {exc}"
            render()
        threading.Thread(target=_run, daemon=True).start()
        render()

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
                            on_click=lambda e, u=it.get("link"):
                            page.run_task(_launch, u))

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
    def render():
        search_bar.visible = state["tab"] == 0
        body.controls.clear()
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
        status.value = "Chargement…"
        page.update()

        def _run():
            try:
                state["tasks"] = load_tasks()
                state["agenda"] = load_agenda()
                state["images"] = list_images()
                if state["tab"] == 4:
                    state["news"] = load_news(max_age=0)
                status.value = ("Mis à jour à "
                                + datetime.datetime.now().strftime("%H:%M"))
            except Exception as exc:
                status.value = f"Erreur : {exc}"
            render()
        threading.Thread(target=_run, daemon=True).start()

    def _tab(e):
        state["tab"] = e.control.selected_index
        render()

    page.appbar = ft.AppBar(
        title=ft.Text("Hub"), bgcolor=BG,
        actions=[ft.IconButton(ft.Icons.REFRESH, on_click=refresh)])
    page.navigation_bar = ft.NavigationBar(
        destinations=[
            ft.NavigationBarDestination(icon=ft.Icons.VIEW_KANBAN_OUTLINED,
                                        label="Tâches"),
            ft.NavigationBarDestination(icon=ft.Icons.CALENDAR_MONTH_OUTLINED,
                                        label="Agenda"),
            ft.NavigationBarDestination(icon=ft.Icons.AUTO_AWESOME_OUTLINED,
                                        label="IA"),
            ft.NavigationBarDestination(icon=ft.Icons.WB_SUNNY_OUTLINED,
                                        label="Briefing"),
            ft.NavigationBarDestination(icon=ft.Icons.RSS_FEED_OUTLINED,
                                        label="Actus")],
        on_change=_tab, bgcolor=CARD)
    page.add(ft.SafeArea(ft.Column([search_bar, body], spacing=0,
                                   expand=True), expand=True))
    refresh()


if __name__ == "__main__":
    threading.Thread(target=load_news, daemon=True).start()
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0",
           assets_dir=os.path.join(os.path.dirname(
               os.path.abspath(__file__)), "assets"),
           port=int(os.environ.get("HUB_MOBILE_PORT", 8550)))
