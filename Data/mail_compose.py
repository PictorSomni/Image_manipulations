"""Fenêtre mail unique de Hub : réponse, nouveau mail, « commande prête ».

Toute modification ici vaut partout (briefing, tâches, Kanban).
La webapp a son équivalent dans Mobile/mail.js.
"""

import base64
import os

import flet as ft

import CONSTANTS
import hub_sync

TONES = [("professionnel et chaleureux", "Chaleureux"),
         ("professionnel et sobre", "Sobre"), ("très bref", "Bref")]


def build(ui, bg, show, close, seg, field):
    """Renvoie open_mail(...) branché sur les outils de hub_mails."""
    page = ui.page
    WHITE, LIGHT_GREY, GREY = ui.WHITE, ui.LIGHT_GREY, ui.GREY

    def open_mail(to="", subject="", text=None, text_tu=None, reply=None,
                  header=None, extra_actions=(), on_sent=None, files=()):
        """reply : mail auquel on répond (adresse et objet imposés).
        text_tu : variante tutoyée du texte, appliquée au choix « Tu »
        tant que le texte n'a pas été retouché.
        header : contrôles affichés au-dessus (pièces du mail reçu…)."""
        o = {"tu": False, "tone": TONES[0][0], "touched": False}
        to_f = field(label="À", value=reply["from"] if reply else to,
                     read_only=bool(reply), autofocus=not (to or reply))
        subj_f = field(label="Objet", value=subject,
                       visible=not reply)
        hint = field(hint_text="Consignes", multiline=True, min_lines=1,
                     max_lines=3)
        if text is None:
            text = "" if reply else "Bonjour,\n\n"
        body = field(label="Message", multiline=True, min_lines=10,
                     max_lines=16, value=text,
                     on_change=lambda e: o.update(touched=True))
        status = ft.Text("", size=13, color=WHITE)
        joined = list(files)
        names = ft.Text(", ".join(os.path.basename(p) for p in joined),
                        size=13, color=LIGHT_GREY)

        def _tu(v):
            o["tu"] = v
            if text_tu and not o["touched"]:
                body.value = text_tu if v else text
                body.update()

        async def _join(e):
            picked = await ft.FilePicker().pick_files(
                dialog_title="Joindre des fichiers", allow_multiple=True,
                initial_directory=ui.state["folder"] or None)
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
            status.value = "Rédaction…"
            page.update()
            if reply:
                work = lambda: hub_sync.mail(  # noqa: E731
                    "draft", id=reply["message_id"], tu=o["tu"],
                    tone=o["tone"], hint=hint.value or "")
            else:
                work = lambda: hub_sync.mail(  # noqa: E731
                    "compose", to=to_f.value, subject=subj_f.value,
                    tu=o["tu"], tone=o["tone"], hint=hint.value or "")
            bg(work, _drafted)

        def _drafted(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
            else:
                status.value, body.value = "", out
                o["touched"] = True

        def _send(e):
            if not (body.value or "").strip():
                return
            status.value = "Envoi…"
            page.update()
            if reply:
                work = lambda: hub_sync.mail(  # noqa: E731
                    "reply", id=reply["message_id"], text=body.value,
                    files=_files())
            else:
                work = lambda: hub_sync.mail(  # noqa: E731
                    "new", to=to_f.value, subject=subj_f.value,
                    text=body.value, files=_files())
            bg(work, _sent)

        def _sent(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            close(dlg)
            if on_sent:
                on_sent()

        title = (reply.get("subject") or "(sans sujet)") if reply \
            else "Mail"
        dlg = ui._dialog(
            title=ft.Row([
                ft.Text(title, expand=True),
                ft.IconButton(ft.Icons.CLOSE, icon_color=LIGHT_GREY,
                              tooltip="Fermer",
                              on_click=lambda e: close(dlg))]),
            content=ft.Column([
                *(header or []),
                *([ft.Divider(height=1, color=GREY)] if header else []),
                to_f, subj_f,
                seg([(False, "Vous"), (True, "Tu")], _tu),
                seg(TONES, lambda v: o.update(tone=v)),
                hint, body, names, status],
                tight=True, spacing=8, width=600,
                scroll=ft.ScrollMode.AUTO,
                height=max(300, min(680, (page.height or 900) - 220))),
            actions=[*extra_actions,
                     ui._dlg_btn("Joindre", color=CONSTANTS.COLOR_MINT,
                                 on_click=_join),
                     ui._dlg_btn("Rédiger", color=ui.VIOLET,
                                 on_click=_draft),
                     ui._dlg_btn("Envoyer", "primary", on_click=_send)],
            inset_padding=ft.Padding(20, 40, 20, 40))
        show(dlg)
        return dlg

    return open_mail
