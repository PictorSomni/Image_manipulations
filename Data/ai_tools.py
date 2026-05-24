# -*- coding: utf-8 -*-
"""
Utilitaires IA partagés entre Dashboard.pyw et SidePanel.pyw.

Fonctions exposées :
  _fetch_url_content(url, max_chars)         — récupère le texte d'une URL HTTP(S)
  _web_search(query, max_results)            — recherche DuckDuckGo, retourne les résultats formatés
  _ollama_chat_once(url, model, messages)    — appel non-streaming à /api/chat, retourne le dict message
  _ollama_chat_stream(url, model, messages)  — appel streaming à /api/chat, génère les tokens

  Outils dossier (partagés) :
  _folder_tool_definitions(folder_path)      — retourne les 4 définitions d'outils dossier pour Ollama
  _folder_list_contents(folder_path)         — liste les fichiers avec taille et date
  _folder_read_file(folder_path, filename)   — lit le contenu texte d'un fichier
  _encode_image_for_analysis(image_path)     — encode une image en base64 JPEG pour un modèle vision
  _analyze_images_batched(...)               — analyse des images par lots et retourne les résultats
"""

import json
import re
import urllib.request
import urllib.parse
import html.parser


class _HTMLTextExtractor(html.parser.HTMLParser):
    """Extrait le texte brut d'un document HTML en ignorant les balises de bruit."""
    # Balises dont tout le contenu est ignoré
    _SKIP_TAGS = {
        "script", "style", "noscript", "head",
        "nav", "header", "footer", "aside",
        "form", "button", "select", "option", "input", "textarea",
        "iframe", "figure", "figcaption", "picture",
        "dialog", "menu", "menuitem",
    }
    # Balises sémantiques de contenu principal (priorité si présentes)
    _CONTENT_TAGS = {"main", "article", "section"}

    def __init__(self):
        super().__init__()
        self._skip_depth   = 0
        self._content_depth = 0
        self._parts        = []
        self._content_parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag in self._CONTENT_TAGS:
            self._content_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._CONTENT_TAGS and self._content_depth > 0:
            self._content_depth -= 1

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if not stripped:
            return
        self._parts.append(stripped)
        if self._content_depth > 0:
            self._content_parts.append(stripped)

    def get_text(self):
        # Privilégier le contenu sémantique (main/article/section) si suffisant
        target = self._content_parts if len(self._content_parts) > 20 else self._parts
        return "\n".join(target)


