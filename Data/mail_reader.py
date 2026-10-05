"""Lecture seule de la boîte mail du studio pour l'IA (retour user).

Identifiants dans ~/.mail (hors du repo, jamais commités) :
    ligne 1 : adresse   ligne 2 : mot de passe   ligne 3 (option) : serveur
Sans ce fichier, l'outil n'est pas proposé à l'IA.

La boîte est ouverte avec EXAMINE (lecture seule) et les messages lus avec
BODY.PEEK : rien n'est marqué comme lu, la boîte partagée reste intacte.
Aucun envoi, suppression ni déplacement possible depuis ce module.
"""

__version__ = "2.3.34"

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


def read_mails(days=3, limit=20, query="", max_chars=600, skip_ads=True,
               sender="", full=False):
    """Mails reçus ces `days` derniers jours (boîte de réception), lus ou
    non (boîte partagée : le collègue a pu les ouvrir), du plus récent au
    plus ancien, en texte pour l'IA. Pubs/newsletters écartées sauf
    skip_ads=False."""
    creds = _credentials()
    if not creds:
        return "Accès mail non configuré sur cette machine."
    user, password, host = creds
    # Recherche ciblée (expéditeur/mot) : on remonte loin et on lit tout
    # (retour user : demandes d'une cliente incomplètes).
    days = max(1, min(int(days or 3), 365))
    if full:
        max_chars = 20_000
    limit = max(1, min(int(limit or 20), 50))
    since = (datetime.date.today() - datetime.timedelta(days=days)
             ).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL(host, 993, timeout=30)
    found, ads = [], 0
    try:
        imap.login(user, password)
        imap._encoding = "utf-8"
        # Reçus + envoyés (retour user : suivi complet d'un échange).
        folders = [("INBOX", "Reçu", "FROM")]
        sent = next((ln.decode().rsplit(' "/" ', 1)[-1]
                     for ln in imap.list()[1] if b"\\Sent" in ln), None)
        if sent:
            folders.append((sent, "Envoyé", "TO"))
        for folder, label, who in folders:
            criteria = ["SINCE", since]
            if sender:
                criteria += [who, '"' + sender.replace('"', "") + '"']
            if query:
                criteria += ["TEXT", '"' + query.replace('"', "") + '"']
            imap.select(folder, readonly=True)  # EXAMINE : lecture seule
            _, data = imap.search(None, *criteria)
            kept = 0
            for num in data[0].split()[::-1]:
                if kept >= limit:
                    break
                # BODY.PEEK : ne pose pas le drapeau \\Seen.
                _, parts = imap.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(parts[0][1])
                if skip_ads and is_bulk(msg):
                    ads += 1
                    continue
                kept += 1
                try:
                    date = email.utils.parsedate_to_datetime(msg["Date"])
                except (TypeError, ValueError):
                    date = None
                files = [_decode(p.get_filename()) for p in msg.walk()
                         if p.get_filename()]
                stamp = f"{date:%Y-%m-%d %H:%M}" if date else "?"
                found.append((stamp,
                    f"- {stamp} | {label} | De : {_decode(msg['From'])}"
                    f" | À : {_decode(msg['To'])}\n"
                    f"  Objet : {_decode(msg['Subject'])}\n"
                    + (f"  Pièces jointes : {', '.join(files)}\n" if files
                       else "")
                    + f"  {_body_text(msg, max_chars)}"))
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    found.sort(key=lambda f: f[0], reverse=True)
    out = [text for _, text in found[:limit]]
    note = f"\n({ads} pub(s)/newsletter(s) écartée(s))" if ads else ""
    return ("\n".join(out) or "Aucun mail sur la période.") + note


TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_mails",
        "description": (
            "Lit (lecture seule) les mails reçus ET envoyés de la boîte du studio "
            "(info@studiocleuze.be) : date, expéditeur, objet, début du "
            "texte. Lus ou non (boîte partagée). Pubs/newsletters "
            "écartées par défaut. Ne marque rien comme lu. Impossible "
            "d'envoyer, répondre ou supprimer."),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer",
                         "description": "Nombre de jours en arrière (1-365, défaut 3)"},
                "sender": {"type": "string",
                           "description": "Filtrer par expéditeur (nom ou adresse, optionnel)"},
                "full": {"type": "boolean",
                         "description": "Texte complet des mails au lieu d'un extrait — à utiliser pour lister des demandes/détails"},
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
