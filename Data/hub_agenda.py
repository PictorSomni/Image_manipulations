# -*- coding: utf-8 -*-
"""Hub — surface Agenda (rendez-vous Notion Studio/Reportage/Location).

Section extraite de Hub.pyw (main) : build(ui) reçoit l'espace de
noms de main (ui) et renvoie les noms utilisés ailleurs dans Hub."""


import CONSTANTS
import asyncio
import datetime
import flet as ft
import json
import hub_sync
import notion_rest
import threading


def build(ui):
    BACKGROUND = ui.BACKGROUND
    BLUE = ui.BLUE
    DARK = ui.DARK
    GREEN = ui.GREEN
    GREY = ui.GREY
    KANBAN_ETAT_COLORS = ui.KANBAN_ETAT_COLORS
    LIGHT_GREY = ui.LIGHT_GREY
    MINT = ui.MINT
    ORANGE = ui.ORANGE
    PINK = ui.PINK
    RED = ui.RED
    SQUARE_BTN = ui.SQUARE_BTN
    SURFACE_ACCENT = ui.SURFACE_ACCENT
    TOOLBAR_H = ui.TOOLBAR_H
    VIOLET = ui.VIOLET
    WHITE = ui.WHITE
    YELLOW = ui.YELLOW
    _AGENDA_CACHE_FILE = ui._AGENDA_CACHE_FILE
    _dialog = ui._dialog
    _dlg_btn = ui._dlg_btn
    _kanban_busy = ui._kanban_busy
    _kanban_change_property = ui._kanban_change_property
    _kanban_deadline_field = ui._kanban_deadline_field
    _kanban_extract_page_content = ui._kanban_extract_page_content
    _kanban_new_task = ui._kanban_new_task
    _kanban_notion_to_plain = ui._kanban_notion_to_plain
    _kanban_open_details = ui._kanban_open_details
    _kanban_plain_to_notion = ui._kanban_plain_to_notion
    _kanban_refresh = ui._kanban_refresh
    _load_json = ui._load_json
    # Agenda stocké sur le Pi (hub-sync), Notion en miroir.
    _notion_call = (hub_sync.tasks_call if hub_sync.available()
                    else ui._notion_call)
    _run_task = ui._run_task
    _save_json = ui._save_json
    _surface_title = ui._surface_title
    _sync_label = ui._sync_label
    agenda_sync_veil = ui.agenda_sync_veil
    kanban_state = ui.kanban_state
    page = ui.page
    # ═════════════════════════════════════════════════════════════════════
    #  Surface Agenda — les 3 bases Notion à date de rendez-vous réunies en
    #  une liste chronologique (retour user). Lecture seule : un clic ouvre
    #  la fiche dans Notion pour la modifier.
    # ═════════════════════════════════════════════════════════════════════
    AGENDA_SOURCES = [
        # nom, data source, couleur, nom de la propriété e-mail
        ("Studio", "ae971f83-22d1-4d53-8972-4c6302c6d371", BLUE, "E-mail"),
        ("Reportage", "42f7bb5c-84f2-416a-aad0-8aad7b1ea51a", VIOLET,
         "E-mail"),
        ("Locations", "23f887c8-202a-4e37-91e1-812a4a6c7472", GREEN, "Email"),
    ]
    AGENDA_MONTHS = ("janvier février mars avril mai juin juillet août "
                     "septembre octobre novembre décembre").split()
    AGENDA_MAX_CHIPS = 3
    agenda_status = ft.Text("", size=11, color=LIGHT_GREY)
    agenda_month_label = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE,
                                 weight=ft.FontWeight.W_600, width=160,
                                 text_align=ft.TextAlign.CENTER)
    agenda_grid = ft.Column(expand=True, spacing=0)
    # Couleurs Notion -> palette Hub (options des select/multi_select).
    NOTION_COLORS = {"gray": GREY, "default": GREY, "purple": VIOLET,
                     "blue": BLUE, "green": GREEN, "red": RED,
                     "yellow": YELLOW, "orange": ORANGE, "brown": ORANGE,
                     "pink": PINK}
    AGENDA_BASE_PROPS = {"Nom", "Date", "Téléphone", "E-mail", "Email"}
    agenda_schemas = {}  # source -> notion_rest.schema()
    # Valeurs par défaut à la création (retour user).
    AGENDA_DEFAULTS = {"Studio": {"État": "Réservé"},
                       "Reportage": {"État": "Réservé"},
                       "Locations": {"Etat": "Pas d'accompte"}}
    # Ordre d'affichage imposé (l'API rend les status par groupe Notion).
    AGENDA_ORDER = ["Réservé", "En cours", "Terminé", "Prêt"]
    AGENDA_DONE = {"Terminé", "Prêt"}
    # Repli si le schéma Notion n'est pas dispo (pas de ~/.notion sur la
    # machine -> connexion MCP, sans options) : couleurs connues en dur.
    AGENDA_ETAT_COLORS = {"Réservé": BLUE, "En cours": VIOLET,
                          "Terminé": GREEN, "Prêt": GREEN,
                          "Pas d'accompte": RED,
                          "Réservé (accompte recu)": YELLOW, "Payé": GREEN}
    agenda_state = {"loading": False, "events": [],
                    "month": datetime.date.today().replace(day=1)}

    def _agenda_chip(ev, expand=False):
        # Carte façon Notion : fond teinté de la couleur de la base, nom en
        # gras, heure + téléphone en dessous (retour user, capture Notion).
        start = ev["start"]
        sub = []
        if len(start) > 10:
            try:
                sub.append(datetime.datetime.fromisoformat(
                    start).astimezone().strftime("%H:%M"))
            except ValueError:
                pass
        if ev["tel"]:
            sub.append(ev["tel"])
        etat = ev["row"].get("État") or ev["row"].get("Etat") or ""
        # Objets / châteaux loués (propriétés multi-sélection).
        loue = ", ".join(n for v in ev["row"].values()
                         if isinstance(v, list) for n in v)
        etat_color = next(
            (NOTION_COLORS.get(c, GREY)
             for info in agenda_schemas.get(ev["source"], {}).values()
             for n, c in info["options"] if n == etat),
            AGENDA_ETAT_COLORS.get(etat, KANBAN_ETAT_COLORS.get(etat, GREY)))
        return ft.Container(
            content=ft.Column([
                ft.Text(ev["nom"] or "(sans nom)", size=12, color=WHITE,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                        weight=ft.FontWeight.W_600),
                ft.Container(
                    content=ft.Text(etat, size=10, color=DARK,
                                    weight=ft.FontWeight.W_600,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                    bgcolor=ft.Colors.with_opacity(0.85, etat_color),
                    border_radius=4, padding=ft.Padding(5, 1, 5, 1),
                    visible=bool(etat)),
                ft.Text(loue, size=11, color=WHITE, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        visible=bool(loue)),
                ft.Text(" · ".join(sub), size=11, color=LIGHT_GREY,
                        visible=bool(sub), max_lines=1),
            ], spacing=2, tight=True),
            bgcolor=ft.Colors.with_opacity(0.22, ev["color"]),
            border=ft.Border(left=ft.BorderSide(3, ev["color"])),
            border_radius=6, padding=ft.Padding(8, 6, 8, 6), ink=True,
            tooltip=ev["source"], expand=expand,
            # Vue d'ensemble (retour user) : terminé = estompé,
            # ce qui reste à faire ressort.
            # Passés NON estompés : retouchés après coup (retour user).
            opacity=0.4 if etat in AGENDA_DONE else 1,
            on_click=lambda e, ev=ev: _agenda_open(ev))

    def _agenda_open(ev):
        # Tâche (deadline) -> sa fiche Tâches ; sinon fiche rendez-vous.
        if ev.get("task"):
            _kanban_open_details(ev["task"])
        else:
            _agenda_new_entry(ev=ev)

    def _agenda_task_events():
        # 4e calendrier (retour user) : tâches du Kanban ayant une
        # deadline, lues dans le cache Tâches (pas d'appel Notion).
        return [{"source": "Tâches", "nom": r["demande"],
                 "start": r["deadline"], "tel": r.get("telephone", ""),
                 "color": ORANGE,
                 "row": {"État": r["etat"]}, "task": r}
                for r in kanban_state["rows"] if r.get("deadline")]

    def _agenda_day_list(day, evs):
        """Tous les rendez-vous d'un jour (clic sur "+n")."""
        def _open(ev):
            dlg.open = False
            _agenda_open(ev)
        dlg = _dialog(
            title=ft.Text(day.strftime("%d/%m/%Y"), size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Column(
                [ft.Container(_agenda_chip(ev), on_click=lambda e, ev=ev:
                              _open(ev)) for ev in evs],
                tight=True, spacing=6, width=420,
                scroll=ft.ScrollMode.AUTO),
            actions=[_dlg_btn("Nouveau", "primary", on_click=lambda e: (
                         setattr(dlg, "open", False),
                         _agenda_new_entry(day))),
                     _dlg_btn("Fermer", "cancel", on_click=lambda e: (
                         setattr(dlg, "open", False), page.update()))])
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    agenda_drag = []  # événements glissables de la grille affichée

    def _agenda_hover(cell, on):
        if on:
            cell.data = cell.bgcolor
            cell.bgcolor = ft.Colors.with_opacity(0.18, SURFACE_ACCENT.get(
                "agenda", BLUE))
        else:
            cell.bgcolor = cell.data if cell.data is not None else None
        cell.update()

    def _agenda_move(e, day):
        if e.src is None or not 0 <= e.src.data < len(agenda_drag):
            return
        ev = agenda_drag[e.src.data]
        new_start = day.isoformat() + ev["start"][10:]
        if new_start == ev["start"]:
            return
        if ev.get("task"):
            _kanban_change_property(ev["task"], "Deadline", "deadline",
                                    new_start)
            _agenda_rebuild()
            page.update()
            return
        old_start = ev["start"]
        ev["start"] = new_start
        _save_json(_AGENDA_CACHE_FILE, {"events": agenda_state["events"],
                                        "schemas": agenda_schemas})
        _agenda_rebuild()
        agenda_status.value = "Enregistrement…"
        _kanban_busy(1)
        page.update()

        def _work():
            result = _notion_call(
                "mcp__notion__notion-update-page",
                {"page_id": ev["page_id"], "command": "update_properties",
                 "properties": {"Date": new_start}})

            async def _apply():
                _kanban_busy(-1)
                if result.startswith("Erreur"):
                    ev["start"] = old_start
                    _save_json(_AGENDA_CACHE_FILE,
                               {"events": agenda_state["events"],
                                "schemas": agenda_schemas})
                    _agenda_rebuild()
                    agenda_status.value = f"Échec : {result}"
                else:
                    agenda_status.value = "Enregistré."
                page.update()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _agenda_rebuild():
        agenda_drag.clear()
        first = agenda_state["month"]
        agenda_month_label.value = (f"{AGENDA_MONTHS[first.month - 1]} "
                                    f"{first.year}").capitalize()
        by_day = {}
        for ev in agenda_state["events"] + _agenda_task_events():
            by_day.setdefault(ev["start"][:10], []).append(ev)
        today = datetime.date.today()
        day = first - datetime.timedelta(days=first.weekday())
        line = ft.BorderSide(1, ft.Colors.with_opacity(0.12, WHITE))
        rows = [ft.Row([
            ft.Container(ft.Text(d, size=11, color=LIGHT_GREY),
                         expand=True, alignment=ft.Alignment.CENTER,
                         padding=ft.Padding(0, 4, 0, 4))
            for d in "lun. mar. mer. jeu. ven. sam. dim.".split()],
            spacing=0)]
        # 6 semaines max, on s'arrête après la dernière semaine du mois.
        while day.month == first.month or day < first:
            cells = []
            for _ in range(7):
                # Rendez-vous d'abord, tâches ensuite (retour user) : les
                # tâches ne masquent jamais un rendez-vous derrière le "+n".
                evs = sorted(by_day.get(day.isoformat(), []),
                             key=lambda e: (bool(e.get("task")), e["start"]))
                in_month = day.month == first.month
                # Cartes adaptatives (retour user) : elles se partagent la
                # hauteur de la case (1 = pleine, 2 = moitié, 3 = tiers),
                # au-delà un bouton "+n" ouvre la liste du jour.
                # Glisser une carte sur un autre jour change sa date
                # (retour user) ; l'heure éventuelle est conservée.
                chips = []
                for e in evs[:AGENDA_MAX_CHIPS]:
                    agenda_drag.append(e)
                    chip = _agenda_chip(e, expand=True)
                    # Draggable n'a pas d'expand : le Container le porte.
                    chips.append(ft.Container(ft.Draggable(
                        group="agenda_ev", data=len(agenda_drag) - 1,
                        content=chip,
                        content_feedback=ft.Container(
                            _agenda_chip(e), width=160, opacity=0.85)),
                        expand=True))
                if len(evs) > AGENDA_MAX_CHIPS:
                    chips.append(ft.Container(
                        ft.Text(f"+{len(evs) - AGENDA_MAX_CHIPS}", size=11,
                                color=WHITE, weight=ft.FontWeight.W_600),
                        bgcolor=ft.Colors.with_opacity(0.12, WHITE),
                        border_radius=4, padding=ft.Padding(6, 2, 6, 2),
                        alignment=ft.Alignment.CENTER, ink=True,
                        on_click=lambda e, d=day, v=evs:
                            _agenda_day_list(d, v)))
                label = (str(day.day) if day.day != 1 or in_month
                         else f"1 {AGENDA_MONTHS[day.month - 1][:3]}.")
                num = ft.Text(label, size=12,
                              color=(ft.Colors.BLACK if day == today
                                     else WHITE if in_month
                                     else LIGHT_GREY),
                              weight=ft.FontWeight.W_600)
                if day == today:
                    num = ft.Container(num, bgcolor=RED, width=26,
                                       height=26, border_radius=13,
                                       alignment=ft.Alignment.CENTER)
                cell = ft.Container(
                    content=ft.Column([
                        ft.Row([num], alignment=ft.MainAxisAlignment.END),
                        *chips], spacing=4, expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    expand=True, padding=6,
                    # Sans teinte en semaine, légère teinte le weekend.
                    bgcolor=(ft.Colors.with_opacity(0.06, WHITE)
                             if day.weekday() >= 5 else None),
                    # Aujourd'hui : case entière cerclée de rouge.
                    border=(ft.Border.all(2, RED) if day == today
                            else ft.Border(right=line, bottom=line)),
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    ink=True,
                    on_click=lambda e, d=day: _agenda_new_entry(d))
                # DragTarget sans flex réel dans une Row : c'est le
                # Container expand qui partage la largeur (sinon grille vide).
                cells.append(ft.Container(ft.DragTarget(
                    group="agenda_ev", content=cell,
                    on_will_accept=lambda e, c=cell: _agenda_hover(c, True),
                    on_leave=lambda e, c=cell: _agenda_hover(c, False),
                    on_accept=lambda e, c=cell, d=day: (
                        _agenda_hover(c, False), _agenda_move(e, d))),
                    expand=True))
                day += datetime.timedelta(days=1)
            rows.append(ft.Row(cells, expand=True, spacing=0,
                               vertical_alignment=(
                                   ft.CrossAxisAlignment.STRETCH)))
        agenda_grid.controls = rows

    def _agenda_shift(months):
        m = agenda_state["month"]
        if months == 0:
            agenda_state["month"] = datetime.date.today().replace(day=1)
        else:
            y, mo = divmod(m.month - 1 + months, 12)
            agenda_state["month"] = m.replace(year=m.year + y, month=mo + 1)
        _agenda_rebuild()
        page.update()

    def _agenda_refresh(event=None):
        if agenda_state["loading"]:
            return
        agenda_state["loading"] = True
        _kanban_busy(1)
        agenda_status.value = "Chargement…"
        page.update()

        def _work():
            events, errors = [], []
            for name, ds_id, color, mail_prop in AGENDA_SOURCES:
                raw = _notion_call(
                    "mcp__notion__notion-query-data-sources",
                    {"data": {"mode": "rows",
                              "data_source_url": f"collection://{ds_id}",
                              "limit": 100}})
                if raw.startswith("Erreur"):
                    errors.append(f"{name} : {raw}")
                    continue
                for r in json.loads(raw).get("results", []):
                    start = r.get("date:Date:start") or ""
                    if start:
                        events.append({
                            "source": name, "color": color, "start": start,
                            "url": r.get("url", ""),
                            "row": r,
                            "page_id": r.get("url", "").rsplit("/", 1)[-1],
                            "tel": r.get("Téléphone") or "",
                            "mail": r.get(mail_prop) or "",
                            "nom": " ".join((r.get("Nom") or "").split())})

            # Schémas relus à chaque actualisation : options modifiées
            # dans Notion prises en compte sans relancer le Hub.
            for name, ds_id, _c, _m in AGENDA_SOURCES:
                try:
                    if hub_sync.available():
                        raw = hub_sync.tasks_call(
                            "schema", {"data_source_id": ds_id})
                        if not raw.startswith("Erreur"):
                            agenda_schemas[name] = json.loads(raw)
                    elif notion_rest.TOKEN:
                        agenda_schemas[name] = notion_rest.schema(ds_id)
                except Exception:
                    pass  # options indisponibles : champs de base

            async def _apply():
                agenda_state["loading"] = False
                _kanban_busy(-1)
                agenda_state["events"] = events
                if not errors:
                    _save_json(_AGENDA_CACHE_FILE,
                               {"events": events, "schemas": agenda_schemas})
                agenda_status.value = (
                    " / ".join(errors) if errors else _sync_label())
                _agenda_rebuild()
                page.update()

            _run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    def _agenda_new_entry(day=None, ev=None):
        """Création (ev None) ou fiche d'un rendez-vous existant."""
        def _field(label, value=""):
            return ft.TextField(label=label, value=value, width=560,
                                bgcolor=DARK,
                                border=CONSTANTS.input_border(GREY),
                                color=WHITE)
        heure = ""
        if ev and len(ev["start"]) > 10:
            try:
                heure = datetime.datetime.fromisoformat(
                    ev["start"]).astimezone().strftime("%H:%M")
            except ValueError:
                pass
        nom_field = _field("Nom", ev["nom"] if ev else "")
        date_field = _kanban_deadline_field(
            ev["start"][:10] if ev
            else (day or datetime.date.today()).isoformat(), label="Date")
        # TimePicker plutôt que saisie libre (retour user) : l'heure est
        # toujours au format HH:MM, rien d'invalide n'arrive à Notion.
        heure_field = _field("Heure (vide = journée)", heure)
        heure_field.read_only = True

        def _time_picked(e):
            v = e.control.value
            if v is None:
                return
            if isinstance(v, str):
                v = datetime.time.fromisoformat(v[:5])
            heure_field.value = v.strftime("%H:%M")
            heure_field.update()

        def _time_open(e):
            try:
                cur = datetime.time.fromisoformat(heure_field.value)
            except ValueError:
                cur = datetime.time(10, 0)
            page.show_dialog(ft.TimePicker(
                value=cur, hour_format=ft.TimePickerHourFormat.H24,
                on_change=_time_picked))

        def _time_clear(e):
            heure_field.value = ""
            heure_field.update()

        heure_field.on_click = _time_open
        heure_field.suffix = ft.Row([
            ft.IconButton(ft.Icons.SCHEDULE, on_click=_time_open,
                          icon_color=SURFACE_ACCENT["agenda"]),
            ft.IconButton(ft.Icons.CLOSE, on_click=_time_clear,
                          icon_color=LIGHT_GREY),
        ], tight=True, spacing=0)
        tel_field = _field("Téléphone", ev["tel"] if ev else "")
        mail_field = _field("E-mail", ev["mail"] if ev else "")
        texts = [ft.Text(n, size=11) for n, *_ in AGENDA_SOURCES]
        # "Options" propres à chaque base (État, objets, remarques…),
        # construites depuis le schéma Notion : getters prop -> valeur.
        extras_col = ft.Column(spacing=8, tight=True)
        extras = {}
        row_vals = ev["row"] if ev else {}

        def _option_seg(options, current, allow_empty):
            options = sorted(options, key=lambda o: (
                AGENDA_ORDER.index(o[0]) if o[0] in AGENDA_ORDER
                else len(AGENDA_ORDER)))
            names = (["—"] if allow_empty else []) + [n for n, _ in options]
            colors = {n: NOTION_COLORS.get(c, GREY) for n, c in options}
            seg_texts = [ft.Text(n, size=11) for n in names]

            def _style():
                for k, t in enumerate(seg_texts):
                    t.color = DARK if k == sg.selected_index else WHITE
                sg.thumb_color = colors.get(names[sg.selected_index], GREY)

            def _chg(e):
                _style()
                sg.update()

            sg = ft.CupertinoSlidingSegmentedButton(
                selected_index=(names.index(current) if current in names
                                else 0),
                controls=seg_texts, on_change=_chg, width=560)
            _style()
            return sg, lambda: ("" if names[sg.selected_index] == "—"
                                else names[sg.selected_index])

        def _multi_chips(options, current):
            chosen = set(current or [])
            chips = []

            def _chip(name, color):
                c = ft.Container(
                    content=ft.Text(name, size=11),
                    border_radius=12, padding=ft.Padding(8, 4, 8, 4),
                    ink=True)

                def _style():
                    on = name in chosen
                    c.bgcolor = (ft.Colors.with_opacity(0.85, color) if on
                                 else DARK)
                    c.content.color = DARK if on else WHITE
                    c.border = ft.Border.all(1, color)

                def _toggle(e):
                    chosen.symmetric_difference_update({name})
                    _style()
                    c.update()
                c.on_click = _toggle
                _style()
                return c
            chips = [_chip(n, NOTION_COLORS.get(col, GREY))
                     for n, col in options]
            return (ft.Row(chips, wrap=True, spacing=6, run_spacing=6,
                           width=560),
                    lambda: [n for n, _ in options if n in chosen])

        def _build_extras(source_name):
            extras.clear()
            rows = []
            for prop, info in agenda_schemas.get(source_name, {}).items():
                if prop in AGENDA_BASE_PROPS:
                    continue
                t = info["type"]
                cur = (row_vals.get(prop) if ev else
                       AGENDA_DEFAULTS.get(source_name, {}).get(prop))
                if t in ("status", "select") and info["options"]:
                    # Plus d'état vide (retour user) : toujours une option.
                    ctrl, get = _option_seg(info["options"], cur,
                                            allow_empty=False)
                elif t == "multi_select":
                    ctrl, get = _multi_chips(info["options"], cur)
                elif t in ("rich_text", "number"):
                    ctrl = _field(prop, "" if cur in (None, "")
                                  else f"{cur:g}" if t == "number"
                                  else str(cur))
                    get = (lambda c=ctrl: (c.value or "").strip())
                    rows.append(ctrl)
                    extras[prop] = get
                    continue
                else:
                    continue
                rows += [ft.Text(prop, size=11, color=LIGHT_GREY), ctrl]
                extras[prop] = get
            extras_col.controls = rows

        notes_field = ft.TextField(
            label="Notes", multiline=True, min_lines=4, width=560,
            bgcolor=DARK, border=CONSTANTS.input_border(GREY), color=WHITE,
            value="Chargement…" if ev else "", disabled=bool(ev))
        notes_orig = {"value": ""}

        def _restyle():
            for k, t in enumerate(texts):
                t.color = DARK if k == seg.selected_index else WHITE
            seg.thumb_color = AGENDA_SOURCES[seg.selected_index][2]

        def _seg_change(e):
            _restyle()
            _build_extras(AGENDA_SOURCES[seg.selected_index][0])
            page.update()

        seg = ft.CupertinoSlidingSegmentedButton(
            selected_index=next(
                (i for i, src in enumerate(AGENDA_SOURCES)
                 if ev and src[0] == ev["source"]), 0),
            controls=texts, on_change=_seg_change, width=560,
            # Une fiche existante ne change pas de base Notion.
            disabled=ev is not None)
        _restyle()

        def _close(e=None):
            dlg.open = False
            page.update()

        def _confirm(e):
            nom = (nom_field.value or "").strip()
            date_txt = (date_field.value or "").strip()
            if not nom or not date_txt:
                return
            heure = (heure_field.value or "").strip().replace("h", ":")
            start = date_txt
            if heure:
                try:
                    hh, _, mm = heure.partition(":")
                    start = datetime.datetime.combine(
                        datetime.date.fromisoformat(date_txt),
                        datetime.time(int(hh), int(mm or 0))
                    ).astimezone().isoformat(timespec="minutes")
                except ValueError:
                    heure_field.error_text = "Format HH:MM"
                    heure_field.update()
                    return
            name, ds_id, _color, mail_prop = AGENDA_SOURCES[
                seg.selected_index]
            props = {"Nom": nom, "Date": start,
                     "Téléphone": (tel_field.value or "").strip(),
                     mail_prop: (mail_field.value or "").strip()}
            for prop, get in extras.items():
                v = get()
                if prop in row_vals or v:
                    props[prop] = v
            if not ev:  # création : pas de propriétés vides
                props = {k: v for k, v in props.items() if v}
            notes = (notes_field.value or "").strip()
            notes_changed = (not notes_field.disabled
                             and notes != notes_orig["value"])
            _close()
            agenda_status.value = "Enregistrement…"
            page.update()

            def _work():
                if ev:
                    result = _notion_call(
                        "mcp__notion__notion-update-page",
                        {"page_id": ev["page_id"],
                         "command": "update_properties",
                         "properties": props})
                    if notes_changed and not result.startswith("Erreur"):
                        result = _notion_call(
                            "mcp__notion__notion-update-page",
                            {"page_id": ev["page_id"],
                             "command": "replace_content",
                             "new_str": _kanban_plain_to_notion(notes)})
                else:
                    page_data = {"properties": props}
                    if notes:
                        page_data["content"] = _kanban_plain_to_notion(notes)
                    result = _notion_call(
                        "mcp__notion__notion-create-pages",
                        {"parent": {"type": "data_source_id",
                                    "data_source_id": ds_id},
                         "pages": [page_data]})

                async def _apply():
                    if result.startswith("Erreur"):
                        agenda_status.value = f"Échec ({name}) : {result}"
                        page.update()
                    else:
                        _agenda_refresh()

                _run_task(_apply)

            threading.Thread(target=_work, daemon=True).start()

        def _delete(e):
            # Corbeille Notion (récupérable 30 jours), comme les tâches.
            _close()
            agenda_state["events"].remove(ev)
            _save_json(_AGENDA_CACHE_FILE, {"events": agenda_state["events"],
                                            "schemas": agenda_schemas})
            _agenda_rebuild()
            page.update()

            def _work():
                result = _notion_call("mcp__notion__notion-trash-page",
                                      {"page_id": ev["page_id"]})

                async def _apply():
                    if result.startswith("Erreur"):
                        agenda_state["events"].append(ev)
                        _agenda_rebuild()
                        agenda_status.value = f"Échec suppression : {result}"
                        page.update()

                _run_task(_apply)

            threading.Thread(target=_work, daemon=True).start()

        # Boutons à fond coloré, plus lisibles (retour user).
        actions = [_dlg_btn("Annuler", "cancel", on_click=_close),
                   _dlg_btn("Enregistrer" if ev else "Créer",
                            on_click=_confirm)]
        def _to_task(e):
            _close()
            _kanban_new_task(prefill={
                "demande": f"{ev['source']} {(nom_field.value or '').strip()}",
                "prevenir": "Appeler quand prêt",
                "notes": ("" if notes_field.disabled
                          else (notes_field.value or "").strip()),
                "telephone": (tel_field.value or "").strip(),
                "email": (mail_field.value or "").strip()})

        if ev and ev["source"] in ("Studio", "Reportage"):
            actions.insert(0, _dlg_btn("Créer une tâche", color=MINT,
                                       on_click=_to_task))
        if ev:
            actions.insert(0, _dlg_btn("Supprimer", "danger",
                                       on_click=_delete))
        dlg = _dialog(
            title=ft.Text("Rendez-vous" if ev else "Nouveau rendez-vous",
                          size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Container(height=10), seg, nom_field, date_field,
                heure_field, tel_field, mail_field, extras_col,
                ft.Divider(height=1, color=GREY), notes_field,
            ], tight=True, spacing=8, width=600, scroll=ft.ScrollMode.AUTO,
               height=max(300, min(680, (page.height or 900) - 220))),
            actions=actions,
            inset_padding=ft.Padding(20, 40, 20, 40))
        _build_extras(AGENDA_SOURCES[seg.selected_index][0])
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        def _load_notes():
            raw = _notion_call("mcp__notion__notion-fetch",
                               {"id": ev["page_id"]})
            failed = raw.startswith("Erreur")
            body = "" if failed else _kanban_extract_page_content(raw)

            async def _apply():
                if failed:
                    notes_field.value = f"(notes indisponibles : {raw})"
                else:
                    plain = _kanban_notion_to_plain(body or "").strip()
                    notes_orig["value"] = plain
                    notes_field.value = plain
                    notes_field.disabled = False
                page.update()

            _run_task(_apply)

        if ev:
            threading.Thread(target=_load_notes, daemon=True).start()

    def _agenda_btn(icon, tip, fn):
        return ft.IconButton(icon, icon_color=SURFACE_ACCENT["agenda"],
                             icon_size=CONSTANTS.ICON_SM, tooltip=tip,
                             on_click=fn, **SQUARE_BTN)

    agenda_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                _surface_title("Agenda", "agenda"),
                _agenda_btn(ft.Icons.CHEVRON_LEFT, "Mois précédent",
                            lambda e: _agenda_shift(-1)),
                agenda_month_label,
                _agenda_btn(ft.Icons.CHEVRON_RIGHT, "Mois suivant",
                            lambda e: _agenda_shift(1)),
                _agenda_btn(ft.Icons.TODAY, "Aujourd'hui",
                            lambda e: _agenda_shift(0)),
                ft.Container(expand=True),
                *[ft.Container(
                    content=ft.Text(n, size=11, color=ft.Colors.BLACK,
                                    weight=ft.FontWeight.W_600),
                    bgcolor=ft.Colors.with_opacity(0.85, c),
                    border_radius=4, padding=ft.Padding(6, 2, 6, 2))
                  for n, c in [(n, c) for n, _d, c, _m in AGENDA_SOURCES]
                  + [("Tâches", ORANGE)]],
                agenda_status,
                _agenda_btn(ft.Icons.ADD, "Nouveau rendez-vous",
                            lambda e: _agenda_new_entry()),
                _agenda_btn(ft.Icons.REFRESH, "Actualiser",
                            _agenda_refresh),
            ], spacing=8),
            height=TOOLBAR_H, padding=ft.Padding(12, 0, 12, 0),
            alignment=ft.Alignment(-1, 0), bgcolor=BACKGROUND),
        ft.Divider(height=1, color=GREY),
        # Grille positionnée (bords à 0) : sinon le Stack lui donne des
        # contraintes lâches et le calendrier disparaît (retour user).
        ft.Stack([ft.Container(content=agenda_grid,
                               left=0, top=0, right=0, bottom=0,
                               padding=ft.Padding(24, 6, 24, 12)),
                  agenda_sync_veil], expand=True),
    ], expand=True, spacing=0)
    # Cache local comme les Tâches (retour user) : affiché tel quel, pas
    # d'appel Notion tant qu'on ne modifie rien ou ne clique pas sur ⟳.
    _agenda_cache = _load_json(_AGENDA_CACHE_FILE, {})
    if isinstance(_agenda_cache, dict) and _agenda_cache.get("events"):
        agenda_state["events"] = _agenda_cache["events"]
        agenda_schemas.update(_agenda_cache.get("schemas") or {})
        agenda_status.value = _sync_label(_AGENDA_CACHE_FILE)
    _agenda_rebuild()

    async def _hourly_sync():
        # Tâches toutes les heures, Agenda une fois par jour (retour user),
        # en plus du cache et du bouton Actualiser.
        hours = 0
        while True:
            await asyncio.sleep(3600)
            hours += 1
            _kanban_refresh()
            if hours % 24 == 0:
                _agenda_refresh()


    # Sans clé Notion, la synchro passerait par MCP et ouvrirait le
    # navigateur toutes les heures sur les machines non connectées
    # volontairement (retour user).
    async def _startup_sync():
        # Tâches + Agenda à jour dès le démarrage (retour user), après
        # l'affichage du cache.
        await asyncio.sleep(2)
        _kanban_refresh()
        _agenda_refresh()

    if notion_rest.TOKEN or hub_sync.available():
        _run_task(_startup_sync)
        _run_task(_hourly_sync)

    return {
        "_agenda_rebuild": _agenda_rebuild,
        "_agenda_refresh": _agenda_refresh,
        "agenda_state": agenda_state,
        "agenda_surface": agenda_surface,
    }
