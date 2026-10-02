"""Lecture seule de la boîte mail du studio pour l'IA (retour user).

Identifiants dans ~/.mail (hors du repo, jamais commités) :
    ligne 1 : adresse   ligne 2 : mot de passe   ligne 3 (option) : serveur
Sans ce fichier, l'outil n'est pas proposé à l'IA.

La boîte est ouverte avec EXAMINE (lecture seule) et les messages lus avec
BODY.PEEK : rien n'est marqué comme lu, la boîte partagée reste intacte.
Aucun envoi, suppression ni déplacement possible depuis ce module.
"""

__version__ = "2.3.23"

import datetime
import email
import email.header
import email.utils
import html
import imaplib
import os
import re

_HOST = "ex2.mail.ovh.net"


def _credentials():
    try:
        with open(os.path.expanduser("~/.mail"), encoding="utf-8-sig") as f:
            lines = [ln.strip() for ln in f.read().splitlines() if ln.strip()]
    except OSError:
        return None
    if len(lines) < 2:
        return None
    return lines[0], lines[1], (lines[2] if len(lines) > 2 else _HOST)


def available():
    return _credentials() is not None


def _decode(value):
    return str(email.header.make_header(
        email.header.decode_header(value or "")))


def _body_text(msg, max_chars):
    """Texte brut (ou HTML débalisé à défaut), sans les URL qui noient
    les newsletters."""
    parts = [p for p in msg.walk() if not p.get_filename()
             and p.get_content_type() in ("text/plain", "text/html")]
    part = next((p for p in parts if p.get_content_type() == "text/plain"),
                parts[0] if parts else None)
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", "replace")
    if part.get_content_type() == "text/html":
        text = html.unescape(re.sub(r"(?s)<(style|script).*?</\1>|<[^>]+>",
                                    " ", text))
    text = re.sub(r"https?://\S+", "", text)
    return " ".join(text.split())[:max_chars]


def is_bulk(msg):
    """Newsletter/pub : en-têtes posés par les outils d'envoi en masse."""
    return bool(msg["List-Unsubscribe"] or msg["List-Id"]
                or (msg["Precedence"] or "").lower() in ("bulk", "list"))


def read_mails(days=3, limit=20, query="", max_chars=600, skip_ads=True):
    """Mails reçus ces `days` derniers jours (boîte de réception), lus ou
    non (boîte partagée : le collègue a pu les ouvrir), du plus récent au
    plus ancien, en texte pour l'IA. Pubs/newsletters écartées sauf
    skip_ads=False."""
    creds = _credentials()
    if not creds:
        return "Accès mail non configuré sur cette machine."
    user, password, host = creds
    days = max(1, min(int(days or 3), 30))
    limit = max(1, min(int(limit or 20), 50))
    since = (datetime.date.today() - datetime.timedelta(days=days)
             ).strftime("%d-%b-%Y")
    criteria = ["SINCE", since]
    if query:
        criteria += ["TEXT", '"' + query.replace('"', "") + '"']
    imap = imaplib.IMAP4_SSL(host, 993, timeout=30)
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=True)  # EXAMINE : lecture seule
        imap._encoding = "utf-8"
        _, data = imap.search(None, *criteria)
        ids = data[0].split()[::-1]
        out, ads = [], 0
        for num in ids:
            if len(out) >= limit:
                break
            # BODY.PEEK : ne pose pas le drapeau \\Seen.
            _, parts = imap.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(parts[0][1])
            if skip_ads and is_bulk(msg):
                ads += 1
                continue
            date = email.utils.parsedate_to_datetime(msg["Date"]) \
                if msg["Date"] else None
            out.append(
                f"- {date:%Y-%m-%d %H:%M} | De : {_decode(msg['From'])}\n"
                f"  Objet : {_decode(msg['Subject'])}\n"
                f"  {_body_text(msg, max_chars)}" if date else
                f"- De : {_decode(msg['From'])} | "
                f"Objet : {_decode(msg['Subject'])}")
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    note = f"\n({ads} pub(s)/newsletter(s) écartée(s))" if ads else ""
    return ("\n".join(out) or "Aucun mail sur la période.") + note


TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_mails",
        "description": (
            "Lit (lecture seule) les mails récents de la boîte du studio "
            "(info@studiocleuze.be) : date, expéditeur, objet, début du "
            "texte. Lus ou non (boîte partagée). Pubs/newsletters "
            "écartées par défaut. Ne marque rien comme lu. Impossible "
            "d'envoyer, répondre ou supprimer."),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer",
                         "description": "Nombre de jours en arrière (1-30, défaut 3)"},
                "limit": {"type": "integer",
                          "description": "Nombre max de mails (1-50, défaut 20)"},
                "query": {"type": "string",
                          "description": "Mot à chercher (optionnel)"},
                "include_ads": {"type": "boolean",
                                "description": "Inclure pubs/newsletters (défaut non)"},
            },
        },
    },
}]


if __name__ == "__main__":
    print(read_mails(days=2, limit=3) if available() else "pas de ~/.mail")
