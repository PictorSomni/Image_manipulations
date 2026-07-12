# -*- coding: utf-8 -*-
"""
Client MCP générique — connecte Dashboard/SidePanel à n'importe quel
serveur MCP configuré dans CONSTANTS.MCP_SERVERS, expose ses outils dans
le même format que les outils internes de ai_tools.py (JSON Schema), et
route les appels vers le bon serveur. Fonctionne avec n'importe quel
modèle actif (Gemini/Ollama/Claude) : le format d'outil est déjà celui
utilisé partout ailleurs dans l'app, converti automatiquement par
_ollama_tools_to_gemini / _ollama_tools_to_claude (ai_tools.py).

Aucun serveur configuré par défaut (CONSTANTS.MCP_SERVERS = []) : ce
module est totalement inerte tant que Charles n'ajoute pas d'entrée —
aucun thread ni import du SDK mcp au démarrage de l'app.

API publique :
  mcp_get_all_tools() -> liste d'outils au format {"type": "function", ...}
  mcp_call_tool(qualified_name, arguments) -> str (résultat texte)
"""

import asyncio
import http.server
import os
import threading
import urllib.parse
import webbrowser

import CONSTANTS
import credentials

_TOOL_PREFIX = "mcp__"

# ── OAuth (serveurs MCP hébergés — Notion, et plus généralement tout
# serveur SaaS distant, la spec MCP standardise OAuth 2.1 pour ce cas) ──
_OAUTH_CALLBACK_PORT = 8765
_OAUTH_REDIRECT_URI = f"http://localhost:{_OAUTH_CALLBACK_PORT}/callback"


class _KeyringTokenStorage:
    """Persiste les tokens/infos client OAuth dans le coffre natif de
    l'OS (Data/credentials.py), par serveur — jamais en clair sur disque.
    Implémente le protocole mcp.client.auth.TokenStorage.
    """

    def __init__(self, server_name):
        self._service = f"mcp_oauth_{server_name}"

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        raw = credentials.get_credential(self._service, "tokens")
        return OAuthToken.model_validate_json(raw) if raw else None

    async def set_tokens(self, tokens):
        credentials.set_credential(
            self._service, "tokens", tokens.model_dump_json())

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        raw = credentials.get_credential(self._service, "client_info")
        return OAuthClientInformationFull.model_validate_json(raw) if raw else None

    async def set_client_info(self, client_info):
        credentials.set_credential(
            self._service, "client_info", client_info.model_dump_json())


