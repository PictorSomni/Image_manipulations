# -*- coding: utf-8 -*-
"""
Agrégation de flux RSS/Atom (news tech/IA + notes d'épisode de podcasts) —
portage Python de dashboard-perso/src/lib/feeds.ts pour la surface "Actus"
du Hub.

API publique :
  fetch_all_feeds() -> list[dict] triée par date décroissante
    chaque item : {"title", "link", "date" (datetime|None), "summary",
                   "source"}
"""

import datetime
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

_MIN_DATE = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

# Un flux à ajouter = une ligne ici. Même liste que dashboard-perso (retour
# user : "Les Numériques" retiré, trop généraliste grand public).
FEEDS = [
    ("https://tldr.tech/api/rss/ai", "TLDR AI"),
    ("https://tldr.tech/api/rss/tech", "TLDR Tech"),
    ("https://news.ycombinator.com/rss", "Hacker News"),
    ("https://simonwillison.net/atom/everything/", "Simon Willison"),
    # Podcasts : pas de transcript complet disponible sur ces flux,
    # seulement les notes d'épisode écrites (retour user, déjà vérifié).
    ("https://feeds.acast.com/public/shows/64d7fb0db4d0da0010a2f09d",
     "Comptoir IA (podcast)"),
    ("https://feeds.acast.com/public/shows/"
     "43160adc-fadd-4764-b93f-aa1ca93f22bf", "Underscore_ (podcast)"),
    ("https://feeds.simplecast.com/MdgHX7eu",
     "Tech&Co, la quotidienne (podcast)"),
    ("https://feeds.simplecast.com/yRFCMe21", "Culture IA (podcast)"),
]

# Un podcast quotidien peut publier des milliers d'épisodes archivés dans
# son flux (Tech&Co : 2000) — sans plafond, une seule source écraserait
# toutes les autres une fois tout fusionné/trié par date.
MAX_ITEMS_PER_FEED = 15

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text):
    if not text:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()


def _parse_date(raw):
    if not raw:
        return None
    dt = None
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    # Normalisé en UTC-aware : un mélange naïf/aware fait planter le tri
    # par date dans fetch_all_feeds (comparaison impossible entre les
    # deux), et toutes les dates RSS/Atom n'incluent pas de fuseau.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _local_tag(elem):
    return elem.tag.rsplit("}", 1)[-1]


def _fetch_one(entry):
    url, source = entry
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Hub-Actus/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception:
        # Un flux en panne ne doit pas casser toute la page — les autres
        # s'affichent quand même.
        return []

    root_tag = _local_tag(root)

    # RSS 2.0 (ex. TLDR, Hacker News) : <rss><channel><item>...
    if root_tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        items = []
        for item in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
            title = _strip_html(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            date = _parse_date(item.findtext("pubDate"))
            # Hacker News ne met qu'un lien "Comments" en description,
            # pas un vrai résumé — inutile à afficher.
            summary = _strip_html(item.findtext("description") or "")
            if summary.lower() == "comments":
                summary = ""
            items.append({"title": title, "link": link, "date": date,
                          "summary": summary, "source": source})
        return items

    # Atom : <feed><entry>...
    if root_tag == "feed":
        ns = {"a": "http://www.w3.org/2005/Atom"}
        items = []
        for entry_el in root.findall("a:entry", ns)[:MAX_ITEMS_PER_FEED]:
            title = _strip_html(entry_el.findtext("a:title", "", ns) or "")
            href = ""
            for link_el in entry_el.findall("a:link", ns):
                rel = link_el.get("rel")
                if rel != "self":
                    href = link_el.get("href", "")
                    break
            else:
                links = entry_el.findall("a:link", ns)
                if links:
                    href = links[0].get("href", "")
            date = _parse_date(entry_el.findtext("a:updated", "", ns))
            summary = _strip_html(entry_el.findtext("a:summary", "", ns)
                                  or "")
            items.append({"title": title, "link": href.strip(),
                          "date": date, "summary": summary,
                          "source": source})
        return items

    return []


def fetch_all_feeds():
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        results = list(pool.map(_fetch_one, FEEDS))
    items = [item for group in results for item in group]
    items.sort(key=lambda it: it["date"] or _MIN_DATE, reverse=True)
    return items
