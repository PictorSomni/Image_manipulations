# -*- coding: utf-8 -*-
"""Hub — surface Actus (flux RSS/Atom, Data/rss_feeds.py).

Section extraite de Hub.pyw (main) : build(ui) reçoit l'espace de
noms de main (ui) et renvoie les noms utilisés ailleurs dans Hub."""


import CONSTANTS
import datetime
import flet as ft
import json
import rss_feeds
import threading
import webbrowser


def build(ui):
    BACKGROUND = ui.BACKGROUND
    BLUE = ui.BLUE
    DARK = ui.DARK
    GREEN = ui.GREEN
    GREY = ui.GREY
    LIGHT_GREY = ui.LIGHT_GREY
    ORANGE = ui.ORANGE
    RED = ui.RED
    SQUARE_BTN = ui.SQUARE_BTN
    SURFACE_ACCENT = ui.SURFACE_ACCENT
    TOOLBAR_H = ui.TOOLBAR_H
    VIOLET = ui.VIOLET
    WHITE = ui.WHITE
    _dlg_btn = ui._dlg_btn
    _run_task = ui._run_task
    _surface_title = ui._surface_title
    page = ui.page
    # ═════════════════════════════════════════════════════════════════════
    #  Surface Actus — agrégateur RSS/Atom natif (Data/rss_feeds.py) : news
    #  tech/IA + notes d'épisode de podcasts, fusionnées et triées par date.
    #  Portage Python du prototype web dashboard-perso — pas de WebView
    #  (non supporté sous Windows/Linux desktop par flet-webview), donc
    #  rendu 100% natif Flet ici.
    # ═════════════════════════════════════════════════════════════════════
    actus_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=LIGHT_GREY)
    actus_list_view = ft.ListView(expand=True, spacing=2,
                                  padding=ft.Padding(8, 4, 8, 8))
    actus_state = {"loading": False, "items": [], "fetched": False,
                   "filter": None,
                   "unread_only": False, "selected": None}

    # Couleur par catégorie (retour user : la couleur par source rendait
    # la page bariolée et illisible) — une source = son nom en texte.
    ACTUS_CAT_COLORS = dict(zip(
        rss_feeds.CATEGORIES, [VIOLET, BLUE, GREEN, LIGHT_GREY, ORANGE]))
    _ACTUS_READ_FILE = CONSTANTS.state_file(".actus_read.json")

    def _actus_load_read():
        try:
            with open(_ACTUS_READ_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    actus_read = _actus_load_read()   # liste ordonnée de liens lus

    # Cache des articles (retour user) : la liste et les textes complets
    # déjà chargés s'affichent dès l'ouverture, les flux se rafraîchissent
    # ensuite en fond.
    _ACTUS_CACHE_FILE = CONSTANTS.state_file(".actus_cache.json")

    def _actus_save_cache():
        data = [{**it, "date": it["date"].isoformat() if it["date"]
                 else None} for it in actus_state["items"]]
        try:
            with open(_ACTUS_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except (OSError, TypeError):
            pass

    def _actus_load_cache():
        try:
            with open(_ACTUS_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            for it in data:
                it["date"] = (datetime.datetime.fromisoformat(it["date"])
                              if it["date"] else None)
            return data
        except (OSError, ValueError, KeyError, TypeError):
            return []

    actus_state["items"] = _actus_load_cache()

    def _actus_mark_read(link):
        if not link or link in actus_read:
            return
        actus_read.append(link)
        del actus_read[:-3000]   # ponytail: plafond, assez pour des mois
        try:
            with open(_ACTUS_READ_FILE, "w", encoding="utf-8") as f:
                json.dump(actus_read, f)
        except OSError:
            pass

    def _actus_thumb(item, size):
        color = ACTUS_CAT_COLORS.get(item["category"], GREY)
        fallback = ft.Container(
            ft.Text(item["source"][:1], color=DARK, size=size // 2.5,
                    weight=ft.FontWeight.W_600),
            width=size, height=size, border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.85, color),
            alignment=ft.Alignment(0, 0))
        if not item["image"]:
            return fallback
        return ft.Container(
            ft.Image(src=item["image"], width=size, height=size,
                     fit=ft.BoxFit.COVER, error_content=fallback),
            width=size, height=size, border_radius=6,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS)

    actus_reader = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO,
                             spacing=12)

    def _actus_show(item):
        actus_state["selected"] = item
        _actus_mark_read(item["link"])
        date_txt = (_actus_fr_date(item["date"]) + " · "
                    + item["date"].astimezone().strftime("%H:%M")
                    if item["date"] else "")
        color = ACTUS_CAT_COLORS.get(item["category"], GREY)
        body_text = ft.Markdown(
            item.get("full") or item["summary"] or "Pas de résumé.",
            selectable=True, soft_line_break=True,
            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
            on_tap_link=lambda e: webbrowser.open(e.data))
        controls = []
        if item["image"]:
            controls.append(ft.Container(
                ft.Image(src=item["image"], fit=ft.BoxFit.COVER,
                         height=240, width=float("inf")),
                border_radius=8, clip_behavior=ft.ClipBehavior.ANTI_ALIAS))
        controls += [
            ft.Text(f"{item['source']} · {date_txt}", size=CONSTANTS.TEXT_SM,
                    color=color, weight=ft.FontWeight.W_500),
            ft.Text(item["title"], size=CONSTANTS.TEXT_LG + 4, color=WHITE,
                    weight=ft.FontWeight.W_600, selectable=True),
            body_text,
        ]
        if item["link"]:
            controls.append(ft.Row([_dlg_btn(
                "Lire l'article", color=color,
                on_click=lambda e, u=item["link"]: webbrowser.open(u))]))
        actus_reader.controls = controls
        _actus_render()
        # Texte complet de la page (retour user : résumés RSS trop courts
        # ou absents, ex. TLDR, et lecture sans pubs/pisteurs), chargé en
        # fond et gardé sur l'item ; résumé RSS affiché en attendant et en
        # repli (site qui bloque, podcast).
        if "full" in item or item["category"] == "Podcasts":
            return
        status = ft.Text("Chargement de l'article…", size=11,
                         color=LIGHT_GREY, italic=True)
        actus_reader.controls.insert(controls.index(body_text), status)
        page.update()

        def _work():
            item["full"] = rss_feeds.fetch_article_text(item["link"])
            _actus_save_cache()

            async def _apply():
                if status in actus_reader.controls:
                    actus_reader.controls.remove(status)
                if actus_state["selected"] is item:
                    body_text.value = item["full"] or body_text.value
                page.update()
            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _actus_row(item):
        is_read = item["link"] in actus_read
        is_sel = actus_state["selected"] is item
        time_txt = (item["date"].astimezone().strftime("%H:%M")
                    if item["date"] else "")
        return ft.Container(
            ft.Row([
                _actus_thumb(item, 52),
                ft.Column([
                    ft.Text(item["title"], size=CONSTANTS.TEXT_SM + 1,
                            color=LIGHT_GREY if is_read else WHITE,
                            weight=(ft.FontWeight.W_400 if is_read
                                    else ft.FontWeight.W_600),
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"{item['source']} · {time_txt}", size=11,
                            color=ACTUS_CAT_COLORS.get(item["category"],
                                                       GREY)),
                ], spacing=2, expand=True, tight=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(8, 6, 8, 6), border_radius=8,
            bgcolor=GREY if is_sel else None, ink=True,
            opacity=0.6 if is_read and not is_sel else 1.0,
            on_click=lambda e, it=item: _actus_show(it))

    _JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi",
              "samedi", "dimanche"]
    _MOIS = ["janvier", "février", "mars", "avril", "mai", "juin",
             "juillet", "août", "septembre", "octobre", "novembre",
             "décembre"]

    def _actus_fr_date(dt):
        # strftime("%A") suit la locale de l'OS (souvent anglaise).
        d = dt.astimezone()
        return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"

    def _actus_day_label(dt):
        if dt is None:
            return "Sans date"
        days = (datetime.date.today() - dt.astimezone().date()).days
        return ("Aujourd'hui" if days == 0 else "Hier" if days == 1
                else _actus_fr_date(dt).capitalize())

    def _actus_render():
        cat, unread = actus_state["filter"], actus_state["unread_only"]
        items = [it for it in actus_state["items"]
                 if (cat is None or it["category"] == cat)
                 and not (unread and it["link"] in actus_read)]
        controls, last_day = [], None
        for it in items:
            day = _actus_day_label(it["date"])
            if day != last_day:
                controls.append(ft.Container(
                    ft.Text(day.upper(), size=11, color=LIGHT_GREY,
                            weight=ft.FontWeight.W_600),
                    padding=ft.Padding(8, 12, 0, 4)))
                last_day = day
            controls.append(_actus_row(it))
        actus_list_view.controls = controls or [ft.Container(
            ft.Text("Rien à afficher.", color=LIGHT_GREY),
            padding=20)]
        for chip in actus_chips.controls:
            chip.data["paint"]()
        page.update()

    def _actus_chip(label, value, color):
        text = ft.Text(label, size=CONSTANTS.TEXT_SM,
                       weight=ft.FontWeight.W_500)
        chip = ft.Container(text, padding=ft.Padding(12, 6, 12, 6),
                            border_radius=16, ink=True)

        def _paint():
            on = (actus_state["unread_only"] if value == "unread"
                  else actus_state["filter"] == value)
            chip.bgcolor = color if on else GREY
            text.color = DARK if on else WHITE

        def _click(e):
            if value == "unread":
                actus_state["unread_only"] = not actus_state["unread_only"]
            else:
                actus_state["filter"] = value
            _actus_render()

        chip.on_click = _click
        chip.data = {"paint": _paint}
        _paint()
        return chip

    actus_chips = ft.Row(
        [_actus_chip("Tout", None, WHITE)]
        + [_actus_chip(c, c, ACTUS_CAT_COLORS[c])
           for c in rss_feeds.CATEGORIES]
        + [_actus_chip("Non lus", "unread", RED)],
        spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def _actus_refresh(event=None):
        if actus_state["loading"]:
            return
        actus_state["loading"] = True
        actus_status.value = "Chargement…"
        page.update()

        def _work():
            try:
                items = rss_feeds.fetch_all_feeds()
                error = None
            except Exception as exc:
                items, error = [], str(exc)

            async def _apply():
                actus_state["loading"] = False
                if error:
                    actus_status.value = f"Erreur : {error}"
                else:
                    # Garde les textes complets déjà chargés.
                    full = {it["link"]: it["full"]
                            for it in actus_state["items"] if "full" in it}
                    for it in items:
                        if it["link"] in full:
                            it["full"] = full[it["link"]]
                    actus_state["items"] = items
                    _actus_save_cache()
                    actus_status.value = (
                        f"{datetime.datetime.now().strftime('%H:%M')}")
                    if items and actus_state["selected"] is None:
                        _actus_show(items[0])
                        return
                _actus_render()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    actus_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                _surface_title("Actus", "actus"),
                actus_chips,
                actus_status,
                ft.IconButton(ft.Icons.REFRESH, **SQUARE_BTN,
                             icon_color=SURFACE_ACCENT["actus"],
                             icon_size=CONSTANTS.ICON_SM,
                             tooltip="Actualiser les flux",
                             on_click=_actus_refresh),
            ], spacing=12),
            height=TOOLBAR_H, padding=ft.Padding(12, 0, 12, 0),
            alignment=ft.Alignment(-1, 0), bgcolor=BACKGROUND),
        ft.Divider(height=1, color=GREY),
        ft.Row([
            ft.Container(content=actus_list_view, expand=2),
            ft.VerticalDivider(width=1, color=GREY),
            ft.Container(content=actus_reader, expand=3,
                         padding=ft.Padding(24, 16, 24, 16)),
        ], expand=True, spacing=0,
           vertical_alignment=ft.CrossAxisAlignment.STRETCH),
    ], expand=True, spacing=0)

    return {
        "_actus_refresh": _actus_refresh,
        "_actus_show": _actus_show,
        "actus_state": actus_state,
        "actus_surface": actus_surface,
    }
