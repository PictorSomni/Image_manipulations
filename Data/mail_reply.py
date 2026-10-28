"""Mails du studio envoyés depuis le Pi (info@studiocleuze.be).

Réponses aux mails repérés par le briefing (~/briefing_mails.json),
rédigées à la demande de Charles, et « commande prête » aux clients.
Rien ne part sans validation dans Hub ou la webapp. Tourne sur le Pi
(mot de passe via `pass`) ; Hub y accède par hub-sync (POST /mail).
"""
import base64
import datetime
import html
import imaplib
import json
import mimetypes
import os
import re
import smtplib
import subprocess
import time
from email.message import EmailMessage

import hub_sync

HOME = os.path.expanduser("~")
MAILS = os.path.join(HOME, "briefing_mails.json")
ADDRESS = "info@studiocleuze.be"
HOST = "ex2.mail.ovh.net"
LOGO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "logo_mail.png")
# Ajouté sous chaque mail envoyé (réponses et « commande prête »).
FOOTER = ("\n\n--\nStudio C · Leuze · 081 51 17 57 · www.studiocleuze.be\n"
          "Ouvert de 9h30 à 12h15 et de 13h30 à 18h00\n"
          "Fermé le mardi, le dimanche et les jours fériés")


def _read():
    try:
        with open(MAILS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _mark_done(mid):
    mails = _read()
    for m in mails:
        if m["message_id"] == mid:
            m["done"] = True
    with open(MAILS + ".tmp", "w", encoding="utf-8") as f:
        json.dump(mails, f, ensure_ascii=False, indent=1)
    os.replace(MAILS + ".tmp", MAILS)


def quiz_daily():
    """Question du jour du quiz (Quiz/quiz.py), si elle date d'aujourd'hui."""
    try:
        with open(os.path.join(HOME, "quiz", "state.json"),
                  encoding="utf-8") as f:
            daily = json.load(f).get("daily") or {}
    except (OSError, ValueError):
        return None
    today = datetime.date.today().isoformat()
    return daily.get("q") if daily.get("date") == today else None


def pending():
    return [m for m in _read() if not m.get("done")]


def _mail(mid):
    return next(m for m in _read() if m["message_id"] == mid)


def draft(mid, tu, tone, hint):
    m = _mail(mid)
    rule = (f"Rédige la réponse du Studio C, magasin photo à Leuze (studio, tirages, "
            f"encadrement) à ce mail. {'Tutoie' if tu else 'Vouvoie'} la "
            f"personne, ton {tone}. Termine exactement par « Belle "
            f"journée, » puis « Studio C » à la ligne. Ne reprends "
            f"pas le détail de la commande ou de la demande : la "
            f"personne le connaît, réponds directement. "
            + (f"Consignes de Charles : {hint}. " if hint else "")
            + "Rends uniquement le corps du mail.")
    return hub_sync.ask_claude(hub_sync.claude_prompt(
        f"De : {m['from']}\nSujet : {m['subject']}\n\n{m['body']}", rule))


def _password():
    pw = subprocess.run(["pass", "show", "mail/studiocleuze"],
                        capture_output=True, text=True,
                        timeout=30).stdout.split("\n")[0]
    if not pw:
        raise RuntimeError("mot de passe mail introuvable (pass)")
    return pw


def _sent_folder(imap):
    for line in imap.list()[1]:
        if b"\\Sent" in line:
            return line.rsplit(b' "/" ', 1)[-1].decode()
    return "Sent"


def send(to, subject, text, reply_to=None, files=()):
    if not re.fullmatch(r"[^@\s<>,]+@[^@\s<>,]+\.[^@\s<>,]+", to or ""):
        raise ValueError(f"adresse invalide : {to}")
    msg = EmailMessage()
    msg["From"] = f"Studio C <{ADDRESS}>"
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["In-Reply-To"] = msg["References"] = reply_to
    body = text.rstrip() + FOOTER
    msg.set_content(body)
    # Version HTML : même texte + logo sous la signature.
    msg.add_alternative(
        '<div style="font-family:sans-serif">'
        + html.escape(body).replace("\n", "<br>")
        + '<br><br><img src="cid:logo" width="200" alt="Studio C"></div>',
        subtype="html")
    with open(LOGO, "rb") as f:
        msg.get_payload()[1].add_related(f.read(), "image", "png",
                                         cid="<logo>")
    for f in files:  # pièces jointes : {"name", "data" en base64}
        kind = (mimetypes.guess_type(f["name"])[0]
                or "application/octet-stream").split("/")
        msg.add_attachment(base64.b64decode(f["data"]), kind[0], kind[1],
                           filename=os.path.basename(f["name"]))
    pw = _password()
    with smtplib.SMTP(HOST, 587, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(ADDRESS, pw)
        smtp.send_message(msg)
    try:  # copie dans « Éléments envoyés » (le SMTP ne la range pas)
        with imaplib.IMAP4_SSL(HOST) as imap:
            imap.login(ADDRESS, pw)
            imap.append(_sent_folder(imap), "\\Seen",
                        imaplib.Time2Internaldate(time.time()),
                        msg.as_bytes())
    except (imaplib.IMAP4.error, OSError) as exc:
        print(f"[Mail] copie envoyés : {exc}", flush=True)


def reply(mid, text, files=()):
    m = _mail(mid)
    subj = m["subject"]
    send(m["from"], subj if subj.lower().startswith("re:")
         else "Re: " + subj, text, m["message_id"], files)
    _mark_done(mid)


def call(req):
    """Point d'entrée de hub-sync (POST /mail) et de la webapp."""
    a = req["action"]
    if a == "list":
        return pending()
    if a == "briefing":  # le texte du matin, pour Hub
        path = os.path.join(HOME, "briefing.md")
        try:
            with open(path, encoding="utf-8") as f:
                return {"text": f.read(), "at": os.path.getmtime(path),
                        "mails": pending(), "pi": hub_sync.pi_problems(),
                        "quiz": quiz_daily()}
        except OSError:
            return {"text": "", "at": None, "mails": pending(), "pi": [],
                    "quiz": quiz_daily()}
    if a == "draft":
        return draft(req["id"], req["tu"], req["tone"], req.get("hint", ""))
    if a == "reply":
        return reply(req["id"], req["text"], req.get("files") or ())
    if a == "done":
        return _mark_done(req["id"])
    if a == "notify":
        return send(req["to"], "Votre commande est prête", req["text"])
    raise ValueError(f"action inconnue : {a}")


if __name__ == "__main__":
    for bad in ("", "a@b", "x@y.be, z@w.be", "a b@c.be"):
        try:
            send(bad, "s", "t")
            raise AssertionError(bad)
        except ValueError:
            pass
    print("ok")
