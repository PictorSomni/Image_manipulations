# -*- coding: utf-8 -*-
"""
Utilitaires IA partagés entre Dashboard.pyw et SidePanel.pyw.

Fonctions et constantes exposées :
  _fetch_url_content(url, max_chars)         — récupère le texte d'une URL HTTP(S)
  _web_search(query, max_results)            — recherche DuckDuckGo, retourne les résultats formatés
  _ollama_chat_once(url, model, messages)    — appel non-streaming à /api/chat, retourne le dict message
  _ollama_chat_stream(url, model, messages)  — appel streaming à /api/chat, génère les tokens

  Outils dossier (partagés) :
  _folder_tool_definitions(folder_path)      — retourne les 7 définitions d'outils dossier pour Ollama/Gemma
  _gemini_tool_definitions(folder_path)       — version allégée pour Gemini (sans analyze_images)
  _folder_list_contents(folder_path)         — liste les fichiers avec taille et date
  _folder_read_file(folder_path, filename)   — lit le contenu texte d'un fichier
  _folder_create_file(folder_path, filename, content)
                                             — crée un fichier texte dans le dossier ouvert
  _encode_image_for_analysis(image_path)     — encode une image en base64 JPEG pour un modèle vision
  _analyze_images_batched(...)               — analyse des images par lots et retourne les résultats
  _gemini_generate_image(prompt, ...)        — génère/modifie une image via Nano Banana 2

  Helpers système (partagés) :
  _WEB_TOOLS                                 — liste des 2 définitions d'outils web (web_search + fetch_url)
  _TERMINAL_TOOLS                            — définition de l'outil run_terminal_command
  _MEMORY_TOOLS                              — définition de l'outil update_memory_file
  _run_terminal_command(command, cwd, timeout)
                                             — exécute une commande shell et retourne la sortie
  _update_memory_file(target, action, content, old_text)
                                             — met à jour memory.md / user.md / skills.md (retourne JSON)
  _read_memory_file(target)                  — lit un fichier mémoire brut (str)
  _build_system_content(base_prompt, folder_path, today_date_str)
                                             — assemble le message système complet (system.md + mémoire + date + dossier)

    Voix — TTS :
  _gemini_tts(text, ...)                     — génère l'audio TTS en une seule requête (bytes PCM)
  _gemini_tts_stream(text, ...)              — TTS multi-requêtes pipeline (compatible tous modèles)
  _gemini_live_tts_stream(text, ...)         — TTS via Gemini Live WebSocket (voix cohérente, modèle Live)
  _voice_play_audio(pcm_bytes, ...)          — joue des bytes PCM via sounddevice
"""

import ast as _ast
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


