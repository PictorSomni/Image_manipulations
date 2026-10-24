# -*- coding: utf-8 -*-
"""
Agrégation de flux RSS/Atom (news tech/IA + notes d'épisode de podcasts) —
portage Python de dashboard-perso/src/lib/feeds.ts pour la surface "Actus"
du Hub.

API publique :
  fetch_all_feeds() -> list[dict] triée par date décroissante
    chaque item : {"title", "link", "date" (datetime|None), "summary",
                   "source", "category", "image" (url ou "")}
"""

__version__ = "2.10.126"


import datetime
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

_MIN_DATE = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

# Un flux à ajouter = une ligne ici : (url, nom, catégorie). Les
# catégories deviennent les filtres de la page Actus, dans cet ordre.
# Retirés (retour user) : "Les Numériques" (trop grand public), Hacker
# News.
CATEGORIES = ["IA", "Photo", "Tech", "Apple", "Podcasts"]
FEEDS = [
    ("https://tldr.tech/api/rss/ai", "TLDR AI", "IA"),
    ("https://simonwillison.net/atom/everything/", "Simon Willison", "IA"),
    ("https://blog.google/innovation-and-ai/technology/ai/rss/",
     "Google AI", "IA"),
    ("https://openai.com/news/rss.xml", "OpenAI", "IA"),
    ("https://the-decoder.com/feed/", "The Decoder", "IA"),
    ("https://www.bensbites.com/feed", "Ben's Bites", "IA"),
    ("https://petapixel.com/feed/", "PetaPixel", "Photo"),
    ("https://fstoppers.com/rss.xml", "Fstoppers", "Photo"),
    ("https://www.dpreview.com/feeds/news.xml", "DPReview", "Photo"),
    ("https://www.phototrend.fr/feed/", "Phototrend", "Photo"),
    ("https://tldr.tech/api/rss/tech", "TLDR Tech", "Tech"),
    ("https://next.ink/feed/", "Next", "Tech"),
    ("https://www.numerama.com/feed/", "Numerama", "Tech"),
    ("https://www.frandroid.com/feed", "Frandroid", "Tech"),
    ("https://www.01net.com/actualites/feed/", "01net", "Tech"),
    ("https://feeds.macrumors.com/MacRumors-All", "MacRumors", "Apple"),
    ("https://9to5mac.com/feed/", "9to5Mac", "Apple"),
    # Podcasts : pas de transcript complet disponible sur ces flux,
    # seulement les notes d'épisode écrites (retour user, déjà vérifié).
    ("https://feeds.acast.com/public/shows/64d7fb0db4d0da0010a2f09d",
     "Comptoir IA", "Podcasts"),
    ("https://feeds.acast.com/public/shows/"
     "43160adc-fadd-4764-b93f-aa1ca93f22bf", "Underscore_", "Podcasts"),
    ("https://feeds.simplecast.com/MdgHX7eu", "Tech&Co", "Podcasts"),
    ("https://feeds.simplecast.com/yRFCMe21", "Culture IA", "Podcasts"),
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


_IMG_RE = re.compile(r"""<img[^>]+src=["']([^"']+)""", re.I)


def _find_image(el, html):
    """Vignette : media:content/thumbnail, enclosure image, itunes:image,
    sinon première <img> du résumé HTML. "" si aucune."""
    for child in el.iter():
        tag = _local_tag(child)
        url = child.get("url") or child.get("href") or ""
        if (tag in ("content", "thumbnail", "image") and url
                and child.get("medium", "image") == "image"
                and not url.lower().endswith((".mp3", ".m4a", ".mp4"))):
            return url
        if (tag == "enclosure" and url
                and (child.get("type") or "").startswith("image")):
            return url
    match = _IMG_RE.search(html or "")
    return match.group(1) if match else ""


def _fetch_one(entry):
    url, source, category = entry
    try:
        # UA navigateur : certains sites refusent un UA inconnu.
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (Hub-Actus)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
    except Exception:
        # Un flux en panne ne doit pas casser toute la page — les autres
        # s'affichent quand même.
        return []

    root_tag = _local_tag(root)

    def _item(title, link, date, summary_html, el):
        return {"title": title, "link": link, "date": date,
                "summary": _strip_html(summary_html), "source": source,
                "category": category,
                "image": _find_image(el, summary_html)}

    # RSS 2.0 (ex. TLDR) : <rss><channel><item>...
    if root_tag == "rss":
        channel = root.find("channel")
        if channel is None:
            return []
        items = []
        for item in channel.findall("item")[:MAX_ITEMS_PER_FEED]:
            title = _strip_html(item.findtext("title") or "")
            link = (item.findtext("link") or "").strip()
            date = _parse_date(item.findtext("pubDate"))
            items.append(_item(title, link, date,
                               item.findtext("description") or "", item))
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
            summary = (entry_el.findtext("a:summary", "", ns)
                       or entry_el.findtext("a:content", "", ns) or "")
            items.append(_item(title, href.strip(), date, summary,
                               entry_el))
        return items

    return []


def fetch_all_feeds():
    with ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        results = list(pool.map(_fetch_one, FEEDS))
    items = [item for group in results for item in group]
    items.sort(key=lambda it: it["date"] or _MIN_DATE, reverse=True)
    return items


_BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def fetch_article_text(url):
    """Texte principal (Markdown + images) de l'article (trafilatura), "" si
    échec — site qui bloque (DPReview, OpenAI : 403) ou module absent.
    UA navigateur complet : PetaPixel refuse un UA court."""
    try:
        import trafilatura
        req = urllib.request.Request(url, headers={
            "User-Agent": _BROWSER_UA, "Accept": "text/html",
            "Accept-Language": "fr,en"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            # Markdown avec images (retour user), affiché par ft.Markdown.
            return trafilatura.extract(
                resp.read(), output_format="markdown",
                include_images=True, url=url) or ""
    except Exception:
        return ""
