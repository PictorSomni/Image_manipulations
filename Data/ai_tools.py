# -*- coding: utf-8 -*-
"""
Utilitaires IA partagés entre Dashboard.pyw et SidePanel.pyw.

Fonctions exposées :
  _fetch_url_content(url, max_chars)       — récupère le texte d'une URL HTTP(S)
  _web_search(query, max_results)          — recherche DuckDuckGo, retourne les résultats formatés
  _ollama_chat_once(url, model, messages)  — appel non-streaming à /api/chat, retourne le dict message
  _ollama_chat_stream(url, model, messages)— appel streaming à /api/chat, génère les tokens
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