class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Capte la redirection OAuth locale (code + state) sur un seul
    aller-retour, puis affiche une page de confirmation minimale."""

    def do_GET(self):
        query = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(query)
        self.server.oauth_code = (params.get("code") or [None])[0]
        self.server.oauth_state = (params.get("state") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            "<html><body>Connexion réussie — tu peux fermer cet "
            "onglet.</body></html>".encode("utf-8")
        )

    def log_message(self, *args):
        pass   # pas de bruit sur stdout pour chaque requête


async def _oauth_redirect_handler(url):
    webbrowser.open(url)
    print(f"[MCP] Ouvre ce lien pour autoriser la connexion : {url}")


async def _oauth_callback_handler():
    httpd = http.server.HTTPServer(
        ("localhost", _OAUTH_CALLBACK_PORT), _OAuthCallbackHandler)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, httpd.handle_request)
    return httpd.oauth_code, httpd.oauth_state

_loop = None
_loop_thread = None
_loop_lock = threading.Lock()
_sessions = {}   # nom de serveur -> mcp.ClientSession déjà connectée
# Références fortes vers les context managers (stdio_client/streamablehttp_client
# + ClientSession) : entrés manuellement via __aenter__ sans jamais être
# sortis (connexions gardées ouvertes tant que l'app tourne), leur garbage
# collection prématurée casse le nettoyage interne d'anyio (cancel scope
# ouvert/fermé dans des tâches différentes) — on les garde donc en vie ici.
_session_ctxs = {}   # nom de serveur -> (transport_ctx, session_ctx)


def _ensure_loop():
    """Démarre (une seule fois) le thread de fond avec sa boucle asyncio."""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None:
            return _loop
        ready = threading.Event()

        def _run():
            global _loop
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            ready.set()
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run, daemon=True)
        _loop_thread.start()
        ready.wait(timeout=5)
        return _loop


def _run_sync(coro, timeout=30):
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


async def _connect_server(server_cfg):
    """Ouvre une session MCP (stdio ou http) et la garde active."""
    from mcp import ClientSession

    name = server_cfg["name"]
    if server_cfg.get("transport") == "http":
        from mcp.client.streamable_http import streamablehttp_client

        auth = None
        headers = {}
        if server_cfg.get("auth") == "oauth":
            from mcp.client.auth import OAuthClientProvider
            from mcp.shared.auth import OAuthClientMetadata
            auth = OAuthClientProvider(
                server_url=server_cfg["url"],
                client_metadata=OAuthClientMetadata(
                    redirect_uris=[_OAUTH_REDIRECT_URI],
                    client_name="Dashboard Image Manipulation",
                    # Client public (PKCE, pas de secret) : certains
                    # serveurs MCP (Notion) rejettent l'échange de token
                    # si le client présente à la fois un secret et PKCE
                    # ("Client must not use multiple authentication
                    # methods"). Sans ce champ explicite, l'enregistrement
                    # dynamique peut aboutir à un client jugé incompatible.
                    token_endpoint_auth_method="none",
                ),
                storage=_KeyringTokenStorage(name),
                redirect_handler=_oauth_redirect_handler,
                callback_handler=_oauth_callback_handler,
                timeout=300,
            )
        else:
            token_env = server_cfg.get("headers_env")
            if token_env:
                token = os.environ.get(token_env, "").strip()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

        ctx = streamablehttp_client(
            server_cfg["url"], headers=headers or None, auth=auth)
        read, write, _ = await ctx.__aenter__()
    else:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )
        ctx = stdio_client(params)
        read, write = await ctx.__aenter__()

    session_ctx = ClientSession(read, write)
    session = await session_ctx.__aenter__()
    await session.initialize()
    _sessions[name] = session
    _session_ctxs[name] = (ctx, session_ctx)
    return session


async def _get_or_connect(server_cfg):
    name = server_cfg["name"]
    if name in _sessions:
        return _sessions[name]
    return await _connect_server(server_cfg)


async def _list_all_tools():
    tools = []
    for server_cfg in CONSTANTS.MCP_SERVERS:
        name = server_cfg["name"]
        try:
            session = await _get_or_connect(server_cfg)
            result = await session.list_tools()
        except Exception:
            continue
        for tool in result.tools:
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{_TOOL_PREFIX}{name}__{tool.name}",
                    "description": tool.description or "",
                    "parameters": tool.inputSchema
                    or {"type": "object", "properties": {}},
                },
            })
    return tools


async def _call_tool(qualified_name, arguments):
    rest = qualified_name[len(_TOOL_PREFIX):]
    server_name, _, tool_name = rest.partition("__")
    server_cfg = next(
        (s for s in CONSTANTS.MCP_SERVERS if s["name"] == server_name), None)
    if server_cfg is None:
        return f"Serveur MCP inconnu : {server_name}"
    session = await _get_or_connect(server_cfg)
    result = await session.call_tool(tool_name, arguments)
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    text = "\n".join(parts) or "(résultat vide)"
    return f"Erreur : {text}" if result.isError else text


def mcp_get_all_tools():
    """Outils de tous les serveurs configurés, au format outil interne.

    [] si CONSTANTS.MCP_SERVERS est vide (aucune connexion tentée) ou si
    la découverte échoue globalement. Un serveur individuellement en
    échec est ignoré sans empêcher les autres de répondre.

    Timeout à 300s (pas 20s) : une première connexion à un serveur OAuth
    (Notion...) attend que Charles clique "Autoriser" dans son
    navigateur — sans incidence sur le cas courant (session déjà
    authentifiée → réponse en quelques centaines de ms).
    """
    if not CONSTANTS.MCP_SERVERS:
        return []
    try:
        return _run_sync(_list_all_tools(), timeout=300)
    except Exception:
        return []


def mcp_call_tool(qualified_name, arguments):
    """Appelle un outil MCP par son nom qualifié (mcp__<serveur>__<outil>).

    Retourne toujours une chaîne (résultat ou message d'erreur lisible
    par le modèle), ne lève jamais. Timeout à 300s, même raison que
    mcp_get_all_tools (premier appel OAuth potentiellement interactif).
    """
    try:
        return _run_sync(_call_tool(qualified_name, arguments or {}), timeout=300)
    except Exception as exc:
        return f"Erreur outil MCP {qualified_name} : {exc}"
