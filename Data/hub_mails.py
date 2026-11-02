"""Hub : briefing du matin, réponses aux mails et « commande prête ».

Tout passe par le Pi (hub_sync.mail → Data/mail_reply.py) ; rien n'est
envoyé sans clic sur « Envoyer ».
"""
import datetime
import os
import re
import tempfile
import threading
import urllib.parse
import webbrowser

import flet as ft

import CONSTANTS
import hub_sync
import mail_compose
import thumb_cache

# Le message de Charles, mot pour mot (+ le prix s'il est connu).
READY = ("Bonjour,\n\nVotre commande est prête, vous pouvez venir la "
         "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")
READY_TU = ("Bonjour,\n\nTa commande est prête, tu peux venir la "
            "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")


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
        # Pas de retrait de page.overlay dans la même mise à jour : le
        # client ne voit jamais open=False et le dialogue reste orphelin.
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

    open_mail = mail_compose.build(ui, _bg, _show, _close, _seg, _field)

    VIEWER_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
                   ".tif", ".tiff", ".pdf")

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
            # Images/PDF : le mail se ferme et la pièce jointe s'affiche
            # en plein écran dans la visionneuse (retour user).
            def _shown(out):
                if isinstance(out, Exception):
                    return
                path = os.path.join(out, n)
                if os.path.splitext(n)[1].lower() not in VIEWER_EXTS:
                    ui._open_file_default(path)
                    return
                for c in page.overlay:
                    if isinstance(c, ft.AlertDialog):
                        c.open = False
                page.update()
                ui._open_viewer(path)
            _bg(lambda: _download(temp, [n]), _shown)

        def _preview(names):
            """Aperçu sous le message (retour user) : images et 1re page
            des PDF, rendues via thumb_cache comme dans Fichiers."""
            out = []
            for n in names:
                if os.path.splitext(n)[1].lower() in VIEWER_EXTS:
                    _download(temp, [n])
                    data = thumb_cache.get_or_generate(
                        os.path.join(temp, n), size_px=1600)
                    if data:
                        out.append((n, data))
            return out

        def _previewed(out):
            if isinstance(out, Exception):
                return
            previews.controls = [ft.GestureDetector(
                ft.Image(src=data, width=560, fit=ft.BoxFit.CONTAIN,
                         border_radius=CONSTANTS.BUTTON_RADIUS),
                mouse_cursor=ft.MouseCursor.CLICK,
                on_tap=lambda e, n=n: _open(n)) for n, data in out]

        def _saved(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            status.value = f"Enregistré dans {out}"
            if out == ui.state["folder"]:
                ui._refresh_folder()
            open_btn.data = out
            open_btn.visible = "open_folder" in hooks

        def _open_in_hub(e):
            for c in page.overlay:
                if isinstance(c, ft.AlertDialog):
                    c.open = False
            hooks["open_folder"](open_btn.data)

        async def _save(e):
            # Dossier de l'onglet ouvert dans Hub (retour user).
            folder = ui.state["folder"] or await ft.FilePicker(
            ).get_directory_path(
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
            _bg(lambda: _preview(names), _previewed)
        previews = ft.Column(spacing=8, tight=True)
        _bg(lambda: hub_sync.list_files(fid), _listed)
        open_btn = ft.TextButton("Ouvrir dans Hub",
                                 icon=ft.Icons.FOLDER_OPEN_OUTLINED,
                                 visible=False, on_click=_open_in_hub)
        return ft.Column([previews, files, ft.Row([ft.TextButton(
            "Enregistrer", icon=ft.Icons.DOWNLOAD, on_click=_save),
            open_btn], spacing=6), status], spacing=4, tight=True)

    # ── Réponse à un mail (fenêtre commune : mail_compose) ───────────────
    def open_reply(m, on_done=None):
        box = {}

        def _to_task(e):
            _close(box["dlg"])
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

        box["dlg"] = open_mail(
            reply=m,
            header=[ft.Text(m.get("body", ""), color=WHITE,
                            selectable=True),
                    *([_mail_files(m)] if m.get("files_id") else [])],
            extra_actions=[_dlg_btn("Tâche", color=ui.ORANGE,
                                    on_click=_to_task)]
            if "new_task" in hooks else [],
            on_sent=(lambda: on_done(m)) if on_done else None)

    # ── Recherche dans toute la boîte (reçus + envoyés) ──────────────────
    def search_mails(e=None):
        box = {}
        results = ft.ListView(spacing=0, height=480, width=380)
        status = ft.Text("", color=LIGHT_GREY)
        # Mail ouvert à côté de la liste : on compare sans fermer.
        preview = ft.Column([], width=560, height=480,
                            scroll=ft.ScrollMode.AUTO, spacing=6)

        def _reply(m):
            _close(box["dlg"])
            open_reply(m)

        def _pick(m):
            for t in results.controls:
                t.bgcolor = (ft.Colors.with_opacity(0.2, BLUE)
                             if t.data is m else None)
            preview.controls = [
                ft.Text(m["subject"] or "(sans objet)", color=WHITE,
                        size=CONSTANTS.TEXT_LG, selectable=True),
                ft.Text(f"{m['date']} · "
                        + ("À : " if m["sent"] else "De : ") + m["from"],
                        color=LIGHT_GREY, selectable=True),
                _dlg_btn("Répondre", on_click=lambda e: _reply(m)),
                *([_mail_files(m)] if m.get("files_id") else []),
                ft.Text(m["body"], color=WHITE, selectable=True)]
            page.update()

        def _done(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            status.value = "" if out else "Aucun mail"
            results.controls = [ft.ListTile(
                data=m,
                leading=ft.Icon(ft.Icons.SEND if m["sent"]
                                else ft.Icons.MAIL_OUTLINE, color=BLUE),
                title=ft.Text(m["name"], color=WHITE),
                subtitle=ft.Text(f"{m['date'][:10]} · {m['subject']}",
                                 color=LIGHT_GREY),
                trailing=ft.Icon(ft.Icons.ATTACH_FILE, color=LIGHT_GREY,
                                 size=16) if m.get("files_id") else None,
                on_click=lambda e, m=m: _pick(m)) for m in out]
            if out:
                _pick(out[0])

        def _go(e):
            q = field.value.strip()
            if not q:
                return
            status.value = "Recherche…"
            results.controls = []
            preview.controls = []
            page.update()
            _bg(lambda: hub_sync.mail("search", q=q), _done)

        field = _field(hint_text="Nom, adresse, objet…", autofocus=True,
                       on_submit=_go)
        box["dlg"] = _dialog(
            title=ft.Text("Rechercher un mail"), bar_color=BLUE,
            content=ft.Column([field, status, ft.Row(
                [results, ft.VerticalDivider(width=1, color=GREY), preview],
                vertical_alignment=ft.CrossAxisAlignment.START)],
                tight=True),
            actions=[_dlg_btn("Chercher", on_click=_go),
                     _dlg_btn("Fermer",
                              on_click=lambda e: _close(box["dlg"]))])
        _show(box["dlg"])

    # ── Briefing du matin : onglet de Hub, une carte par section ─────────
    accent = ui.SURFACE_ACCENT["briefing"]
    # Couleur par section, d'après son titre (Échéances en rouge…).
    section_colors = [("chéance", RED), ("mail", BLUE),
                      ("tâche", ui.VIOLET), ("liste", ui.PINK),
                      ("agenda", ui.YELLOW_GREEN), ("rappel", ui.ORANGE)]

    def _card(title, color, controls, action=None):
        head = ft.Text(title, color=color, size=CONSTANTS.TEXT_LG,
                       weight=ft.FontWeight.W_500)
        if action:
            head = ft.Row([head, action],
                          alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
        return ft.Container(
            ft.Column([head] + controls,
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
        # Terminées, client pas encore prévenu (comme la webapp).
        waiting = [r for r in rows if r["etat"] == "Terminé"
                   and r.get("prevenu") not in ("Prévenu",
                                                "Viendra d'office")]
        green = ui.KANBAN_ETAT_COLORS["Terminé"]

        def _prevenu(row):
            hooks["set_prevenu"](row)
            row["prevenu"] = "Prévenu"
            refill(b)

        def _sms(row):
            phone = re.sub(r"[^\d+]", "", row.get("telephone") or "")
            p = row.get("prix")
            prix = ("\nCela fera " + f"{p:g}".replace(".", ",") + " €."
                    if isinstance(p, (int, float)) and p else "")
            webbrowser.open(f"sms:{phone}&body="
                            + urllib.parse.quote(READY.format(prix=prix)))
            _prevenu(row)

        def _wait_line(row):
            btns = []
            if row.get("telephone"):
                btns.append(ft.IconButton(
                    ft.Icons.SMS, icon_color=green, tooltip="SMS",
                    on_click=lambda e, r=row: _sms(r)))
            if row.get("email"):
                btns.append(ft.IconButton(
                    ft.Icons.MAIL_OUTLINE, icon_color=BLUE, tooltip="Mail",
                    on_click=lambda e, r=row: notify_client(
                        r, on_sent=lambda: _prevenu(r))))
            btns.append(ft.IconButton(
                ft.Icons.DONE, icon_color=WHITE, tooltip="Prévenu",
                on_click=lambda e, r=row: _prevenu(r)))
            return ft.ListTile(
                title=ft.Text(row["demande"] or "(sans titre)",
                              color=WHITE),
                subtitle=ft.Text(row.get("telephone") or row.get("email")
                                 or "Pas de contact", color=LIGHT_GREY,
                                 selectable=True),
                trailing=ft.Row(btns, tight=True, spacing=0),
                on_click=lambda e, r=row: hooks["open_task"](r))
        if waiting:
            cards.append(_card(f"À prévenir · {len(waiting)}", green,
                               [_wait_line(r) for r in waiting]))
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
        new_btn = ft.IconButton(
            ft.Stack([
                ft.Icon(ft.Icons.MAIL_OUTLINE, color=BLUE, size=26),
                ft.Container(
                    ft.Icon(ft.Icons.ADD, color=DARK, size=13),
                    bgcolor=BLUE, border_radius=9, width=15, height=15,
                    alignment=ft.Alignment.CENTER, right=0, bottom=0)],
                width=30, height=30),
            tooltip="Nouveau mail",
            on_click=lambda e: new_mail())
        new_btn = ft.Row([
            ft.IconButton(ft.Icons.SEARCH, icon_color=BLUE,
                          tooltip="Rechercher", on_click=search_mails),
            new_btn], tight=True, spacing=0)
        if not mails:
            cards.append(_card("Mails", BLUE, [], new_btn))
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
                for m in mails], new_btn))
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
        p = row.get("prix")
        prix = ("\nCela fera " + f"{p:g}".replace(".", ",") + " €."
                if isinstance(p, (int, float)) and p else "")
        open_mail(to=mail, subject="Votre commande est prête",
                  text=READY.format(prix=prix),
                  text_tu=READY_TU.format(prix=prix), on_sent=on_sent)

    def new_mail(to_addr=""):
        open_mail(to=to_addr)

    hooks.update({"notify_client": notify_client,
                  "new_mail": new_mail,
                  "briefing_surface": briefing_surface,
                  "briefing_refresh": briefing_refresh})
    return hooks
