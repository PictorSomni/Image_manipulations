"""Mails du studio envoyés depuis le Pi (info@studiocleuze.be).

Réponses aux mails repérés par le briefing (~/briefing_mails.json),
rédigées à la demande de Charles, et « commande prête » aux clients.
Rien ne part sans validation dans Hub ou la webapp. Tourne sur le Pi
(mot de passe via `pass`) ; Hub y accède par hub-sync (POST /mail).
"""
import base64
import email.utils
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


def _cache(name):
    try:
        with open(os.path.join(HOME, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def extras():
    """Ce que la webapp montre en plus à l'accueil, pour le briefing de
    Hub : météo, anecdotes, actus (caches de Mobile/mobile.py)."""
    today = datetime.date.today().isoformat()
    wx = _cache(".hub_mobile_weather.json")
    dg = _cache(".hub_mobile_digest.json")
    news = _cache(".hub_mobile_news.json").get("items") or []
    return {"weather": wx if wx.get("date") == today else None,
            "digest": [{"md": e["md"], "link": (e.get("item") or {})
                        .get("link")}
                       for e in dg.get("entries") or [] if e.get("md")],
            "news": [{k: it.get(k) for k in ("title", "source", "link")}
                     for it in news[:3]]}


def pending():
    return [m for m in _read() if not m.get("done")]


def _mail(mid):
    return next(m for m in _read() + _found() if m["message_id"] == mid)


FOUND = os.path.join(HOME, "mail_search.json")


def _found():
    """Derniers résultats de recherche : pour y répondre ensuite."""
    try:
        with open(FOUND, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _clean_body(msg):
    """Texte lisible : paragraphes gardés, HTML débalisé, historique
    cité (« Le … a écrit », « De : … ») coupé."""
    parts = [p for p in msg.walk() if not p.get_filename()
             and p.get_content_type() in ("text/plain", "text/html")]
    part = next((p for p in parts if p.get_content_type() == "text/plain"),
                parts[0] if parts else None)
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", "replace")
    if part.get_content_type() == "text/html":
        text = re.sub(r"(?is)<(style|script|head).*?</\1>", "", text)
        text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d)>", "\n", text)
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        line = " ".join(line.replace("\xa0", " ").split())
        if line.startswith(">"):
            continue
        if re.match(r"(Le .{5,120} a écrit ?:|On .{5,120} wrote:|"
                    r"-+ ?(Original|Message d'origine)|"
                    r"(De|From) ?: .+@)", line):
            break
        lines.append(line)
    text = "\n".join(lines)
    # Lignes coupées à ~76 caractères par le client mail : recollées.
    text = re.sub(r"(?<=[^\n.!?:;])\n(?=[a-zà-ÿ(])", " ", text)
    text = re.sub(r"\[https?://[^\]]*\]|<(mailto:|https?://)[^>]*>", "",
                  text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:20_000]


def copy_files(src, dst):
    """Copie ~/task_files/<src> (pièces jointes d'un mail) dans le
    dossier de la tâche <dst> (id avec ou sans tirets)."""
    import shutil
    src, dst = src.replace("-", ""), dst.replace("-", "")
    if not (re.fullmatch(r"[0-9a-f]{32}", src)
            and re.fullmatch(r"[0-9a-f]{32}", dst)):
        raise ValueError("id invalide")
    root = os.path.join(HOME, "task_files")
    shutil.copytree(os.path.join(root, src), os.path.join(root, dst),
                    dirs_exist_ok=True)
    return True


def search(q, limit=30):
    """Mails reçus et envoyés (toute la boîte) dont l'expéditeur, le
    destinataire ou l'objet contient `q` — à défaut, le texte."""
    import email
    import email.policy
    import email.utils
    import sys
    import mail_reader
    sys.path.insert(0, os.path.join(os.path.dirname(
        os.path.abspath(__file__)), "..", "Pi"))
    from mail_watch import _save_files
    q = (q or "").replace('"', "").strip()
    if not q:
        return []
    found = []
    with imaplib.IMAP4_SSL(HOST, 993, timeout=30) as imap:
        imap.login(ADDRESS, _password())
        imap._encoding = "utf-8"
        for folder, sent in (("INBOX", False), (_sent_folder(imap), True)):
            imap.select(folder, readonly=True)
            arg = '"' + q + '"'
            # Un critère à la fois : le OR imbriqué rate chez OVH Exchange.
            nums = sorted({n for key in ("FROM", "TO", "SUBJECT")
                           for n in imap.search(None, key, arg)[1][0].split()},
                          key=int)
            if not nums:
                _, data = imap.search(None, "TEXT", arg)
                nums = data[0].split()
            for num in nums[::-1][:limit]:
                _, parts = imap.fetch(num, "(BODY.PEEK[])")
                msg = email.message_from_bytes(parts[0][1],
                                               policy=email.policy.default)
                try:
                    date = email.utils.parsedate_to_datetime(msg["Date"])
                    stamp = f"{date:%Y-%m-%d %H:%M}"
                except (TypeError, ValueError):
                    stamp = ""
                other = mail_reader._decode(msg["To" if sent else "From"])
                found.append({
                    "message_id": msg["Message-ID"] or f"{folder}:{num}",
                    # Répondre à un mail envoyé = écrire au destinataire.
                    "from": other,
                    "name": ("→ " if sent else "")
                    + (other.split("<")[0].strip().strip('"') or other),
                    "subject": mail_reader._decode(msg["Subject"]),
                    "body": _clean_body(msg),
                    "date": stamp, "sent": sent})
                mid = found[-1]["message_id"]
                try:  # pièces jointes servies par /files, comme le briefing
                    found[-1]["files_id"] = _save_files(msg, mid)
                except Exception as exc:
                    print(f"[Mail] pièces jointes : {exc}", flush=True)
    found.sort(key=lambda m: m["date"], reverse=True)
    found = found[:limit]
    with open(FOUND + ".tmp", "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False)
    os.replace(FOUND + ".tmp", FOUND)
    return found


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


def compose(to, subject, tu, tone, hint):
    """Mail écrit de zéro : rédigé d'après les consignes de Charles."""
    rule = (f"Rédige un mail du Studio C, magasin photo à Leuze (studio, "
            f"tirages, encadrement), à {to or 'un client'}"
            + (f", objet « {subject} »" if subject else "")
            + f". {'Tutoie' if tu else 'Vouvoie'} la personne, ton {tone}. "
            f"Commence par « Bonjour, ». Termine exactement par « Belle "
            f"journée, » puis « Studio C » à la ligne. "
            "Rends uniquement le corps du mail.")
    return hub_sync.ask_claude(hub_sync.claude_prompt(
        f"Consignes de Charles : {hint or subject}", rule))


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
    # Sans Date ni Message-ID, les autres logiciels classaient la copie
    # des « Éléments envoyés » n'importe où (retour user).
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain="studiocleuze.be")
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
    if a == "copy_files":  # pièces jointes d'un mail → fichiers de tâche
        return copy_files(req["src"], req["dst"])
    if a == "search":
        return search(req.get("q", ""))
    if a == "briefing":  # le texte du matin, pour Hub
        path = os.path.join(HOME, "briefing.md")
        try:
            with open(path, encoding="utf-8") as f:
                return {"text": f.read(), "at": os.path.getmtime(path),
                        "mails": pending(), "pi": hub_sync.pi_problems(),
                        "quiz": quiz_daily(), **extras()}
        except OSError:
            return {"text": "", "at": None, "mails": pending(), "pi": [],
                    "quiz": quiz_daily(), **extras()}
    if a == "draft":
        return draft(req["id"], req["tu"], req["tone"], req.get("hint", ""))
    if a == "reply":
        return reply(req["id"], req["text"], req.get("files") or ())
    if a == "done":
        return _mark_done(req["id"])
    if a == "compose":
        return compose(req.get("to", ""), req.get("subject", ""),
                       req.get("tu"), req.get("tone", "professionnel"),
                       req.get("hint", ""))
    if a == "new":  # mail écrit de zéro
        return send(req["to"].strip(), req["subject"].strip() or "Studio C",
                    req["text"], files=req.get("files") or ())
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
