# -*- coding: utf-8 -*-
"""
Hub mobile : Tâches + Agenda pour iPhone / iPad, en web app servie par le
Pi (Tailscale, http://pictorsomni:8550 → « Ajouter à l'écran d'accueil »).

Mêmes données que Hub : Notion (Data/notion_rest.py) pour les cartes et
l'agenda, ordre manuel des cartes partagé via le Pi (hub_sync
"kanban_ordre"). Rien n'est dupliqué : Hub reste l'outil complet.
"""

__version__ = "2.10.1"

import datetime
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "Data"))
import flet as ft  # noqa: E402
import hub_sync  # noqa: E402
import notion_rest  # noqa: E402

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
    state = {"etat": "À faire", "tasks": [], "tab": 0}

    status = ft.Text("", size=12, color=GREY)
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

    def _task_card(row):
        deadline = row.get("date:Deadline:start") or ""
        sub = []
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

    def _etat_chips():
        def _pick(e):
            state["etat"] = e.control.data
            render()
        counts = {}
        for r in state["tasks"]:
            k = r.get("Etat") or "À faire"
            counts[k] = counts.get(k, 0) + 1
        return ft.Row([ft.Chip(
            label=ft.Text(f"{e} ({counts.get(e, 0)})"), data=e,
            selected=state["etat"] == e, selected_color=c + "55",
            on_select=_pick) for e, c in ETATS],
            scroll=ft.ScrollMode.AUTO, spacing=6)

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

    # ── Rendu / chargement ───────────────────────────────────────────
    def render():
        body.controls.clear()
        if state["tab"] == 0:
            body.controls.append(_etat_chips())
            rows = [r for r in state["tasks"]
                    if (r.get("Etat") or "À faire") == state["etat"]]
            body.controls += [_task_card(r) for r in rows] or [
                ft.Text("Rien ici", color=GREY)]
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
                                        label="Agenda")],
        on_change=_tab, bgcolor=CARD)
    page.add(ft.SafeArea(body, expand=True))
    refresh()


if __name__ == "__main__":
    ft.run(main, view=ft.AppView.WEB_BROWSER, host="0.0.0.0",
           port=int(os.environ.get("HUB_MOBILE_PORT", 8550)))