def _get_gemini_api_key():
    """Tente de récupérer la clé d'API Gemini de façon extrêmement robuste sur Windows, macOS et Linux."""
    import os
    import re
    import subprocess
    
    # 1. Directement dans l'environnement
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
        
    # 2. Dans un fichier .env (relatif au dossier de l'app ou racine du dépôt)
    for env_dir in [os.getcwd(), os.path.dirname(os.path.abspath(__file__)), os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]:
        env_path = os.path.join(env_dir, ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip() and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            if k.strip() == "GEMINI_API_KEY":
                                key = v.strip().strip('"').strip("'")
                                if key:
                                    os.environ["GEMINI_API_KEY"] = key
                                    return key
            except Exception:
                pass

    # 3. macOS / Linux uniquement : charger depuis le login shell (pour .zshrc, .bashrc, .profile)
    if os.name != "nt":
        for shell in ["/bin/zsh", "/bin/bash"]:
            if os.path.exists(shell):
                try:
                    result = subprocess.run(
                        [shell, "-l", "-c", "echo $GEMINI_API_KEY"],
                        capture_output=True, text=True, timeout=2
                    )
                    key = result.stdout.strip()
                    if key:
                        os.environ["GEMINI_API_KEY"] = key
                        return key
                except Exception:
                    pass

        # Fallback : lecture directe des fichiers RC de l'utilisateur
        home = os.path.expanduser("~")
        for rc_file in [".zshrc", ".bashrc", ".bash_profile", ".profile"]:
            rc_path = os.path.join(home, rc_file)
            if os.path.isfile(rc_path):
                try:
                    with open(rc_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    # match "export GEMINI_API_KEY=xxx" or "GEMINI_API_KEY=xxx"
                    match = re.search(r'(?:export\s+)?GEMINI_API_KEY\s*=\s*["\']?(.*?)["\']?\s*(?:#|$)', content)
                    if match:
                        key = match.group(1).strip()
                        if key:
                            os.environ["GEMINI_API_KEY"] = key
                            return key
                except Exception:
                    pass
                    
    return ""


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


def _eval_str_node(node):
    """Évalue un nœud AST en chaîne (littéral ou concaténation de littéraux)."""
    if isinstance(node, _ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, _ast.BinOp) and isinstance(node.op, _ast.Add):
        left = _eval_str_node(node.left)
        right = _eval_str_node(node.right)
        if left is not None and right is not None:
            return left + right
    return None


def _parse_text_tool_calls(text):
    """
    Détecte les appels d'outils écrits en texte brut par le modèle (format de repli).

    Supporte trois formats émis par Gemma :
      <execute_tool> fn(key='val') </execute_tool>
      <|tool_call>call:fn{key:<|"|>val<|"|>}<tool_call|>
      <tool_code>print(obj.fn(key="val"))</tool_code>  — style Google/Gemma

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

    # Format 3 : <tool_code>print(obj.fn(key="val"))</tool_code> — style Google/Gemma
    _GEMMA_FN_ALIASES = {
        "write_file":       "create_file",
        "update_file":      "create_file",
        "save_file":        "create_file",
        "create_text_file": "create_file",
    }
    _GEMMA_PARAM_ALIASES = {
        "create_file": {
            "file_name":    "filename",
            "file_content": "content",
            "file_path":    "filename",
            "path":         "filename",
        },
        "read_file_content": {
            "file_name": "filename",
            "file_path": "filename",
            "path":      "filename",
        },
    }
    pat3 = re.compile(r'<tool_code>(.*?)</tool_code>', re.DOTALL | re.IGNORECASE)
    for m in pat3.finditer(text):
        code_block = m.group(1).strip()
        try:
            tree = _ast.parse(code_block, mode='eval')
            call_node = tree.body
            # Déballer print(...) si présent
            if (
                isinstance(call_node, _ast.Call)
                and isinstance(call_node.func, _ast.Name)
                and call_node.func.id == 'print'
                and call_node.args
            ):
                call_node = call_node.args[0]
            # obj.fn_name(...)
            if isinstance(call_node, _ast.Call) and isinstance(call_node.func, _ast.Attribute):
                fn_name = call_node.func.attr
                # Normaliser le nom de fonction (ex. write_file → create_file)
                fn_name = _GEMMA_FN_ALIASES.get(fn_name, fn_name)
                args = {}
                for kw in call_node.keywords:
                    if not kw.arg:
                        continue
                    # Essayer concaténation de chaînes d'abord, puis literal_eval
                    arg_val = _eval_str_node(kw.value)
                    if arg_val is None:
                        try:
                            arg_val = _ast.literal_eval(kw.value)
                        except Exception:
                            arg_val = None
                    if arg_val is not None:
                        args[kw.arg] = arg_val
                # Normaliser les noms de paramètres Gemma → noms de nos outils
                aliases = _GEMMA_PARAM_ALIASES.get(fn_name, {})
                for gemma_key, our_key in aliases.items():
                    if gemma_key in args:
                        args[our_key] = args.pop(gemma_key)
                if fn_name:  # args peut être vide (ex. list_folder_contents())
                    calls.append({"function": {"name": fn_name, "arguments": args}})
        except (SyntaxError, ValueError, AttributeError):
            # Fallback regex pour les blocs avec chaînes multi-lignes
            # (ast.parse échoue si le contenu contient de vraies newlines)
            _fb_match = re.search(
                r'(?:print\s*\(\s*)?(?:\w+\.)?(\w+)\s*\(', code_block
            )
            if _fb_match:
                _fb_fn = _fb_match.group(1)
                if _fb_fn == "print":
                    _inner_match = re.search(
                        r'print\s*\(\s*(?:\w+\.)?(\w+)\s*\(', code_block
                    )
                    _fb_fn = _inner_match.group(1) if _inner_match else ""
                # Normaliser le nom de fonction (ex. write_file → create_file)
                _fb_fn = _GEMMA_FN_ALIASES.get(_fb_fn, _fb_fn)
                _fb_args = {}
                for _kv in re.finditer(
                    r'(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', code_block, re.DOTALL
                ):
                    _fb_args[_kv.group(1)] = (
                        _kv.group(2)
                        .replace('\\n', '\n').replace('\\t', '\t')
                        .replace('\\\\', '\\').replace('\\"', '"')
                    )
                for _kv in re.finditer(
                    r"(\w+)\s*=\s*'((?:[^'\\]|\\.)*)'", code_block, re.DOTALL
                ):
                    if _kv.group(1) not in _fb_args:
                        _fb_args[_kv.group(1)] = (
                            _kv.group(2)
                            .replace('\\n', '\n').replace('\\t', '\t')
                            .replace('\\\\', '\\').replace("\\'", "'")
                        )
                _fb_aliases = _GEMMA_PARAM_ALIASES.get(_fb_fn, {})
                for _gk, _ok in _fb_aliases.items():
                    if _gk in _fb_args:
                        _fb_args[_ok] = _fb_args.pop(_gk)
                if _fb_fn:
                    calls.append({"function": {"name": _fb_fn, "arguments": _fb_args}})

    return calls


def _strip_text_tool_calls(text):
    """Supprime les blocs d'appels d'outils textuels du contenu."""
    text = re.sub(r'<execute_tool>.*?</execute_tool>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<\|tool_call>.*?<tool_call\|>', '', text, flags=re.DOTALL)
    text = re.sub(r'<tool_code>.*?</tool_code>', '', text,
                  flags=re.IGNORECASE | re.DOTALL)
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
        events = message.get("events", [])
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
            block = f"> 💭 **Réflexion**\n>\n{thinking_lines}\n\n# {prefix}\n\n"
        else:
            block = f"# {prefix}\n\n"
        if events:
            events_text = "\n".join(f"  • {e}" for e in events)
            block += f"**Actions :**\n{events_text}\n\n"
        block += content.strip()
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
        # Autoriser la génération d'image même sans dossier ouvert :
        # le Dashboard sauvegarde alors dans app_directory/Generated.
        return [
            {
                "type": "function",
                "function": {
                    "name": "generate_image",
                    "description": (
                        "Génère une image à partir d'un prompt texte avec Nano Banana 2 "
                        "(gemini-3.1-flash-image-preview). "
                        "L'image est sauvegardée et affichée dans le chat. "
                        "Utilise cet outil quand l'utilisateur demande de créer, dessiner ou générer une image."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "prompt": {
                                "type": "string",
                                "description": (
                                    "Description détaillée de l'image à générer. "
                                    "Plus la description est précise, meilleur est le résultat."
                                ),
                            },
                            "filename": {
                                "type": "string",
                                "description": (
                                    "Nom du fichier de sortie (ex. 'portrait.png'). "
                                    "Laisser vide pour nommer automatiquement."
                                ),
                            },
                            "aspect_ratio": {
                                "type": "string",
                                "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
                                "description": "Format de l'image. Défaut : 1:1.",
                            },
                        },
                        "required": ["prompt"],
                    },
                },
            },
        ]
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
                "name": "create_file",
                "description": (
                    "Crée ou écrase un fichier dans le dossier ouvert avec le contenu fourni. "
                    "Fonctionne aussi pour modifier un fichier existant : lire son contenu "
                    "avec read_file_content, modifier le texte en mémoire, puis appeler "
                    "create_file avec le même nom de fichier et le nouveau contenu complet. "
                    "Idéal pour générer des scripts (.py, .sh, .bat), des notes (.txt, .md), "
                    "des fichiers de configuration, ou tout autre fichier texte. "
                    "IMPORTANT : le paramètre 'filename' est obligatoire. "
                    "Le contenu doit être basé uniquement sur les données réelles "
                    "obtenues des outils précédents — ne pas inventer de données. "
                    "Le paramètre 'content' doit contenir UNIQUEMENT le contenu du fichier, "
                    "sans aucun message conversationnel, question ou commentaire destiné à l'utilisateur."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Nom du fichier à créer (ex. script.py, notes.txt)",
                        },
                        "content": {
                            "type": "string",
                            "description": "Contenu textuel complet du fichier",
                        },
                    },
                    "required": ["filename", "content"],
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
                    "trouver les photos prises en extérieur. "
                    "N'utilise PAS cet outil si l'image est déjà jointe directement "
                    "dans le message de l'utilisateur — réponds directement à partir de cette image."
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
        {
            "type": "function",
            "function": {
                "name": "generate_image",
                "description": (
                    "Génère une image à partir d'un prompt texte avec Nano Banana 2 "
                    "(gemini-3.1-flash-image-preview). "
                    "L'image est sauvegardée dans le dossier ouvert et affichée dans le chat. "
                    "Utilise cet outil quand l'utilisateur demande de créer, dessiner ou générer une image."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Description détaillée de l'image à générer. "
                                "Plus la description est précise, meilleur est le résultat."
                            ),
                        },
                        "filename": {
                            "type": "string",
                            "description": (
                                "Nom du fichier de sortie (ex. 'portrait.png'). "
                                "Laisser vide pour nommer automatiquement."
                            ),
                        },
                        "aspect_ratio": {
                            "type": "string",
                            "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
                            "description": "Format de l'image. Défaut : 1:1.",
                        },
                    },
                    "required": ["prompt"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_image",
                "description": (
                    "Modifie une image existante du dossier ouvert avec un prompt texte "
                    "via Nano Banana 2 (gemini-3.1-flash-image-preview). "
                    "Idéal pour : changer le style, ajouter/supprimer des éléments, "
                    "changer les couleurs, transformer une photo en illustration. "
                    "L'image modifiée est sauvegardée dans le dossier ouvert."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source_filename": {
                            "type": "string",
                            "description": "Nom du fichier image source à modifier (dans le dossier ouvert).",
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Instructions de modification, ex. : "
                                "'Transforme en style aquarelle', "
                                "'Remplace le fond par un coucher de soleil'."
                            ),
                        },
                        "output_filename": {
                            "type": "string",
                            "description": (
                                "Nom du fichier de sortie (ex. 'photo_aquarelle.png'). "
                                "Laisser vide pour nommer automatiquement."
                            ),
                        },
                        "aspect_ratio": {
                            "type": "string",
                            "enum": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
                            "description": "Format de sortie. Défaut : même que l'original.",
                        },
                    },
                    "required": ["source_filename", "prompt"],
                },
            },
        },
    ]


def _gemini_tool_definitions(folder_path):
    """
    Retourne tous les outils dossier pour Gemini, y compris analyze_images.
    Les outils web (web_search, fetch_url) sont filtrés dans
    _gemini_chat_stream_with_tools et remplacés par google_search natif.
    """
    return _folder_tool_definitions(folder_path)


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


def _folder_create_file(folder_path, filename, content):
    """
    Crée un fichier texte dans le dossier ouvert avec le contenu fourni.
    Retourne un message de succès ou d'erreur.
    """
    try:
        safe_name = _os.path.basename(filename)
        if not safe_name:
            return "Nom de fichier invalide."
        file_path = _os.path.join(folder_path, safe_name)
        with open(file_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(content)
        return f"Fichier créé : {safe_name} ({len(content)} caractère(s))"
    except Exception as exc:
        return f"Erreur lors de la création du fichier : {exc}"


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
            if model.startswith("gemini"):
                from google import genai as _genai_ab
                from google.genai import types as _gtypes_ab
                import base64 as _b64_ab
                _client_ab = _genai_ab.Client()
                _parts_ab = [
                    _gtypes_ab.Part.from_bytes(
                        data=_b64_ab.b64decode(b64), mime_type="image/jpeg"
                    )
                    for b64 in b64_list
                ]
                _parts_ab.append(_gtypes_ab.Part(text=prompt))
                _resp_ab = _client_ab.models.generate_content(
                    model=model,
                    contents=[_gtypes_ab.Content(role="user", parts=_parts_ab)],
                    config=_gtypes_ab.GenerateContentConfig(temperature=0.2),
                )
                results.append(_resp_ab.text or "")
            else:
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


# ─── Outils terminal partagés ───────────────────────────────────────────────
import subprocess as _subprocess


def _run_terminal_command(command, cwd=None, timeout=60):
    """
    Exécute une commande shell et retourne la sortie combinée stdout + stderr.
    cwd : répertoire de travail (dossier ouvert si fourni).
    """
    try:
        result = _subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
        )
        output = result.stdout
        if result.stderr:
            output += ("\n" if output else "") + result.stderr
        output = output.strip()
        if not output:
            output = f"(Commande exécutée, code de retour : {result.returncode})"
        elif result.returncode != 0:
            output += f"\n(Code de retour : {result.returncode})"
        return output
    except _subprocess.TimeoutExpired:
        return f"[Timeout : la commande a dépassé {timeout} secondes]"
    except Exception as exc:
        return f"[Erreur d'exécution : {exc}]"


_TERMINAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_terminal_command",
            "description": (
                "Exécute une commande shell sur la machine locale. "
                "Utile pour installer des paquets, lancer des scripts, "
                "convertir des formats, lancer des processus, etc. "
                "NE PAS utiliser pour lister le contenu d'un dossier "
                "(utiliser list_folder_contents à la place) ni pour créer un fichier texte "
                "(utiliser create_file à la place). "
                "Une confirmation est toujours demandée à l'utilisateur avant exécution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Commande shell à exécuter",
                    },
                    "description": {
                        "type": "string",
                        "description": "Explication courte de ce que fait la commande",
                    },
                },
                "required": ["command"],
            },
        },
    },
]


# ─── Outils web partagés ──────────────────────────────────────────────────────

_WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Recherche des informations récentes sur internet via DuckDuckGo. "
                "À utiliser pour les actualités, événements récents, prix, météo, "
                "ou toute information susceptible d'avoir changé depuis la date d'entraînement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Requête de recherche",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": (
                "Lit le contenu textuel d'une page web à partir de son URL. "
                "À utiliser pour approfondir un résultat de recherche ou consulter "
                "une page spécifique."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL complète (https://…) de la page à lire",
                    }
                },
                "required": ["url"],
            },
        },
    },
]


# ─── Système de mémoire persistante ─────────────────────────────────────────

_DATA_DIR = _os.path.dirname(_os.path.abspath(__file__))

_MEMORY_CHAR_LIMITS = {
    "memory": 2200,
    "user":   1375,
    "skills": 3000,
}

_MEMORY_FILE_NAMES = {
    "memory": "memory.md",
    "user":   "user.md",
    "skills": "skills.md",
}


def _memory_file_path(target):
    return _os.path.join(_DATA_DIR, _MEMORY_FILE_NAMES[target])


def _read_memory_file(target):
    """Lit un fichier mémoire, retourne le contenu brut (chaîne vide si absent)."""
    try:
        with open(_memory_file_path(target), encoding="utf-8") as file_handle:
            return file_handle.read()
    except (FileNotFoundError, OSError):
        return ""


def _update_memory_file(target, action, content="", old_text=""):
    """
    Met à jour un fichier mémoire persistant (memory.md, user.md, skills.md).

    Actions :
        add     — ajoute une nouvelle entrée (séparée par §)
        replace — remplace l'entrée contenant old_text par content
        remove  — supprime l'entrée contenant old_text

    Retourne une chaîne JSON avec success, message et usage.
    """
    if target not in _MEMORY_CHAR_LIMITS:
        return json.dumps({
            "success": False,
            "error": f"Cible invalide : {target!r}. Utilise 'memory', 'user' ou 'skills'.",
        })

    file_path = _memory_file_path(target)
    char_limit = _MEMORY_CHAR_LIMITS[target]

    try:
        with open(file_path, encoding="utf-8") as file_handle:
            raw_content = file_handle.read()
    except FileNotFoundError:
        raw_content = ""
    except OSError as error:
        return json.dumps({"success": False, "error": str(error)})

    # Séparer les lignes de commentaires HTML du corps
    all_lines = raw_content.splitlines()
    comment_lines = [line for line in all_lines if line.startswith("<!--")]
    header = ("\n".join(comment_lines) + "\n") if comment_lines else ""
    body_lines = [line for line in all_lines if not line.startswith("<!--")]
    body = "\n".join(body_lines).strip()
    entries = [entry.strip() for entry in body.split("§") if entry.strip()]

    if action == "add":
        if not content.strip():
            return json.dumps({"success": False, "error": "content est vide."})
        new_entry = content.strip()
        if new_entry in entries:
            return json.dumps({"success": True, "note": "Entrée déjà présente, aucun doublon ajouté."})
        candidate_entries = entries + [new_entry]
        candidate_body = " §\n".join(candidate_entries)
        candidate_full = header + candidate_body
        if len(candidate_full) > char_limit:
            _entry_sep = " §\n"
            current_usage = f"{len(header + _entry_sep.join(entries))}/{char_limit}"
            return json.dumps({
                "success": False,
                "error": (
                    f"Mémoire à {current_usage} chars. "
                    f"Ajouter cette entrée ({len(new_entry)} chars) dépasserait la limite. "
                    "Consolide ou supprime des entrées existantes d'abord."
                ),
                "current_entries": entries,
                "usage": current_usage,
            })
        entries = candidate_entries

    elif action == "replace":
        if not old_text.strip():
            return json.dumps({"success": False, "error": "old_text est requis pour 'replace'."})
        matching_indices = [index for index, entry in enumerate(entries) if old_text.strip() in entry]
        if not matching_indices:
            return json.dumps({
                "success": False,
                "error": f"Aucune entrée ne contient : {old_text!r}",
                "current_entries": entries,
            })
        if len(matching_indices) > 1:
            return json.dumps({
                "success": False,
                "error": f"old_text ambigu : {len(matching_indices)} entrées correspondent. Précise davantage.",
                "matches": [entries[index] for index in matching_indices],
            })
        entries[matching_indices[0]] = content.strip()
        candidate_body = " §\n".join(entries)
        candidate_full = header + candidate_body
        if len(candidate_full) > char_limit:
            return json.dumps({
                "success": False,
                "error": f"Contenu trop long après remplacement ({len(candidate_full)}/{char_limit} chars).",
            })

    elif action == "remove":
        if not old_text.strip():
            return json.dumps({"success": False, "error": "old_text est requis pour 'remove'."})
        matching_indices = [index for index, entry in enumerate(entries) if old_text.strip() in entry]
        if not matching_indices:
            return json.dumps({
                "success": False,
                "error": f"Aucune entrée ne contient : {old_text!r}",
                "current_entries": entries,
            })
        if len(matching_indices) > 1:
            return json.dumps({
                "success": False,
                "error": f"old_text ambigu : {len(matching_indices)} entrées correspondent.",
                "matches": [entries[index] for index in matching_indices],
            })
        entries.pop(matching_indices[0])

    else:
        return json.dumps({
            "success": False,
            "error": f"Action invalide : {action!r}. Utilise 'add', 'replace' ou 'remove'.",
        })

    new_body = " §\n".join(entries)
    new_full = header + new_body
    try:
        with open(file_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(new_full)
    except OSError as error:
        return json.dumps({"success": False, "error": str(error)})

    usage = f"{len(new_full)}/{char_limit}"
    return json.dumps({
        "success": True,
        "action": action,
        "target": target,
        "entries_count": len(entries),
        "usage": usage,
    })


# ─── Outil mémoire persistante ────────────────────────────────────────────────

_MEMORY_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "update_memory_file",
            "description": (
                "Met à jour ta mémoire persistante entre les sessions. "
                "Utilise cet outil proactivement quand tu apprends quelque chose d'important sur "
                "l'utilisateur, son environnement, ses préférences ou une procédure utile.\n"
                "Cibles :\n"
                "  - 'memory' : tes notes personnelles (environnement, conventions, leçons apprises) — 2 200 chars max\n"
                "  - 'user'   : profil utilisateur (préférences, habitudes, style de communication) — 1 375 chars max\n"
                "  - 'skills' : procédures et techniques apprises (étapes, commandes, workflows) — 3 000 chars max\n"
                "Actions :\n"
                "  - 'add'     : ajoute une nouvelle entrée\n"
                "  - 'replace' : remplace l'entrée contenant old_text par content\n"
                "  - 'remove'  : supprime l'entrée contenant old_text"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["memory", "user", "skills"],
                        "description": "Fichier cible : 'memory', 'user' ou 'skills'",
                    },
                    "action": {
                        "type": "string",
                        "enum": ["add", "replace", "remove"],
                        "description": "Action à effectuer",
                    },
                    "content": {
                        "type": "string",
                        "description": "Contenu de la nouvelle entrée (requis pour 'add' et 'replace')",
                    },
                    "old_text": {
                        "type": "string",
                        "description": (
                            "Sous-chaîne unique identifiant l'entrée à remplacer ou supprimer "
                            "(requis pour 'replace' et 'remove')"
                        ),
                    },
                },
                "required": ["target", "action"],
            },
        },
    },
]


def _build_system_content(base_prompt, folder_path=None, today_date_str=None):
    """
    Assemble le contenu complet du message système envoyé à l'IA.

    Lit system.md si disponible (sinon utilise base_prompt comme fallback).
    Injecte ensuite memory.md, user.md, skills.md avec indicateurs d'utilisation.
    Ajoute la date du jour et le contexte du dossier ouvert.

    Args:
        base_prompt     : prompt de base (str), utilisé si system.md est absent.
        folder_path     : chemin absolu du dossier ouvert, ou None.
        today_date_str  : date du jour pré-formatée (ex. "25 mai 2026"), ou None.

    Returns:
        Chaîne complète prête à être passée comme message système.
    """
    # ── Prompt système de base ────────────────────────────────────────────────
    system_md_path = _os.path.join(_DATA_DIR, "system.md")
    if _os.path.exists(system_md_path):
        try:
            with open(system_md_path, encoding="utf-8") as file_handle:
                system_content = file_handle.read().strip()
        except OSError:
            system_content = base_prompt
    else:
        system_content = base_prompt

    # ── Fichiers mémoire persistante ──────────────────────────────────────────
    _memory_label_map = {
        "memory": "MÉMOIRE (notes personnelles)",
        "user":   "PROFIL UTILISATEUR",
        "skills": "SKILLS (procédures apprises)",
    }

    for target in ("memory", "user", "skills"):
        raw = _read_memory_file(target)
        all_lines = raw.splitlines()
        body_lines = [line for line in all_lines if not line.startswith("<!--")]
        body = "\n".join(body_lines).strip()
        entries = [entry.strip() for entry in body.split("§") if entry.strip()]
        if not entries:
            continue
        char_limit = _MEMORY_CHAR_LIMITS[target]
        char_count = len(raw)
        pct = int(char_count * 100 / char_limit)
        label = _memory_label_map[target]
        separator = "═" * 46
        content_str = " §\n".join(entries)
        system_content += f"\n\n{separator}\n{label} [{pct}% — {char_count}/{char_limit} chars]\n{separator}\n{content_str}"

    # ── Date du jour ──────────────────────────────────────────────────────────
    if today_date_str:
        system_content += f"\n\nDate du jour : {today_date_str}."

    # ── Contexte du dossier ouvert ────────────────────────────────────────────
    if folder_path and _os.path.isdir(folder_path):
        folder_name = _os.path.basename(folder_path)
        system_content += (
            f"\n\nDOSSIER OUVERT : « {folder_name} » (`{folder_path}`).\n"
            "Outils disponibles pour ce dossier : list_folder_contents, "
            "read_file_content, organize_files, analyze_images, create_file, "
            "generate_image, edit_image.\n"
            "Utilise-les quand l'utilisateur te demande d'explorer, résumer, "
            "organiser ou analyser visuellement le contenu de ce dossier. "
            "Pour toute question sur ce que contiennent les images "
            "(couleurs, personnes, lieux, objets…), utilise analyze_images. "
            "Pour générer une nouvelle image depuis un prompt texte, utilise generate_image. "
            "Pour modifier une image existante du dossier, utilise edit_image. "
            "RÈGLE ABSOLUE : pour lister le contenu du dossier, utilise TOUJOURS "
            "list_folder_contents — JAMAIS ls, find ou toute autre commande shell via run_terminal_command. "
            "Pour créer un fichier (script, note, liste, config…), utilise TOUJOURS create_file — "
            "JAMAIS run_terminal_command avec une redirection (>, tee, etc.). "
            "Le paramètre 'content' doit contenir UNIQUEMENT le texte final du fichier, "
            "recopié mot pour mot depuis les résultats des outils — "
            "sans aucun raisonnement, auto-correction, note entre parenthèses ou placeholder."
        )
    system_content += (
        "\n\nOutil terminal disponible : run_terminal_command. "
        "Utilise-le pour exécuter des commandes shell si l'utilisateur le demande "
        "(installation de paquets, conversion de fichiers, scripts, etc.). "
        "NE PAS l'utiliser pour lister des fichiers ou créer des fichiers texte : "
        "utilise list_folder_contents et create_file pour ça. "
        "Une confirmation sera toujours demandée avant exécution."
    )
    return system_content


# ─── Intégration Google Gemini ───────────────────────────────────────────────

def _format_gemini_error(exc, *, prefix="Erreur Gemini"):
    """Rend les erreurs Gemini plus lisibles sans masquer le message brut."""
    import re as _re_ge

    raw = str(exc).strip()
    compact = " ".join(raw.split())
    details = []

    if "429" in compact or "RESOURCE_EXHAUSTED" in compact:
        details.append("quota/rate limit Google atteint")
    elif "503" in compact or "UNAVAILABLE" in compact:
        details.append("service Google temporairement indisponible")

    retry_match = _re_ge.search(r'retryDelay[^0-9]*(\d+(?:\.\d+)?)', compact)
    if retry_match:
        details.append(f"retryDelay={retry_match.group(1)}s")

    if "GenerateContentResponse" in compact:
        compact = compact.split("GenerateContentResponse", 1)[0].strip(" :-")

    suffix = f" ({', '.join(details)})" if details else ""
    if compact:
        return f"[{prefix}{suffix} : {compact}]"
    return f"[{prefix}{suffix}]"


def _extract_gemini_feedback_messages(response):
    """Extrait les signaux de blocage/arrêt Gemini (prompt_feedback, safety, finish_reason)."""
    messages = []

    def _normalize_enum_name(value):
        raw = str(value).strip()
        if not raw:
            return ""
        if "." in raw:
            raw = raw.split(".")[-1]
        return raw.upper()

    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        block_msg = getattr(prompt_feedback, "block_reason_message", None) or getattr(prompt_feedback, "message", None)
        if block_reason and str(block_reason) not in {"BLOCK_REASON_UNSPECIFIED", "0"}:
            messages.append(f"Prompt bloqué ({block_reason})")
        if block_msg:
            messages.append(str(block_msg).strip())

    for cand in (getattr(response, "candidates", None) or []):
        finish_reason = getattr(cand, "finish_reason", None)
        finish_name = _normalize_enum_name(finish_reason) if finish_reason else ""
        if finish_name and finish_name not in {"STOP", "FINISH_REASON_UNSPECIFIED", "UNSPECIFIED", "0"}:
            messages.append(f"Arrêt modèle : {finish_reason}")

        for rating in (getattr(cand, "safety_ratings", None) or []):
            blocked = getattr(rating, "blocked", False)
            if blocked:
                category = getattr(rating, "category", "UNKNOWN")
                probability = getattr(rating, "probability", "UNKNOWN")
                messages.append(f"Blocage sécurité : {category} ({probability})")

    # Dédupliquer en conservant l'ordre
    deduped = []
    seen = set()
    for msg in messages:
        key = msg.strip()
        if key and key not in seen:
            deduped.append(key)
            seen.add(key)
    return deduped

def _ollama_tools_to_gemini(tools):
    """
    Convertit une liste de définitions d'outils au format Ollama (JSON Schema)
    en un seul objet types.Tool Gemini contenant les FunctionDeclaration.
    Retourne None si la liste est vide.
    """
    if not tools:
        return None
    try:
        from google.genai import types as _gtypes
    except ImportError:
        return None

    def _convert_schema(schema, _gtypes):
        """Convertit récursivement un JSON Schema dict en types.Schema Gemini."""
        raw_type = schema.get("type", "string").upper()
        prop_type = getattr(_gtypes.Type, raw_type, _gtypes.Type.STRING)
        kwargs = {
            "type": prop_type,
            "description": schema.get("description", ""),
        }
        if "enum" in schema:
            kwargs["enum"] = schema["enum"]
        # Tableaux : items obligatoire pour Gemini
        if prop_type == _gtypes.Type.ARRAY and "items" in schema:
            kwargs["items"] = _convert_schema(schema["items"], _gtypes)
        # Objets imbriqués
        if prop_type == _gtypes.Type.OBJECT and "properties" in schema:
            kwargs["properties"] = {
                k: _convert_schema(v, _gtypes)
                for k, v in schema["properties"].items()
            }
            if "required" in schema:
                kwargs["required"] = schema["required"]
        return _gtypes.Schema(**kwargs)

    declarations = []
    for tool in tools:
        fn = tool.get("function", {})
        params = fn.get("parameters", {})
        properties = {
            prop_name: _convert_schema(schema, _gtypes)
            for prop_name, schema in params.get("properties", {}).items()
        }
        gemini_params = _gtypes.Schema(
            type=_gtypes.Type.OBJECT,
            properties=properties,
            required=params.get("required", []),
        )
        declarations.append(_gtypes.FunctionDeclaration(
            name=fn.get("name", ""),
            description=fn.get("description", ""),
            parameters=gemini_params,
        ))
    return _gtypes.Tool(function_declarations=declarations)


def _ollama_messages_to_gemini(messages):
    """
    Convertit une liste de messages au format Ollama en :
      (system_instruction_str_or_None, [types.Content, ...])
    Gère : texte, images base64 (clé 'images'), PDFs base64 (clé 'pdfs'),
    tool_calls (role assistant) et résultats d'outils (role 'tool').
    """
    try:
        import base64 as _b64
        from google.genai import types as _gtypes
    except ImportError:
        return None, []

    system_instr = None
    gemini_contents = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            system_instr = content if isinstance(content, str) else ""
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts = []

        # Contenu textuel
        if isinstance(content, str) and content:
            parts.append(_gtypes.Part(text=content))
        elif isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and item.get("text"):
                    parts.append(_gtypes.Part(text=item["text"]))
                elif item.get("type") == "image_url":
                    url = (item.get("image_url") or {}).get("url", "")
                    if url.startswith("data:") and "," in url:
                        header, b64_data = url.split(",", 1)
                        mime_type = header.split(":")[1].split(";")[0]
                        try:
                            parts.append(_gtypes.Part.from_bytes(
                                data=_b64.b64decode(b64_data),
                                mime_type=mime_type,
                            ))
                        except Exception:
                            pass

        # Images base64 (format Ollama : liste de chaînes b64 JPEG)
        for b64_img in msg.get("images", []):
            try:
                parts.append(_gtypes.Part.from_bytes(
                    data=_b64.b64decode(b64_img),
                    mime_type="image/jpeg",
                ))
            except Exception:
                pass

        # PDFs base64 (format étendu : clé 'pdfs', liste de chaînes b64)
        for b64_pdf in msg.get("pdfs", []):
            try:
                parts.append(_gtypes.Part.from_bytes(
                    data=_b64.b64decode(b64_pdf),
                    mime_type="application/pdf",
                ))
            except Exception:
                pass

        # Appels d'outils (rôle assistant)
        if role == "assistant":
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                parts.append(_gtypes.Part.from_function_call(
                    name=fn.get("name", ""),
                    args=args,
                ))

        # Résultats d'outils (rôle 'tool')
        if role == "tool":
            tool_name = msg.get("tool_name") or msg.get("name") or "tool_result"
            result_text = content if isinstance(content, str) else json.dumps(content)
            parts.append(_gtypes.Part.from_function_response(
                name=tool_name,
                response={"result": result_text},
            ))
            gemini_role = "user"

        if parts:
            gemini_contents.append(_gtypes.Content(role=gemini_role, parts=parts))

    return system_instr, gemini_contents


def _gemini_chat_stream_with_tools(model, messages, tools=None, temperature=0.7):
    """
    Version Gemini de _ollama_chat_stream_with_tools.
    Génère les mêmes tuples : ("token", str), ("thinking", str), ("tool_calls", list).

    tool_calls est une liste d'éléments compatibles format Ollama :
      [{"function": {"name": str, "arguments": dict}}, ...]

    Nécessite GEMINI_API_KEY dans les variables d'environnement.
    """
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes
    except ImportError:
        yield ("token", (
            "[Erreur : google-genai n'est pas installé. "
            "Exécute : pip install google-genai>=1.55.0]"
        ))
        return

    api_key = _get_gemini_api_key()

    if not api_key:
        yield ("token", (
            "[Erreur : la variable d'environnement GEMINI_API_KEY n'est pas définie. "
            "Veuillez la configurer dans votre environnement (.zshrc, .bashrc) ou créer un fichier .env contenant GEMINI_API_KEY=votre_cle.]"
        ))
        return

    try:
        client = _genai.Client(api_key=api_key)
    except Exception as exc:
        yield ("token", f"[Erreur initialisation Gemini : {exc}]")
        return

    # web_search et fetch_url sont remplacés par google_search natif :
    # Gemini gère la recherche en interne sans émettre de function_call,
    # donc aucun round de tool n'est consommé pour les recherches web.
    _WEB_TOOL_NAMES = {"web_search", "fetch_url"}
    tools_sans_web = [
        tool for tool in (tools or [])
        if tool.get("function", {}).get("name") not in _WEB_TOOL_NAMES
    ]
    gemini_tool = _ollama_tools_to_gemini(tools_sans_web)
    # Google Search natif toujours présent (remplace DuckDuckGo)
    gemini_tools_list = [_gtypes.Tool(google_search=_gtypes.GoogleSearch())]
    if gemini_tool is not None:
        gemini_tools_list.append(gemini_tool)

    system_instr, gemini_contents = _ollama_messages_to_gemini(messages)

    config_kwargs: dict = {"temperature": temperature}
    if system_instr:
        config_kwargs["system_instruction"] = system_instr
    config_kwargs["tools"] = gemini_tools_list
    # Requis quand on mélange un outil natif (google_search) et des function declarations :
    if gemini_tool is not None:
        config_kwargs["tool_config"] = _gtypes.ToolConfig(
            include_server_side_tool_invocations=True
        )
    config = _gtypes.GenerateContentConfig(**config_kwargs)

    # Accumulateur pour les function calls fragmentés sur plusieurs chunks
    import time as _time
    import re as _re_retry

    _MAX_RETRIES = 3

    for _attempt in range(_MAX_RETRIES + 1):
        pending_tool_calls = []
        emitted_feedback = set()
        try:
            for chunk in client.models.generate_content_stream(
                model=model,
                contents=gemini_contents,
                config=config,
            ):
                for _fb_msg in _extract_gemini_feedback_messages(chunk):
                    if _fb_msg not in emitted_feedback:
                        emitted_feedback.add(_fb_msg)
                        yield ("token", f"\n[Gemini] {_fb_msg}\n")

                if not chunk.candidates:
                    continue
                for part in chunk.candidates[0].content.parts:
                    # Tokens de réflexion (thinking)
                    if getattr(part, "thought", False) and part.text:
                        yield ("thinking", part.text)
                    # Appel d'outil
                    elif part.function_call is not None:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        pending_tool_calls.append({
                            "function": {"name": fc.name, "arguments": args}
                        })
                    # Token de texte
                    elif part.text:
                        yield ("token", part.text)

            # Émettre les tool_calls accumulés en une seule fois
            if pending_tool_calls:
                yield ("tool_calls", pending_tool_calls)
            break  # succès

        except Exception as exc:
            _exc_str = str(exc)
            if ("429" in _exc_str or "RESOURCE_EXHAUSTED" in _exc_str) and _attempt < _MAX_RETRIES:
                _match = _re_retry.search(r"retryDelay[^0-9]*(\d+)", _exc_str)
                _delay = int(_match.group(1)) + 2 if _match else 62
                _retry_msg = _format_gemini_error(exc, prefix="Erreur Gemini")
                yield ("token", f"\n[{_retry_msg[1:-1]} – nouvelle tentative dans {_delay}s…]\n")
                _time.sleep(_delay)
            elif ("503" in _exc_str or "UNAVAILABLE" in _exc_str) and _attempt < _MAX_RETRIES:
                yield ("token", f"\n[Service Gemini indisponible – nouvelle tentative dans 10s…]\n")
                _time.sleep(10)
            else:
                yield ("token", f"\n{_format_gemini_error(exc)}")
                break


def _gemini_generate_image(prompt, input_image_bytes=None, aspect_ratio="1:1", resolution="1K"):
    """
    Génère ou modifie une image avec Nano Banana 2.
    Utilise gemini-3.1-flash-image-preview avec bascule automatique (fallback) vers gemini-2.5-flash-image si surchargé ou indisponible.

    - prompt            : description textuelle de l'image souhaitée
    - input_image_bytes : bytes de l'image source pour édition (None = génération pure)
    - aspect_ratio      : format de sortie, ex. "1:1", "16:9", "3:2" …
    - resolution        : résolution : "512", "1K", "2K", "4K"

    Retourne (text_response: str, image_bytes: bytes | None).
    """
    try:
        from google import genai as _genai_img
        from google.genai import types as _gtypes_img
        import os as _os_img
        import io as _io_img
    except ImportError:
        return ("Erreur : bibliothèque google-genai non installée.", None)

    _api_key = _get_gemini_api_key()

    if not _api_key:
        return (
            "Erreur : la variable d'environnement GEMINI_API_KEY n'est pas définie. "
            "Veuillez la configurer dans votre environnement (.zshrc, .bashrc) ou créer un fichier .env contenant GEMINI_API_KEY=votre_cle.",
            None
        )

    import time as _time_gi
    import re as _re_gi

    _candidate_models = [
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ]
    _last_error = None

    for _model in _candidate_models:
        _MAX_RETRIES_GI = 1  # Retries courts par modèle pour éviter d'attendre indéfiniment
        for _attempt_gi in range(_MAX_RETRIES_GI + 1):
            try:
                _client = _genai_img.Client(api_key=_api_key)

                # Construire le contenu : [prompt texte, image source optionnelle]
                # On évite d'envoyer response_format, qui peut provoquer l'erreur
                # "Extra inputs are not permitted" selon la version du SDK/API.
                _prompt_with_constraints = prompt
                if aspect_ratio != "1:1" or resolution != "1K":
                    _prompt_with_constraints += (
                        "\n\nContraintes de sortie :"
                        f" ratio {aspect_ratio}, taille {resolution}."
                        " Respecte ces contraintes si possible."
                    )

                _contents = [_prompt_with_constraints]
                if input_image_bytes:
                    try:
                        from PIL import Image as _PILImg, ImageOps as _PILOps
                        _pil = _PILImg.open(_io_img.BytesIO(input_image_bytes))
                        # Transposer EXIF et convertir en RGB pour supprimer la transparence RGBA potentiellement rejetée
                        _pil = _PILOps.exif_transpose(_pil).convert("RGB")
                        # Redimensionnement préventif au format 4K max pour préserver la qualité maximale
                        _pil.thumbnail((4096, 4096), _PILImg.Resampling.LANCZOS)
                        _buf = _io_img.BytesIO()
                        _pil.save(_buf, format="JPEG", quality=100, optimize=True)
                        _compressed_bytes = _buf.getvalue()
                        _contents.append(
                            _gtypes_img.Part.from_bytes(data=_compressed_bytes, mime_type="image/jpeg")
                        )
                    except Exception:
                        _contents.append(
                            _gtypes_img.Part.from_bytes(data=input_image_bytes, mime_type="image/jpeg")
                        )

                # Config minimale et robuste pour compatibilité multi-versions.
                _cfg_kwargs: dict = {"response_modalities": ["TEXT", "IMAGE"]}

                _response = _client.models.generate_content(
                    model=_model,
                    contents=_contents,
                    config=_gtypes_img.GenerateContentConfig(**_cfg_kwargs),
                )

                _text_out = ""
                _image_out = None
                _feedback_messages = _extract_gemini_feedback_messages(_response)

                # Les SDK Gemini peuvent exposer les parts à différents niveaux
                # (_response.parts ou _response.candidates[*].content.parts).
                _parts = []
                try:
                    if getattr(_response, "parts", None):
                        _parts.extend(_response.parts)
                except Exception:
                    pass
                if not _parts:
                    try:
                        for _cand in (getattr(_response, "candidates", None) or []):
                            _content = getattr(_cand, "content", None)
                            _cand_parts = getattr(_content, "parts", None) if _content is not None else None
                            if _cand_parts:
                                _parts.extend(_cand_parts)
                    except Exception:
                        pass

                for _part in _parts:
                    if getattr(_part, "thought", False):
                        continue
                    _part_text = getattr(_part, "text", None)
                    if _part_text:
                        _text_out += _part_text
                        continue
                    _inline = getattr(_part, "inline_data", None)
                    if _inline is not None and getattr(_inline, "data", None):
                        _image_out = _inline.data  # bytes PNG/JPEG

                if _feedback_messages:
                    _feedback_text = "\n".join(f"[Gemini] {_m}" for _m in _feedback_messages)
                    if _text_out:
                        _text_out = (_text_out + "\n\n" + _feedback_text).strip()
                    elif _image_out is None:
                        _text_out = _feedback_text

                return (_text_out.strip(), _image_out)

            except Exception as _exc:
                _exc_str = str(_exc)
                _last_error = _exc
                # Retry automatique très rapide sur quota 429 ou erreur 503
                if ("429" in _exc_str or "503" in _exc_str or "UNAVAILABLE" in _exc_str) and _attempt_gi < _MAX_RETRIES_GI:
                    _delay_gi = 2.0
                    _m_gi = _re_gi.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', _exc_str)
                    if _m_gi:
                        _delay_gi = float(_m_gi.group(1)) + 1.0
                    _time_gi.sleep(_delay_gi)
                    continue
                # Si erreur irrémédiable ou épuisement des essais, on tente le modèle suivant immédiatement
                break

    return (_format_gemini_error(_last_error, prefix="ERREUR Gemini Image"), None)


def _gemini_refine_image_prompt(
    intent_prompt,
    user_request="",
    mode="edit_image",
    source_filename="",
    model="gemini-3.5-flash",
):
    """
    Raffine un prompt d'intention en prompt d'édition/génération très précis
    pour Nano Banana 2.

    Retourne toujours une chaîne exploitable : en cas d'échec, renvoie intent_prompt.
    """
    intent_prompt = (intent_prompt or "").strip()
    if not intent_prompt:
        return ""

    try:
        from google import genai as _genai_ref
        from google.genai import types as _gtypes_ref
    except ImportError:
        return intent_prompt

    _api_key = _get_gemini_api_key()
    if not _api_key:
        return intent_prompt

    try:
        _client_ref = _genai_ref.Client(api_key=_api_key)
    except Exception:
        return intent_prompt

    _mode_label = "édition" if mode == "edit_image" else "génération"
    _source_line = f"- Fichier source: {source_filename}\n" if source_filename else ""
    _user_req_block = user_request.strip() if user_request else "(non fourni)"

    _instruction = (
        "Tu es un expert en prompt engineering pour un modèle image-to-image/text-to-image.\n"
        "Ta mission: réécrire l'intention en un prompt d'image ULTRA PRÉCIS et directement exécutable.\n"
        "Contraintes strictes:\n"
        "- Réponds uniquement avec le prompt final, sans commentaire, sans Markdown, sans guillemets.\n"
        "- Le prompt doit être concret, visuel, et inclure des garde-fous de fidélité au sujet.\n"
        "- Pour une édition, préserver composition, proportions, cadrage, perspective, identité du sujet et détails importants,\n"
        "  sauf si la demande explicite de les changer.\n"
        "- Éviter les formulations vagues ('améliore', 'plus beau') sans critères visuels.\n"
        "- Si l'intention est ambiguë, choisir l'interprétation la plus sûre et conservatrice.\n"
        "- Écrire en français.\n\n"
        f"Mode: {_mode_label}\n"
        f"{_source_line}"
        f"Demande utilisateur originale:\n{_user_req_block}\n\n"
        f"Intention brute à raffiner:\n{intent_prompt}\n"
    )

    try:
        _resp_ref = _client_ref.models.generate_content(
            model=model,
            contents=[_instruction],
            config=_gtypes_ref.GenerateContentConfig(temperature=0.2),
        )
        _refined = (_resp_ref.text or "").strip()
        if not _refined:
            return intent_prompt
        return _refined
    except Exception:
        return intent_prompt


# ─── Voix — TTS ───────────────────────────────────────────────────────────────

def _gemini_tts(text, voice_name="Puck", tts_model="gemini-2.5-flash-preview-tts", language_code=None):
    """
    Génère de l'audio TTS via l'API Gemini.

    Retourne les bytes PCM bruts (int16, mono, 24 kHz) ou None en cas d'erreur.
    Lève ImportError si google-genai n'est pas installé.
    """
    try:
        from google import genai as _genai
        from google.genai import types as _gtypes
    except ImportError:
        return None

    api_key = _get_gemini_api_key()
    if not api_key:
        return None

    try:
        client = _genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=tts_model,
            contents=text,
            config=_gtypes.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=_gtypes.SpeechConfig(
                    voice_config=_gtypes.VoiceConfig(
                        prebuilt_voice_config=_gtypes.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    ),
                    language_code=language_code,
                ),
            ),
        )
        return response.candidates[0].content.parts[0].inline_data.data
    except Exception:
        return None


def _gemini_tts_stream(text, voice_name="Puck", tts_model="gemini-2.5-flash-preview-tts", sample_rate=24000, language_code=None, stop_event=None):
    """
    Génère et joue le TTS via l'API Gemini en pipeline chunk par chunk.

    Le texte est découpé en morceaux de ~300 caractères aux frontières de phrases.
    Le premier chunk démarre la lecture en ~1-2 s ; les suivants se génèrent
    en parallèle pendant la lecture (pipelined).
    language_code (ex : "fr", "en") est transmis à chaque appel TTS pour
    garantir un accent cohérent sur l'ensemble de la réponse.
    stop_event (threading.Event) : si activé, interrompt immédiatement la lecture
    et la génération en cours (barge-in).
    Bloquant : attend la fin de la lecture avant de retourner.
    """
    import re
    import queue
    import threading

    # Découpe en phrases puis regroupe jusqu'à ~300 chars pour équilibrer
    # latence (chunks courts) et cohérence vocale (contexte suffisant).
    raw_sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks: list = []
    current_chunk = ""
    for sentence in raw_sentences:
        if not sentence.strip():
            continue
        candidate = (current_chunk + " " + sentence).strip() if current_chunk else sentence
        if current_chunk and len(candidate) > 300:
            chunks.append(current_chunk)
            current_chunk = sentence
        else:
            current_chunk = candidate
    if current_chunk:
        chunks.append(current_chunk)

    if not chunks:
        return

    _SENTINEL = object()
    # maxsize=3 : on pré-génère jusqu'à 3 chunks d'avance
    audio_queue: queue.Queue = queue.Queue(maxsize=3)
    chunks_failed = [0]

    def _producer():
        for chunk in chunks:
            if stop_event is not None and stop_event.is_set():
                break
            pcm = _gemini_tts(
                chunk,
                voice_name=voice_name,
                tts_model=tts_model,
                language_code=language_code,
            )
            if pcm:
                audio_queue.put(pcm)
            else:
                chunks_failed[0] += 1
        audio_queue.put(_SENTINEL)

    threading.Thread(target=_producer, daemon=True).start()

    audio_received = False
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        try:
            item = audio_queue.get(timeout=0.1)
        except Exception:
            continue
        if item is _SENTINEL:
            if not audio_received and stop_event is None or (stop_event is not None and not stop_event.is_set()):
                if chunks_failed[0] == len(chunks):
                    raise RuntimeError(
                        f"Aucun audio généré — vérifier la clé API et le modèle TTS ({tts_model})"
                    )
            break
        audio_received = True
        _voice_play_audio(item, sample_rate=sample_rate, stop_event=stop_event)


def _gemini_live_tts_stream(
    text,
    model="gemini-3.1-flash-live-preview",
    voice_name="Kore",
    sample_rate=24000,
    language_code=None,
    stop_event=None,
):
    """
    Génère et joue le TTS via l'API Gemini Live (connexion WebSocket persistante).

    Contrairement à _gemini_tts_stream qui enchaîne plusieurs requêtes indépendantes,
    cette fonction utilise une seule session Live : la voix est parfaitement cohérente
    du début à la fin (même intonation, même timbre, pas de rupture entre les phrases).

    model          : modèle Gemini Live (ex. "gemini-3.5-flash-live")
    voice_name     : voix Gemini (ex. "Kore", "Puck" — mêmes noms que le TTS classique)
    sample_rate    : fréquence de sortie PCM (24000 Hz par défaut)
    language_code  : code langue ISO 639-1 (ex. "fr") ou None pour auto-détection
    stop_event     : threading.Event — si activé, interrompt la lecture (barge-in)

    Bloquant : attend la fin de la lecture avant de retourner.
    Lève ImportError si google-genai n'est pas installé ou si le modèle n'est pas disponible.
    """
    import asyncio as _asyncio
    import queue as _queue
    import threading as _threading

    api_key = _get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Clé API Gemini introuvable — vérifier GEMINI_API_KEY")

    audio_queue: _queue.Queue = _queue.Queue(maxsize=40)
    _SENTINEL = object()
    error_holder: list = [None]

    async def _run_live():
        try:
            from google import genai as _genai
            from google.genai import types as _gtypes

            client = _genai.Client(api_key=api_key)
            live_config = _gtypes.LiveConnectConfig(
                response_modalities=["AUDIO"],
                speech_config=_gtypes.SpeechConfig(
                    voice_config=_gtypes.VoiceConfig(
                        prebuilt_voice_config=_gtypes.PrebuiltVoiceConfig(
                            voice_name=voice_name,
                        )
                    ),
                    language_code=language_code,
                ),
            )
            async with client.aio.live.connect(model=model, config=live_config) as session:
                # Gemini 3.1 Live: pendant la conversation, envoyer le texte via
                # send_realtime_input (send_client_content sert surtout à l'amorçage
                # d'historique initial avec history_config dédié).
                await session.send_realtime_input(text=text)
                async for message in session.receive():
                    if stop_event is not None and stop_event.is_set():
                        break
                    # Source officielle (Get_started_LiveAPI.py) : les données audio
                    # sont dans server_content.model_turn.parts[n].inline_data.data
                    server_content = getattr(message, "server_content", None)
                    if server_content:
                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn:
                            for part in getattr(model_turn, "parts", []):
                                inline = getattr(part, "inline_data", None)
                                if inline and getattr(inline, "data", None):
                                    audio_queue.put(inline.data)
                        if getattr(server_content, "turn_complete", False):
                            break
                    # Fallback : certaines versions SDK exposent .data directement
                    elif getattr(message, "data", None):
                        audio_queue.put(message.data)
        except Exception as exc:
            error_holder[0] = exc
        finally:
            audio_queue.put(_SENTINEL)

    def _producer():
        loop = _asyncio.new_event_loop()
        _asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_live())
        finally:
            loop.close()

    _threading.Thread(target=_producer, daemon=True).start()

    # Lecture en streaming : on ouvre UN seul OutputStream sounddevice et on y
    # écrit chaque chunk dès qu'il arrive — pas de latence d'accumulation, pas de
    # saccades (un seul stream ouvert en continu, comme le cookbook officiel Google).
    import sounddevice as _sd_tts

    got_audio = False
    output_stream = _sd_tts.RawOutputStream(
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
        blocksize=1024,
        latency="low",
    )
    output_stream.start()
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                item = audio_queue.get(timeout=0.1)
            except Exception:
                continue
            if item is _SENTINEL:
                if error_holder[0] is not None:
                    raise error_holder[0]
                if not got_audio and (stop_event is None or not stop_event.is_set()):
                    raise RuntimeError(
                        f"Aucun audio reçu du modèle Live ({model}) — "
                        "vérifier que le modèle est disponible sur votre compte"
                    )
                break
            got_audio = True
            output_stream.write(item)
    finally:
        # Attendre que le buffer interne du stream soit vidé avant de fermer
        output_stream.stop()
        output_stream.close()


def _voice_play_audio(pcm_bytes, sample_rate=24000, stop_event=None):
    """
    Joue des bytes PCM bruts (int16, mono) via sounddevice.

    stop_event (threading.Event) : si activé pendant la lecture, arrête
    immédiatement la lecture (barge-in).
    Bloquant : attend la fin de la lecture avant de retourner.
    Lève ImportError si sounddevice n'est pas installé.
    """
    import sounddevice as _sd
    import numpy as _np
    import time as _time

    audio_array = _np.frombuffer(pcm_bytes, dtype=_np.int16).astype(_np.float32) / 32768.0
    _sd.play(audio_array, samplerate=sample_rate)
    if stop_event is None:
        _sd.wait()
        return
    # Polling toutes les 20 ms pour réagir au barge-in
    total_seconds = len(audio_array) / sample_rate
    deadline = _time.monotonic() + total_seconds + 0.5
    while _time.monotonic() < deadline:
        if stop_event.is_set():
            _sd.stop()
            return
        _time.sleep(0.02)
    _sd.wait()
