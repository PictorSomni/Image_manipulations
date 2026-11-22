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
import ui_helpers

# Le message de Charles, mot pour mot (+ le prix s'il est connu).
READY = ("Bonjour,\n\nVotre commande est prête, vous pouvez venir la "
         "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")
READY_TU = ("Bonjour,\n\nTa commande est prête, tu peux venir la "
            "chercher au magasin.{prix}\n\nA bientôt,\nStudio C")


def build(ui):
    page = ui.page
    DARK, WHITE, GREY = ui.DARK, ui.WHITE, ui.GREY
    LIGHT_GREY, RED, BLUE = ui.LIGHT_GREY, ui.RED, ui.BLUE
    YELLOW, GREEN = CONSTANTS.COLOR_YELLOW, CONSTANTS.COLOR_GREEN
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
                # Une erreur dans done() ne doit pas bloquer l'affichage
                # (interface figée après un envoi, retour user).
                try:
                    done(out)
                except Exception:
                    import traceback
                    traceback.print_exc()
                finally:
                    page.update()
            _run_task(_apply)
        threading.Thread(target=_run, daemon=True).start()

    def _show(dlg):
        ui_helpers.show_dialog(page, dlg)

    def _close(dlg):
        if dlg is _DOCK:
            _dock_close()
            return
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

    # Bandeau Mails à part (retour user) : la rédaction survit aux
    # changements d'onglet, terminal au-dessous.
    _DOCK = object()
    mails_body = ft.Container(expand=True, padding=ft.Padding(12, 6, 12, 8),
                              alignment=ft.Alignment.TOP_LEFT)
    _MAILS_MIN, _MAILS_MAX = 160, 900

    def _on_mails_resize(e):
        mails_panel.height = max(_MAILS_MIN, min(
            _MAILS_MAX, mails_panel.height - e.local_delta.y))
        mails_panel.update()
        hooks.get("sync_btn", lambda: None)()

    mails_panel = ft.Container(
        content=ft.Column([
            ft.GestureDetector(
                content=ft.Container(height=6, bgcolor=BLUE),
                mouse_cursor=ft.MouseCursor.RESIZE_UP_DOWN,
                on_pan_update=_on_mails_resize),
            mails_body], spacing=0, expand=True),
        bgcolor=DARK, height=480, visible=False)

    _cur = {"add": None}

    def _dock(title_row, content, actions, add=None):
        _cur["add"] = add
        content.expand = True
        mails_body.content = ft.Column([
            title_row, content,
            *([ft.Row(actions, alignment=ft.MainAxisAlignment.END,
                      wrap=True)] if actions else [])],
            spacing=8, expand=True)
        # Ouvert depuis une fiche (tâche…) : on la ferme pour voir le
        # bandeau au lieu de le laisser sous le voile (retour user).
        for c in page.overlay:
            if isinstance(c, ft.AlertDialog) and c.open:
                c.open = False
        mails_panel.visible = True
        hooks.get("sync_btn", lambda: None)()
        page.update()
        return _DOCK

    def _dock_close():
        _cur["add"] = None
        _idle_fill()
        hooks.get("sync_btn", lambda: None)()
        page.update()

    _last = {"b": None}

    _MAILS_CACHE = CONSTANTS.state_file(".mails_cache.json")
    _recent = {"list": ui._load_json(_MAILS_CACHE, None), "todo": False,
               "loading": False}

    def _mail_tiles():
        """Tous les mails triés (sans spams), récents d'abord : à traiter
        en bleu, répondus en vert, retirés en gris (retour user)."""
        lst = _recent["list"]
        if lst is None:
            return [ft.Text("Chargement…", color=LIGHT_GREY)]

        def _done(m):
            m["done"] = m["replied"] = True
            _recent_load()
            if _last["b"] and not isinstance(_last["b"], Exception):
                b = _last["b"]
                b["mails"] = [x for x in b["mails"]
                              if x["message_id"] != m["message_id"]]
                _briefing_fill(b)

        def _dismiss(m):
            m["done"] = True
            _bg(lambda: hub_sync.mail("done", id=m["message_id"]),
                lambda out: _recent_load())

        def _tile(m):
            if not m.get("done"):
                color, icon = BLUE, ft.Icons.MAIL_OUTLINE
            elif m.get("replied"):
                color, icon = GREEN, ft.Icons.REPLY
            else:
                color, icon = GREY, ft.Icons.DRAFTS_OUTLINED
            todo = not m.get("done")
            return ft.Container(ft.ListTile(
                leading=ft.Icon(icon, color=color),
                title=ft.Text(m.get("name") or m["from"],
                              color=WHITE if todo else LIGHT_GREY,
                              weight=ft.FontWeight.BOLD if todo else None),
                subtitle=ft.Text(m.get("summary") or m.get("subject", ""),
                                 color=LIGHT_GREY, max_lines=1),
                trailing=ft.Text(mail_compose._when(m.get("date")), size=12,
                                 color=WHITE if todo else LIGHT_GREY),
                on_click=lambda e: open_reply(
                    m, _done, _dismiss if todo else None)),
                border=ft.Border(left=ft.BorderSide(4, color)))
        return [_tile(m) for m in lst
                if not (_recent["todo"] and m.get("done"))]

    def _recent_load():
        # Copie locale affichée tout de suite ; le Pi ne renvoie en
        # entier que les mails absents du cache (retour user).
        cache = {m["message_id"]: m for m in _recent["list"] or ()
                 if m.get("message_id")}
        _recent["loading"] = True

        def _got(out):
            _recent["loading"] = False
            if not isinstance(out, Exception):
                lst = []
                for m in out:
                    old = cache.get(m.get("message_id"))
                    lst.append({**old, **m} if old else m)
                _recent["list"] = lst
                ui._save_json(_MAILS_CACHE, lst)
            if mails_panel.visible and _idle():
                _idle_fill()
                page.update()
        _bg(lambda: hub_sync.mail("recent", limit=80, known=list(cache)),
            _got)

    def _idle():
        return mails_body.content is None or \
            getattr(mails_body.content, "data", None) == "idle"

    def _toggle_todo(e):
        _recent["todo"] = not _recent["todo"]
        _idle_fill()
        page.update()

    def _idle_fill():
        mails_body.content = ft.Column(data="idle", expand=True, controls=[
            ft.Row([
                ft.Text("Mails", color=BLUE, size=16,
                        weight=ft.FontWeight.BOLD),
                ft.Row([ft.ProgressRing(width=14, height=14,
                                        stroke_width=2, color=BLUE),
                        ft.Text("Nouveaux mails…", size=12,
                                color=LIGHT_GREY)],
                       spacing=6, visible=_recent["loading"]),
                ft.Container(expand=True),
                ft.IconButton(
                    ft.Icons.MARK_EMAIL_UNREAD, tooltip="À traiter",
                    icon_color=DARK if _recent["todo"] else BLUE,
                    bgcolor=BLUE if _recent["todo"] else None,
                    on_click=_toggle_todo),
                ft.IconButton(ft.Icons.SEARCH, icon_color=BLUE,
                              tooltip="Rechercher", on_click=search_mails),
                ft.IconButton(ft.Icons.EDIT, icon_color=BLUE,
                              tooltip="Nouveau mail",
                              on_click=lambda e: new_mail())]),
            ft.ListView(_mail_tiles(), expand=True)])

    def toggle_mails(e=None):
        if _idle():
            _recent_load()
            _idle_fill()
        mails_panel.visible = not mails_panel.visible
        hooks.get("sync_btn", lambda: None)()
        page.update()

    open_mail = mail_compose.build(ui, _bg, _show, _close, _seg, _field,
                                   dock=_dock)

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
            elif "open_folder" in hooks:
                # Autre dossier : on l'ouvre dans Fichiers (retour user).
                open_btn.data = out
                _open_in_hub(None)
                return
            open_btn.data = out
            open_btn.visible = "open_folder" in hooks

        def _open_in_hub(e):
            for c in page.overlay:
                if isinstance(c, ft.AlertDialog):
                    c.open = False
            hooks["open_folder"](open_btn.data)

        async def _save(e):
            # Sélecteur ouvert sur le dossier de l'onglet (retour user).
            folder = await ft.FilePicker().get_directory_path(
                dialog_title="Enregistrer les pièces jointes dans",
                initial_directory=ui.state["folder"] or None)
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
        def _save_here(e):
            folder = ui.state["folder"]
            if not folder:
                return
            status.value = "Téléchargement…"
            page.update()
            names = [c.data for c in files.controls]
            _bg(lambda: _download(folder, names), _saved)

        return ft.Column([previews, files, ft.Row([
            ft.TextButton("Enregistrer dans le dossier en cours",
                          icon=ft.Icons.DOWNLOAD, on_click=_save_here),
            ft.TextButton("Enregistrer sous…",
                          icon=ft.Icons.DRIVE_FOLDER_UPLOAD_OUTLINED,
                          on_click=_save),
            open_btn], spacing=6, wrap=True), status],
            spacing=4, tight=True)

    # ── Réponse à un mail (fenêtre commune : mail_compose) ───────────────
    def mail_to_task(m):
        """Fiche « nouvelle tâche » préremplie d'après le mail."""
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
            "notes": body,
            "files_id": m.get("files_id", "")})

    def open_reply(m, on_done=None, on_dismiss=None):
        box = {}

        def _retire(e):
            _close(box["dlg"])
            on_dismiss(m)

        def _to_task(e):
            _close(box["dlg"])
            mail_to_task(m)

        # Dernier message précédent du fil (reçu ou envoyé), d'office.
        history = ft.Column([], spacing=6)

        def _thread_fill(out):
            if isinstance(out, Exception) or not out:
                return
            x = out[-1]
            history.controls = [ft.Container(ft.Column([
                ft.Row([ft.Icon(ft.Icons.SEND if x["sent"]
                                else ft.Icons.MAIL_OUTLINE,
                                color=YELLOW, size=16),
                        ft.Text(x["date"], color=YELLOW, size=12,
                                weight=ft.FontWeight.BOLD)], spacing=6),
                ft.Text(x["body"], color=WHITE, selectable=True)],
                spacing=4), padding=10, border_radius=8,
                bgcolor=ft.Colors.with_opacity(0.12, YELLOW),
                border=ft.Border.all(1.5, YELLOW))]

        _bg(lambda: hub_sync.mail("thread", addr=m.get("from", ""),
                                  subject=m.get("subject", ""),
                                  exclude=m.get("message_id", "")),
            _thread_fill)

        box["dlg"] = open_mail(
            reply=m,
            header=[*([ft.Container(ft.Column([
                ft.Text(f"• {x}", color=WHITE, selectable=True)
                for x in m["points"]], spacing=2), bgcolor=ft.Colors
                .with_opacity(0.18, BLUE), border_radius=8, padding=10)]
                if m.get("points") else []),
                    ft.Text(m.get("body", ""), color=WHITE,
                            selectable=True),
                    *([_mail_files(m)] if m.get("files_id") else []),
                    history],
            extra_actions=[
                *([_dlg_btn("Marquer comme lu", color=GREEN, on_click=_retire)]
                  if on_dismiss else []),
                *([_dlg_btn("Tâche", color=ui.ORANGE, on_click=_to_task)]
                  if "new_task" in hooks else [])],
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

        def _task(m):
            _close(box["dlg"])
            mail_to_task(m)

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
                ft.Row([
                    _dlg_btn("Répondre", on_click=lambda e: _reply(m)),
                    *([_dlg_btn("Tâche", color=ui.ORANGE,
                                on_click=lambda e: _task(m))]
                      if "new_task" in hooks else [])]),
                ft.Text(m["body"], color=WHITE, selectable=True),
                *([_mail_files(m)] if m.get("files_id") else [])]
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
        """Anecdotes du jour tirées des actus (onglet Actus à part)."""
        cards = []
        if b.get("digest"):
            cards.append(_card("Le saviez-tu ?", accent, [ft.Container(
                ft.Markdown(d["md"],
                            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB),
                ink=True, border_radius=8, padding=ft.Padding(6, 4, 6, 4),
                on_click=lambda e, u=d["link"]: u and hooks.get(
                    "open_news", webbrowser.open)(u))
                for d in b["digest"]]))
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
        # Le matin : ce qui part aujourd'hui, ce qui est prêt, à encaisser.
        today = datetime.date.today().isoformat()
        open_ = [r for r in rows if r["etat"] != "Terminé"]
        urgent = [r for r in open_
                  if (r.get("deadline") or "9")[:10] <= today]
        ready = [r for r in open_ if r.get("projet") == "Fichiers prêts"]
        unpaid = [r for r in rows if r["etat"] == "Terminé"
                  and r.get("paye") == "Non payé"
                  and r.get("prevenu") in ("Prévenu", "Viendra d'office")]

        def _plain(row):
            return ft.ListTile(
                title=ft.Text(row["demande"] or "(sans titre)",
                              color=WHITE),
                subtitle=ft.Text(row["deadline"][:10], color=LIGHT_GREY)
                if row.get("deadline") else None,
                on_click=lambda e, r=row: hooks["open_task"](r))
        for title, color, lst in (
                ("Pour aujourd'hui", RED, urgent),
                ("Fichiers prêts", CONSTANTS.COLOR_CARAMEL, ready),
                ("À encaisser", YELLOW, unpaid)):
            if lst:
                cards.append(_card(f"{title} · {len(lst)}", color,
                                   [_plain(r) for r in lst[:8]]))
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
        recap = next((body for t, body in _sections(b["text"])
                      if "mail" in t.lower()), "").strip()
        new_btn.controls.insert(0, ft.IconButton(
            ft.Icons.UNFOLD_MORE, icon_color=BLUE, tooltip="Tous les mails",
            on_click=lambda e: toggle_mails() if not mails_panel.visible
            else None))
        cards.append(_card(f"Mails · {len(mails)}" if mails else "Mails",
                           BLUE, [ft.Markdown(recap, selectable=True)]
                           if recap else [], new_btn))
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
        _last["b"] = b
        if mails_panel.visible and _idle():
            _idle_fill()
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

    def new_mail(to_addr="", files=()):
        # Rédaction ouverte dans le bandeau : on y joint les fichiers
        # au lieu d'ouvrir un nouveau mail (retour user).
        if files and not to_addr and _cur["add"] and not _idle():
            _cur["add"](list(files))
            if not mails_panel.visible:
                mails_panel.visible = True
                hooks.get("sync_btn", lambda: None)()
                page.update()
            return
        open_mail(to=to_addr, files=files)

    hooks.update({"notify_client": notify_client,
                  "new_mail": new_mail,
                  "briefing_surface": briefing_surface,
                  "briefing_refresh": briefing_refresh,
                  "mails_panel": mails_panel,
                  "toggle_mails": toggle_mails})
    return hooks