def _fetch_url_content(url, max_chars=12_000):
    """
    Récupère le contenu textuel d'une URL HTTP(S).

    Retourne une chaîne tronquée à ``max_chars`` caractères,
    ou un message d'erreur si la récupération échoue.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ImageManipBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw_bytes = response.read()
        raw_text = raw_bytes.decode(charset, errors="replace")
        if "</" in raw_text or "<br" in raw_text.lower():
            extractor = _HTMLTextExtractor()
            extractor.feed(raw_text)
            plain_text = extractor.get_text()
        else:
            plain_text = raw_text
        plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()
        if len(plain_text) > max_chars:
            plain_text = plain_text[:max_chars] + f"\n\n[… contenu tronqué à {max_chars} caractères]"
        return plain_text
    except Exception as fetch_error:
        return f"[Impossible de récupérer l'URL : {fetch_error}]"


class _DDGResultsParser(html.parser.HTMLParser):
    """Parse les résultats de recherche de la page HTML DuckDuckGo."""

    def __init__(self):
        super().__init__()
        self._results   = []   # [{"title": ..., "url": ..., "snippet": ...}]
        self._capturing = None  # "title" | "snippet"
        self._current   = None
        self._buf       = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "a" and "result__a" in cls:
            self._current   = {"title": "", "url": a.get("href", ""), "snippet": ""}
            self._capturing = "title"
            self._buf       = []
        elif tag == "a" and "result__snippet" in cls:
            self._capturing = "snippet"
            self._buf       = []

    def handle_endtag(self, tag):
        if tag != "a" or self._capturing is None:
            return
        text = " ".join(self._buf).strip()
        if self._capturing == "title" and self._current:
            self._current["title"] = text
            self._results.append(self._current)
            self._current = None
        elif self._capturing == "snippet" and self._results:
            self._results[-1]["snippet"] = text
        self._capturing = None

    def handle_data(self, data):
        if self._capturing:
            s = data.strip()
            if s:
                self._buf.append(s)

    def get_results(self):
        return self._results


def _ollama_chat_once(ollama_url, model, messages, tools=None, temperature=0.7, keep_alive=-1, timeout=120):
    """
    Envoie un appel non-streaming à /api/chat d'Ollama.
    Retourne le dict ``message`` de la réponse (clés "content" et éventuellement "tool_calls").
    Lève une exception en cas d'erreur réseau ou HTTP.
    """
    body = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": True,
        "keep_alive": keep_alive,
        "options": {"temperature": temperature},
    }
    if tools:
        body["tools"] = tools
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result.get("message", {})


def _ollama_chat_stream(ollama_url, model, messages, temperature=0.7, keep_alive=-1, timeout=300):
    """
    Envoie un appel streaming à /api/chat d'Ollama.
    Génère les tokens (str) au fur et à mesure de leur réception.
    Lève une exception en cas d'erreur réseau ou HTTP.
    """
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "keep_alive": keep_alive,
        "options": {"temperature": temperature},
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            chunk = json.loads(raw_line.decode("utf-8"))
            token = chunk.get("message", {}).get("content", "")
            if token:
                yield token
            if chunk.get("done"):
                break


def _ollama_chat_stream_with_tools(ollama_url, model, messages, tools=None, temperature=0.7, keep_alive=-1, timeout=300):
    """
    Streaming /api/chat avec thinking natif Ollama (think: true) et capture des tool_calls.

    Génère des tuples :
      ("token",     str)  — token texte au fur et à mesure
      ("thinking",  str)  — token de réflexion (message.thinking, natif Ollama)
      ("tool_calls", list) — appels d'outils cumulés depuis tous les chunks
    """
    body = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": True,
        "keep_alive": keep_alive,
        "options": {"temperature": temperature},
    }
    if tools:
        body["tools"] = tools
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{ollama_url}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            chunk = json.loads(raw_line.decode("utf-8"))
            msg = chunk.get("message", {})
            thinking = msg.get("thinking", "")
            if thinking:
                yield ("thinking", thinking)
            token = msg.get("content", "")
            if token:
                yield ("token", token)
            tool_calls = msg.get("tool_calls") or []
            if tool_calls:
                yield ("tool_calls", tool_calls)
            if chunk.get("done"):
                break


def _parse_text_tool_calls(text):
    """
    Détecte les appels d'outils écrits en texte brut par le modèle (format de repli).

    Supporte deux formats émis par Gemma :
      <execute_tool> fn(key='val') </execute_tool>
      <|tool_call>call:fn{key:<|"|>val<|"|>}<tool_call|>

    Retourne une liste de dicts {"function": {"name": ..., "arguments": {...}}}
    compatibles avec le format tool_calls d'Ollama.
    """
    calls = []

    # Format 1 : <execute_tool> fn(key='value') </execute_tool>
    pat1 = re.compile(r'<execute_tool>\s*(\w+)\(([^)]*)\)\s*</execute_tool>',
                      re.IGNORECASE | re.DOTALL)
    for m in pat1.finditer(text):
        fn_name  = m.group(1)
        args_str = m.group(2)
        args = {}
        for kv in re.finditer(r'(\w+)\s*=\s*["\']([^"\']*)["\']', args_str):
            args[kv.group(1)] = kv.group(2)
        calls.append({"function": {"name": fn_name, "arguments": args}})

    # Format 2 (tokens natifs Gemma) : <|tool_call>call:fn{key:<|"|>val<|"|>}<tool_call|>
    pat2 = re.compile(r'<\|tool_call>call:(\w+)\{(.*?)\}<tool_call\|>', re.DOTALL)
    for m in pat2.finditer(text):
        fn_name  = m.group(1)
        args_str = m.group(2)
        args = {}
        for kv in re.finditer(r'(\w+):<\|"\|>(.*?)<\|"\|>', args_str, re.DOTALL):
            args[kv.group(1)] = kv.group(2)
        for kv in re.finditer(r'(\w+):([^,}]+)', args_str):
            key = kv.group(1)
            if key not in args:
                args[key] = kv.group(2).strip()
        calls.append({"function": {"name": fn_name, "arguments": args}})

    return calls


def _strip_text_tool_calls(text):
    """Supprime les blocs d'appels d'outils textuels du contenu."""
    text = re.sub(r'<execute_tool>.*?</execute_tool>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<\|tool_call>.*?<tool_call\|>', '', text, flags=re.DOTALL)
    return text.strip()


def _format_ai_conversation(conversation, user_name="Toi", separator_width=80):
    """
    Formate une liste de messages IA en texte Markdown exportable.

    Chaque tour est un bloc H1 avec le nom du rôle. Les blocs de réflexion
    (thinking) sont rendus en blockquote avant le contenu. Les blocs sont
    séparés par une ligne de tirets.

    Args:
        conversation : liste de dicts avec les clés 'role', 'content', 'thinking'.
        user_name    : nom affiché pour le rôle 'user'.

    Returns:
        Chaîne Markdown prête à être copiée ou insérée dans le bloc-notes.
    """
    blocks = []
    separator = "\n\n" + "#" * separator_width + "\n\n"
    for message in conversation:
        role = message.get("role", "")
        content = message.get("content", "")
        thinking = message.get("thinking", "")
        if role == "user":
            prefix = user_name
        elif role == "assistant":
            prefix = "IA"
        else:
            continue
        if thinking:
            thinking_lines = "\n".join(
                f"> {line}" if line.strip() else ">" for line in thinking.split("\n")
            )
            block = f"> 💭 **Réflexion**\n>\n{thinking_lines}\n\n# {prefix}\n\n{content.strip()}"
        else:
            block = f"# {prefix}\n\n{content.strip()}"
        blocks.append(block.strip())
    return separator.join(blocks).strip()


def _web_search(query, max_results=5):
    """
    Effectue une recherche sur DuckDuckGo et retourne les résultats formatés.

    Retourne une chaîne listant titres, URLs et extraits,
    ou un message d'erreur si la recherche échoue.
    """
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}&kl=fr-fr"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
        parser = _DDGResultsParser()
        parser.feed(raw_html)
        results = parser.get_results()[:max_results]
        if not results:
            return "[Aucun résultat trouvé]"
        lines = []
        for i, r in enumerate(results, 1):
            title   = r["title"]   or "(sans titre)"
            snippet = r["snippet"] or ""
            link    = r["url"]
            lines.append(f"{i}. **{title}**\n   {link}\n   {snippet}")
        return "\n\n".join(lines)
    except Exception as exc:
        return f"[Erreur de recherche web : {exc}]"


# ─── Outils dossier partagés ──────────────────────────────────────────────────
import os as _os
import datetime as _datetime_module

_FOLDER_DOCUMENT_EXTS_DEFAULT = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".xml",
    ".html", ".htm", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".rst", ".rtf",
})
_FOLDER_IMAGE_EXTS_DEFAULT = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".ico", ".tiff", ".tif",
})


def _folder_tool_definitions(folder_path):
    """
    Retourne la liste des 4 définitions d'outils dossier pour l'API Ollama
    (list_folder_contents, read_file_content, organize_files, analyze_images).
    Retourne [] si folder_path est None ou n'est pas un dossier valide.
    """
    if not folder_path or not _os.path.isdir(folder_path):
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "list_folder_contents",
                "description": (
                    "Liste tous les fichiers et sous-dossiers du dossier "
                    "actuellement ouvert, avec taille et date de modification."
                ),
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_content",
                "description": (
                    "Lit le contenu d'un fichier texte du dossier ouvert. "
                    "Extensions supportées : txt, md, py, js, json, csv, yaml…"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Nom du fichier à lire",
                        }
                    },
                    "required": ["filename"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "organize_files",
                "description": (
                    "Déplace des fichiers du dossier ouvert vers des sous-dossiers. "
                    "Une boîte de confirmation est présentée à l'utilisateur avant toute exécution. "
                    "IMPORTANT : utilise le dossier parent pour la catégorie générale "
                    "(ex. 'Audio' pour un fichier .mp3), et un sous-dossier imbriqué uniquement "
                    "pour les sous-catégories bien distinctes "
                    "(ex. 'Audio/Midi' pour les fichiers .mid/.midi). "
                    "Ne range pas un fichier générique dans un sous-dossier spécialisé."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "actions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "filename": {
                                        "type": "string",
                                        "description": "Nom du fichier à déplacer",
                                    },
                                    "destination_subfolder": {
                                        "type": "string",
                                        "description": (
                                            "Sous-dossier de destination (créé si absent). "
                                            "Peut être imbriqué avec '/' (ex. 'Audio/Midi'). "
                                            "Préférer le dossier parent pour les types généraux, "
                                            "les sous-dossiers pour les sous-catégories précises."
                                        ),
                                    },
                                },
                                "required": ["filename", "destination_subfolder"],
                            },
                            "description": "Liste des déplacements à effectuer",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Résumé de l'organisation proposée",
                        },
                    },
                    "required": ["actions"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "analyze_images",
                "description": (
                    "Analyse visuellement les images du dossier ouvert pour répondre "
                    "à une question. Exemples : trouver les personnes portant du rouge, "
                    "identifier les photos floues, décrire chaque image, "
                    "trouver les photos prises en extérieur."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filenames": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Liste des noms de fichiers images à analyser. "
                                "Laisser vide pour analyser toutes les images du dossier."
                            ),
                        },
                        "question": {
                            "type": "string",
                            "description": "Question visuelle à poser pour chaque image",
                        },
                    },
                    "required": ["question"],
                },
            },
        },
    ]


def _folder_list_contents(folder_path):
    """
    Retourne une chaîne listant fichiers et sous-dossiers avec taille et date.
    """
    try:
        scan_entries = sorted(
            _os.scandir(folder_path),
            key=lambda entry: (entry.is_file(), entry.name.lower()),
        )
        lines = [f"Dossier : {folder_path}", ""]
        for scan_entry in scan_entries:
            if scan_entry.is_dir():
                lines.append(f"  {scan_entry.name}/  [dossier]")
            else:
                scan_stat = scan_entry.stat()
                size_kb   = scan_stat.st_size / 1024
                size_str  = (
                    f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                )
                mtime_str = _datetime_module.datetime.fromtimestamp(
                    scan_stat.st_mtime
                ).strftime("%Y-%m-%d %H:%M")
                lines.append(f"  {scan_entry.name}  ({size_str}, {mtime_str})")
        return "\n".join(lines)
    except Exception as exc:
        return f"Erreur lors de la lecture du dossier : {exc}"


def _folder_read_file(folder_path, filename, document_exts=None, max_chars=20_000):
    """
    Lit le contenu texte d'un fichier du dossier.
    Retourne le contenu ou un message d'erreur.
    """
    if document_exts is None:
        document_exts = _FOLDER_DOCUMENT_EXTS_DEFAULT
    try:
        file_path = _os.path.join(folder_path, _os.path.basename(filename))
        if not _os.path.isfile(file_path):
            return f"Fichier introuvable : {filename}"
        if _os.path.splitext(filename)[1].lower() not in document_exts:
            return f"Type de fichier non lisible en texte : {filename}"
        with open(file_path, "r", encoding="utf-8", errors="replace") as file_handle:
            content = file_handle.read(max_chars)
        if len(content) == max_chars:
            content += f"\n… (tronqué à {max_chars:,} caractères)"
        return content
    except Exception as exc:
        return f"Erreur : {exc}"


def _encode_image_for_analysis(image_path, max_size=1024, quality=70):
    """
    Encode une image en JPEG base64 redimensionnée pour l'envoi à un modèle vision.
    Retourne la chaîne base64 ou None en cas d'échec.
    """
    try:
        import base64 as _base64
        import io as _io
        from PIL import Image as _PilImage, ImageOps as _PilImageOps
        with _PilImage.open(image_path) as pil_img:
            pil_img = _PilImageOps.exif_transpose(pil_img).convert("RGB")
            pil_img.thumbnail((max_size, max_size), _PilImage.LANCZOS)
            buffer = _io.BytesIO()
            pil_img.save(buffer, format="JPEG", quality=quality, optimize=True)
            return _base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        return None


def _analyze_images_batched(
    ollama_url,
    model,
    folder_path,
    filenames,
    question,
    batch_size=5,
    image_exts=None,
    max_size=1024,
    quality=70,
    on_progress=None,
    is_running=None,
):
    """
    Analyse visuellement une liste d'images par lots en posant une question à chaque lot.

    Paramètres :
      ollama_url  — URL de l'API Ollama (ex. "http://localhost:11434")
      model       — nom du modèle vision
      folder_path — chemin du dossier contenant les images
      filenames   — liste de noms de fichiers à analyser (liste vide = toutes les images)
      question    — question à poser pour chaque image
      batch_size  — nombre d'images par appel IA
      image_exts  — frozenset d'extensions images (défaut : _FOLDER_IMAGE_EXTS_DEFAULT)
      max_size    — résolution max des images encodées (px)
      quality     — qualité JPEG des images encodées
      on_progress — callback(batch_num, total_batches) appelé avant chaque lot
      is_running  — callable() → bool, interrompt la boucle si False (optionnel)

    Retourne une liste de chaînes de résultats (une par lot).
    """
    if image_exts is None:
        image_exts = _FOLDER_IMAGE_EXTS_DEFAULT
    if not filenames:
        try:
            filenames = sorted([
                entry.name for entry in _os.scandir(folder_path)
                if entry.is_file()
                and _os.path.splitext(entry.name)[1].lower() in image_exts
            ])
        except Exception:
            filenames = []

    total         = len(filenames)
    total_batches = (total + batch_size - 1) // batch_size if total else 0
    results       = []

    for batch_idx, batch_start in enumerate(range(0, total, batch_size)):
        if is_running is not None and not is_running():
            break
        batch_num   = batch_idx + 1
        batch_names = filenames[batch_start : batch_start + batch_size]
        if on_progress:
            on_progress(batch_num, total_batches)

        b64_list      = []
        encoded_names = []
        for fname in batch_names:
            b64 = _encode_image_for_analysis(
                _os.path.join(folder_path, fname),
                max_size=max_size,
                quality=quality,
            )
            if b64:
                b64_list.append(b64)
                encoded_names.append(fname)
        if not b64_list:
            continue

        prompt = (
            f"Question : {question}\n"
            f"Images de ce groupe ({len(encoded_names)}) : {', '.join(encoded_names)}.\n"
            "Pour chaque image, donne une réponse concise au format :\n"
            "NomFichier : réponse"
        )
        try:
            response = _ollama_chat_once(
                ollama_url,
                model,
                [{"role": "user", "content": prompt, "images": b64_list}],
                temperature=0.2,
            )
            results.append(response.get("content", ""))
        except Exception as exc:
            results.append(f"(lot {batch_num} — erreur : {exc})")

    return results
