"""Hub : briefing du matin, réponses aux mails et « commande prête ».

Tout passe par le Pi (hub_sync.mail → Data/mail_reply.py) ; rien n'est
envoyé sans clic sur « Envoyer ».
"""
import base64
import datetime
import os
import re
import tempfile
import threading
import webbrowser

import flet as ft

import CONSTANTS
import hub_sync
import ui_helpers

# Le message de Charles, mot pour mot (+ le prix s'il est connu).
READY = ("Bonjour,\n\nVotre commande est prête, vous pouvez venir la "
         "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")
READY_TU = ("Bonjour,\n\nTa commande est prête, tu peux venir la "
            "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")
TONES = [("professionnel et chaleureux", "Chaleureux"),
         ("professionnel et sobre", "Sobre"), ("très bref", "Bref")]


def build(ui):
    page = ui.page
    DARK, WHITE, GREY = ui.DARK, ui.WHITE, ui.GREY
    LIGHT_GREY, RED, BLUE = ui.LIGHT_GREY, ui.RED, ui.BLUE
    YELLOW = CONSTANTS.COLOR_YELLOW
    _dialog, _dlg_btn, _run_task = ui._dialog, ui._dlg_btn, ui._run_task
    # Rempli par Hub une fois l'onglet Fichiers prêt (open_folder).
    hooks = {}

    def _bg(work, done):
        """work() dans un fil, puis done(résultat ou exception) dans l'UI."""
        def _run():
            try:
                out = work()
            except Exception as exc:  # Pi injoignable, envoi refusé…
                out = exc

            async def _apply():
                done(out)
                page.update()
            _run_task(_apply)
        threading.Thread(target=_run, daemon=True).start()

    def _show(dlg):
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _close(dlg):
        dlg.open = False
        page.update()

    def _seg(options, on_pick):
        texts = [ft.Text(label, size=11) for _v, label in options]
        return ft.CupertinoSlidingSegmentedButton(
            selected_index=0, controls=texts, thumb_color=BLUE, width=560,
            on_change=lambda e: on_pick(
                options[e.control.selected_index][0]))

    def _field(**kw):
        return ft.TextField(width=560, bgcolor=DARK, color=WHITE,
                            border=CONSTANTS.input_border(GREY), **kw)

    def _mail_files(m):
        """Pièces jointes du mail : un bouton par fichier (ouvert dans
        l'application par défaut) et « Enregistrer » dans un dossier."""
        fid = m["files_id"]
        files = ft.Row([], wrap=True, spacing=6)
        temp = os.path.join(tempfile.gettempdir(), "hub_mail_files", fid)
        status = ft.Text("", size=11, color=LIGHT_GREY)

        def _download(folder, names):
            os.makedirs(folder, exist_ok=True)
            for n in names:
                with open(os.path.join(folder, n), "wb") as f:
                    f.write(hub_sync.file_req("GET", fid, n))
            return folder

        def _open(n):
            _bg(lambda: _download(temp, [n]), lambda out: isinstance(
                out, Exception) or ui._open_file_default(
                    os.path.join(out, n)))

        def _saved(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            status.value = f"Enregistré dans {out}"
            open_btn.data = out
            open_btn.visible = "open_folder" in hooks

        def _open_in_hub(e):
            for c in page.overlay:
                if isinstance(c, ft.AlertDialog):
                    c.open = False
            hooks["open_folder"](open_btn.data)

        async def _save(e):
            folder = await ft.FilePicker().get_directory_path(
                dialog_title="Enregistrer les pièces jointes dans")
            if folder:
                status.value = "Téléchargement…"
                page.update()
                names = [c.data for c in files.controls]
                _bg(lambda: _download(folder, names), _saved)

        def _listed(names):
            if isinstance(names, Exception):
                names = []
            files.controls = [ft.TextButton(
                n, icon=ft.Icons.ATTACH_FILE, data=n,
                on_click=lambda e, n=n: _open(n)) for n in names]
        _bg(lambda: hub_sync.list_files(fid), _listed)
        open_btn = ft.TextButton("Ouvrir dans Hub",
                                 icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                                 visible=False, on_click=_open_in_hub)
        return ft.Column([files, ft.Row([ft.TextButton(
            "Enregistrer", icon=ft.Icons.DOWNLOAD, on_click=_save),
            open_btn], spacing=6), status], spacing=4, tight=True)

    # ── Réponse à un mail ────────────────────────────────────────────────
    def open_reply(m, on_done=None):
        o = {"tu": False, "tone": TONES[0][0]}
        hint = _field(hint_text="Consignes", multiline=True, min_lines=1,
                      max_lines=3)
        text = _field(hint_text="Réponse", multiline=True, min_lines=8,
                      max_lines=16)
        status = ft.Text("", size=11, color=LIGHT_GREY)
        veil = ui_helpers.busy_veil("", ui.VIOLET)

        def _busy(msg=None):
            veil.content.controls[1].value = msg or ""
            ui_helpers.set_busy_veil(veil, bool(msg))
            page.update()
        joined = []
        names = ft.Text("", size=11, color=LIGHT_GREY)

        async def _join(e):
            picked = await ft.FilePicker().pick_files(
                dialog_title="Joindre des fichiers", allow_multiple=True)
            joined.extend(f.path for f in picked or [] if f.path)
            names.value = ", ".join(os.path.basename(p) for p in joined)
            page.update()

        def _files():
            out = []
            for p in joined:
                with open(p, "rb") as f:
                    out.append({"name": os.path.basename(p), "data":
                                base64.b64encode(f.read()).decode()})
            return out

        def _draft(e):
            _busy("Rédaction…")
            _bg(lambda: hub_sync.mail("draft", id=m["message_id"],
                                      tu=o["tu"], tone=o["tone"],
                                      hint=hint.value or ""), _drafted)

        def _drafted(out):
            _busy()
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
            else:
                status.value, text.value = "", out

        def _send(e):
            if not (text.value or "").strip():
                return
            _busy("Envoi en cours…")
            _bg(lambda: hub_sync.mail("reply", id=m["message_id"],
                                      text=text.value, files=_files()),
                _sent)

        def _sent(out):
            _busy()
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            _close(dlg)
            if on_done:
                on_done(m)

        def _to_task(e):
            _close(dlg)
            sender = m.get("from", "")
            mail = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", sender)
            name = sender.split("<")[0].strip().strip('"')
            body = m.get("body", "")
            tel = re.search(r"(?:\+|00)?\d[\d ./-]{7,}\d", body)
            hooks["new_task"]({
                "demande": " – ".join(
                    x for x in (name, m.get("subject", "")) if x),
                "email": mail.group(0) if mail else "",
                "telephone": tel.group(0) if tel else "",
                "notes": body})

        dlg = _dialog(
            title=ft.Row([
                ft.Text(m.get("subject") or "(sans sujet)", expand=True),
                ft.IconButton(ft.Icons.CLOSE, icon_color=LIGHT_GREY,
                              tooltip="Fermer",
                              on_click=lambda e: _close(dlg))]),
            content=ft.Stack([ft.Column([
                ft.Text(m.get("from", ""), size=11, color=LIGHT_GREY),
                ft.Text(m.get("body", ""), color=WHITE, selectable=True),
                *([_mail_files(m)] if m.get("files_id")
                  else []),
                ft.Divider(height=1, color=GREY),
                _seg([(False, "Vous"), (True, "Tu")],
                     lambda v: o.update(tu=v)),
                _seg(TONES, lambda v: o.update(tone=v)),
                hint, text, names, status,
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO, width=600,
               height=max(300, min(680, (page.height or 900) - 220))),
                veil]),
            actions=[*([_dlg_btn("Tâche", color=ui.ORANGE,
                                 on_click=_to_task)]
                       if "new_task" in hooks else []),
                     _dlg_btn("Joindre", color=CONSTANTS.COLOR_MINT,
                              on_click=_join),
                     _dlg_btn("Rédiger", color=ui.VIOLET,
                              on_click=_draft),
                     _dlg_btn("Envoyer", "primary", on_click=_send)],
            inset_padding=ft.Padding(20, 40, 20, 40))
        _show(dlg)

    # ── Briefing du matin : onglet de Hub, une carte par section ─────────
    accent = ui.SURFACE_ACCENT["briefing"]
    # Couleur par section, d'après son titre (Échéances en rouge…).
    section_colors = [("chéance", RED), ("mail", BLUE),
                      ("tâche", ui.VIOLET), ("liste", ui.PINK),
                      ("agenda", ui.YELLOW_GREEN), ("rappel", ui.ORANGE)]

    def _card(title, color, controls):
        return ft.Container(
            ft.Column([ft.Text(title, color=color, size=CONSTANTS.TEXT_LG,
                               weight=ft.FontWeight.W_500)] + controls,
                      spacing=6, tight=True),
            bgcolor=ft.Colors.with_opacity(0.12, color),
            border=ft.Border(left=ft.BorderSide(4, color)),
            border_radius=CONSTANTS.BUTTON_RADIUS,
            padding=ft.Padding(16, 12, 16, 14),
            col={"xs": 12, "md": 6})

    def _sections(text):
        """Découpe le Markdown du briefing sur les titres « ## »."""
        out, title, lines = [], None, []
        for line in (text or "").splitlines():
            if line.startswith("## "):
                if title or "".join(lines).strip():
                    out.append((title or "Briefing", "\n".join(lines)))
                title, lines = line[3:].strip(), []
            elif not line.startswith("# "):
                lines.append(line)
        if title or "".join(lines).strip():
            out.append((title or "Briefing", "\n".join(lines)))
        return out

    def _quiz_card(q):
        """Question du jour du quiz : un choix révèle réponse et anecdote."""
        yellow = CONSTANTS.COLOR_YELLOW
        result = ft.Column(spacing=4, tight=True)

        def _pick(e, i):
            for j, btn in enumerate(buttons):
                btn.disabled = True
                if j == q["answer"]:
                    btn.bgcolor = CONSTANTS.COLOR_GREEN
                elif j == i:
                    btn.bgcolor = CONSTANTS.COLOR_RED
            ok = i == q["answer"]
            result.controls = [
                ft.Text("Bravo !" if ok else "C'était : "
                        + q["choices"][q["answer"]], color=WHITE,
                        weight=ft.FontWeight.W_500),
                ft.Text(q.get("explain", ""), color=LIGHT_GREY)]
            page.update()
        buttons = [ft.Button(c, color=WHITE, bgcolor=GREY,
                             on_click=lambda e, i=i: _pick(e, i))
                   for i, c in enumerate(q["choices"])]
        return _card("Question du jour", yellow, [
            ft.Text(q["q"], color=WHITE, size=CONSTANTS.TEXT_LG),
            ft.Row(buttons, wrap=True, spacing=8, run_spacing=8),
            result])

    def _extra_cards(b):
        """Comme l'accueil de la webapp : anecdotes et actus (échéances et
        tâches sont déjà dans le texte du briefing)."""
        cards = []
        if b.get("digest"):
            cards.append(_card("Le saviez-tu ?", accent, [ft.Container(
                ft.Markdown(d["md"],
                            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB),
                ink=True, border_radius=8, padding=ft.Padding(6, 4, 6, 4),
                on_click=lambda e, u=d["link"]: u and hooks.get(
                    "open_news", webbrowser.open)(u))
                for d in b["digest"]]))
        if b.get("news"):
            cards.append(_card("Actus", BLUE, [ft.ListTile(
                title=ft.Text(n.get("title") or "", color=WHITE),
                subtitle=ft.Text(n.get("source") or "", color=LIGHT_GREY),
                on_click=lambda e, u=n.get("link"): u and hooks.get(
                    "open_news", webbrowser.open)(u))
                for n in b["news"]]))
        return cards

    def _task_cards(refill, b):
        """À faire et En cours : clic = fiche, pastille = état suivant."""
        rows = hooks["kanban_rows"]()
        (todo, todo_c), (doing, doing_c) = ui.KANBAN_ETATS[:2]
        nxt = {todo: (doing, doing_c),
               doing: ("Terminé", ui.KANBAN_ETAT_COLORS["Terminé"])}

        def _advance(row, etat):
            hooks["set_etat"](row, etat)
            if etat == "Terminé":
                notify_client(row,
                              on_sent=lambda: hooks["set_prevenu"](row))
            refill(b)

        def _line(row):
            etat, color = nxt[row["etat"]]
            return ft.ListTile(
                title=ft.Text(row["demande"] or "(sans titre)",
                              color=WHITE),
                trailing=ft.Button(
                    etat.split(" /")[0], icon=ft.Icons.ARROW_FORWARD,
                    color=DARK, bgcolor=color,
                    on_click=lambda e, r=row, t=etat: _advance(r, t)),
                on_click=lambda e, r=row: hooks["open_task"](r))
        cards = []
        for etat, color in ((todo, todo_c), (doing, doing_c)):
            mine = [r for r in rows if r["etat"] == etat]
            more = ([ft.Text(f"+ {len(mine) - 8} autres", color=LIGHT_GREY)]
                    if len(mine) > 8 else [])
            cards.append(_card(f"{etat} · {len(mine)}", color,
                               [_line(r) for r in mine[:8]] + more))
        return cards

    def _text_of(ctl):
        """Tout le texte d'un contrôle, pour estimer sa hauteur."""
        out = getattr(ctl, "value", None) or ""
        if not isinstance(out, str):
            out = ""
        for attr in ("content", "title", "subtitle"):
            sub = getattr(ctl, attr, None)
            if sub is not None and not isinstance(sub, str):
                out += " " * 60 + _text_of(sub)
        for sub in getattr(ctl, "controls", None) or []:
            out += " " * 60 + _text_of(sub)
        return out

    def _briefing_controls(b, refill):
        if isinstance(b, Exception):
            return [ft.Text(f"Pi injoignable : {b}", color=RED)]
        cards = []
        if b["pi"]:
            cards.append(_card("Pi", RED, [ft.Text(p, color=WHITE)
                                           for p in b["pi"]]))
        wx = b.get("weather")
        if wx:
            cards.append(_card("Météo · Leuze", YELLOW, [
                ft.Text(f"{wx['max']}° / {wx['min']}° · {wx['label']}",
                        color=WHITE, size=CONSTANTS.TEXT_LG),
                ft.Text(f"Pluie {wx.get('rain', '–')} % · vent "
                        f"{wx['wind']} km/h", color=LIGHT_GREY)]))
        mails = b["mails"]

        def _answered(m):
            if m in b["mails"]:
                b["mails"].remove(m)
                refill(b)

        def _dismiss(m):
            _answered(m)
            _bg(lambda: hub_sync.mail("done", id=m["message_id"]),
                lambda out: None)
        if mails:
            cards.append(_card(f"Mails · {len(mails)}", BLUE, [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.MAIL_OUTLINE, color=BLUE),
                    title=ft.Text(m.get("name") or m["from"], color=WHITE),
                    subtitle=ft.Text(m.get("summary")
                                     or m.get("subject", ""),
                                     color=LIGHT_GREY),
                    trailing=ft.Row([
                        *([ft.Icon(ft.Icons.ATTACH_FILE, color=LIGHT_GREY,
                                   size=16)] if m.get("files_id") else []),
                        ft.IconButton(
                            ft.Icons.CLOSE, icon_color=LIGHT_GREY,
                            tooltip="Retirer",
                            on_click=lambda e, m=m: _dismiss(m))],
                        tight=True, spacing=0),
                    on_click=lambda e, m=m: open_reply(m, _answered))
                for m in mails]))
        if b.get("quiz"):
            cards.append(_quiz_card(b["quiz"]))
        for title, body in _sections(b["text"]):
            if "mail" in title.lower():  # déjà dans la carte Mails
                continue
            if "tâche" in title.lower() and "kanban_rows" in hooks:
                continue  # remplacé par les cartes interactives
            color = next((c for k, c in section_colors
                          if k in title.lower()), accent)
            cards.append(_card(title, color, [ft.Markdown(
                body.strip(), selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]))
        if "kanban_rows" in hooks:
            cards += _task_cards(refill, b)
        cards += _extra_cards(b)
        if not cards:
            cards.append(_card("Briefing", accent, [ft.Text(
                "Pas encore de briefing.", color=LIGHT_GREY)]))
        # Deux colonnes empilées (maçonnerie) : pas de trou sous une carte
        # plus courte que sa voisine. Hauteur estimée sur le texte.
        cols, heights = [[], []], [0, 0]
        for c in cards:
            i = heights.index(min(heights))
            cols[i].append(c)
            heights[i] += 2 + len(_text_of(c)) / 60
        ctl = [ft.ResponsiveRow([ft.Column(
            col, spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            col={"xs": 12, "md": 6}) for col in cols],
            spacing=12, run_spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START)]
        if b["at"]:
            when = datetime.datetime.fromtimestamp(b["at"])
            ctl.insert(0, ft.Text(when.strftime(
                "Briefing du %d/%m à %H:%M"), size=11, color=LIGHT_GREY))
        return ctl

    briefing_view = ft.ListView(expand=True, spacing=10,
                                padding=ft.Padding(16, 12, 16, 16))

    def _briefing_fill(b):
        briefing_view.controls = _briefing_controls(b, _briefing_fill)
        page.update()

    def briefing_refresh(event=None):
        if not briefing_view.controls:
            briefing_view.controls = [ft.Text("Chargement…",
                                              color=LIGHT_GREY)]
        _bg(lambda: hub_sync.mail("briefing", timeout=20), _briefing_fill)

    briefing_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                ui._surface_title("Briefing", "briefing"),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.REFRESH, **ui.SQUARE_BTN,
                              icon_color=accent,
                              icon_size=CONSTANTS.ICON_SM,
                              tooltip="Actualiser",
                              on_click=briefing_refresh),
            ], spacing=12),
            height=ui.TOOLBAR_H, padding=ft.Padding(12, 0, 12, 0),
            alignment=ft.Alignment(-1, 0), bgcolor=ui.BACKGROUND),
        ft.Divider(height=1, color=GREY),
        briefing_view,
    ], expand=True, spacing=0)

    # ── Client prévenu quand c'est prêt ──────────────────────────────────
    def notify_client(row, on_sent=None):
        """Mail « commande prête » ; row = ligne du Kanban de Hub."""
        mail = (row.get("email") or "").strip()
        if not mail:
            return

        def _text(tu):
            p = row.get("prix")
            prix = ("\nCela fera " + f"{p:g}".replace(".", ",") + " €."
                    if isinstance(p, (int, float)) and p else "")
            return (READY_TU if tu else READY).format(prix=prix)
        text = _field(value=_text(False), multiline=True, min_lines=10,
                      max_lines=16)
        status = ft.Text("", size=11, color=LIGHT_GREY)

        def _tu(v):
            text.value = _text(v)
            text.update()

        def _send(e):
            status.value = "Envoi…"
            page.update()
            _bg(lambda: hub_sync.mail("notify", to=mail, text=text.value),
                _sent)

        def _sent(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            _close(dlg)
            if on_sent:
                on_sent()

        dlg = _dialog(
            title=ft.Text("Prévenir le client"),
            content=ft.Column([ft.Text(mail, size=11, color=LIGHT_GREY),
                               _seg([(False, "Vous"), (True, "Tu")], _tu),
                               text, status], tight=True, spacing=8,
                              width=600),
            actions=[_dlg_btn("Plus tard", "cancel",
                              on_click=lambda e: _close(dlg)),
                     _dlg_btn("Envoyer", "primary", on_click=_send)])
        _show(dlg)

    hooks.update({"notify_client": notify_client,
                  "briefing_surface": briefing_surface,
                  "briefing_refresh": briefing_refresh})
    return hooks
