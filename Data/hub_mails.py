"""Hub : briefing du matin, réponses aux mails et « commande prête ».

Tout passe par le Pi (hub_sync.mail → Data/mail_reply.py) ; rien n'est
envoyé sans clic sur « Envoyer ».
"""
import datetime
import os
import tempfile
import threading

import flet as ft

import CONSTANTS
import hub_sync

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
    _dialog, _dlg_btn, _run_task = ui._dialog, ui._dlg_btn, ui._run_task

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
        return ft.Column([files, ft.TextButton(
            "Enregistrer", icon=ft.Icons.DOWNLOAD, on_click=_save),
            status], spacing=4, tight=True)

    # ── Réponse à un mail ────────────────────────────────────────────────
    def open_reply(m, on_done=None):
        o = {"tu": False, "tone": TONES[0][0]}
        hint = _field(hint_text="Consignes", multiline=True, min_lines=1,
                      max_lines=3)
        text = _field(hint_text="Réponse", multiline=True, min_lines=8,
                      max_lines=16)
        status = ft.Text("", size=11, color=LIGHT_GREY)

        def _draft(e):
            status.value = "Rédaction…"
            page.update()
            _bg(lambda: hub_sync.mail("draft", id=m["message_id"],
                                      tu=o["tu"], tone=o["tone"],
                                      hint=hint.value or ""), _drafted)

        def _drafted(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
            else:
                status.value, text.value = "", out

        def _send(e):
            if not (text.value or "").strip():
                return
            status.value = "Envoi…"
            page.update()
            _bg(lambda: hub_sync.mail("reply", id=m["message_id"],
                                      text=text.value), _sent)

        def _sent(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            _close(dlg)
            if on_done:
                on_done(m)

        def _ignore(e):
            _close(dlg)
            _bg(lambda: hub_sync.mail("done", id=m["message_id"]),
                lambda out: on_done and on_done(m))

        dlg = _dialog(
            title=ft.Text(m.get("subject") or "(sans sujet)"),
            content=ft.Column([
                ft.Text(m.get("from", ""), size=11, color=LIGHT_GREY),
                ft.Text(m.get("body", ""), color=WHITE, selectable=True),
                *([_mail_files(m)] if m.get("files_id")
                  else []),
                ft.Divider(height=1, color=GREY),
                _seg([(False, "Vous"), (True, "Tu")],
                     lambda v: o.update(tu=v)),
                _seg(TONES, lambda v: o.update(tone=v)),
                hint, text, status,
            ], tight=True, spacing=8, scroll=ft.ScrollMode.AUTO, width=600,
               height=max(300, min(680, (page.height or 900) - 220))),
            actions=[_dlg_btn("Ignorer", "cancel", on_click=_ignore),
                     _dlg_btn("Fermer", "cancel",
                              on_click=lambda e: _close(dlg)),
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

    def _briefing_controls(b, refill):
        if isinstance(b, Exception):
            return [ft.Text(f"Pi injoignable : {b}", color=RED)]
        cards = []
        if b["pi"]:
            cards.append(_card("Pi", RED, [ft.Text(p, color=WHITE)
                                           for p in b["pi"]]))
        mails = b["mails"]

        def _answered(m):
            b["mails"].remove(m)
            refill(b)
        if mails:
            cards.append(_card(f"Mails · {len(mails)}", BLUE, [
                ft.ListTile(
                    leading=ft.Icon(ft.Icons.MAIL_OUTLINE, color=BLUE),
                    title=ft.Text(m.get("name") or m["from"], color=WHITE),
                    subtitle=ft.Text(m.get("summary")
                                     or m.get("subject", ""),
                                     color=LIGHT_GREY),
                    on_click=lambda e, m=m: open_reply(m, _answered))
                for m in mails]))
        for title, body in _sections(b["text"]):
            if "mail" in title.lower():  # déjà dans la carte Mails
                continue
            color = next((c for k, c in section_colors
                          if k in title.lower()), accent)
            cards.append(_card(title, color, [ft.Markdown(
                body.strip(), selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB)]))
        if not cards:
            cards.append(_card("Briefing", accent, [ft.Text(
                "Pas encore de briefing.", color=LIGHT_GREY)]))
        ctl = [ft.ResponsiveRow(cards, spacing=12, run_spacing=12)]
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

    return {"notify_client": notify_client,
            "briefing_surface": briefing_surface,
            "briefing_refresh": briefing_refresh}
