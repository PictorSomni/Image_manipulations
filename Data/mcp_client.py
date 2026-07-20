# -*- coding: utf-8 -*-
"""
Client MCP générique — connecte Hub à n'importe quel
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
import json
import logging
import os
import threading
import time
import urllib.parse
import webbrowser

import CONSTANTS
import credentials

_TOOL_PREFIX = "mcp__"

# Un serveur MCP en échec est ignoré silencieusement pour ne pas bloquer
# les autres (voir mcp_get_all_tools) — mais l'erreur réelle doit rester
# quelque part consultable, plutôt que disparaître complètement (Hub
# tourne en .pyw, sans console).
_logger = logging.getLogger("mcp_client")
if not _logger.handlers:
    _log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mcp_errors.log")
    _handler = logging.FileHandler(_log_path, encoding="utf-8")
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    _logger.addHandler(_handler)
    _logger.setLevel(logging.WARNING)

# ── OAuth (serveurs MCP hébergés — Notion, et plus généralement tout
# serveur SaaS distant, la spec MCP standardise OAuth 2.1 pour ce cas) ──
_OAUTH_CALLBACK_PORT = 8765
_OAUTH_REDIRECT_URI = f"http://localhost:{_OAUTH_CALLBACK_PORT}/callback"


class _KeyringTokenStorage:
    """Persiste les tokens/infos client OAuth dans le coffre natif de
    l'OS (Data/credentials.py), par serveur — jamais en clair sur disque.
    Implémente le protocole mcp.client.auth.TokenStorage.

    Persiste aussi l'expiration absolue du token (voir get_expiry) : le SDK
    mcp ne la recalcule pas lui-même après un rechargement depuis le stockage
    (seulement après une authorization/refresh fraîche), donc sans ça, un
    token expiré est considéré valide jusqu'au premier 401 — qui déclenche
    alors une réautorisation complète (navigateur) plutôt qu'un simple
    rafraîchissement silencieux. D'où la reconnexion demandée à chaque
    lancement de l'appli une fois le token expiré.
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
        if tokens.expires_in is not None:
            expiry = time.time() + int(tokens.expires_in)
            credentials.set_credential(self._service, "expiry", str(expiry))

    def get_expiry(self):
        """Expiration absolue (timestamp Unix) persistée, ou None si
        inconnue/jamais enregistrée. Synchrone : lu juste après la
        création de OAuthClientProvider, avant toute connexion réseau.
        """
        raw = credentials.get_credential(self._service, "expiry")
        return float(raw) if raw else None

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

_loops = {}   # nom de serveur -> (event loop, thread) dédiés à CE serveur
_loops_lock = threading.Lock()
_sessions = {}   # nom de serveur -> mcp.ClientSession déjà connectée
# Références fortes vers les context managers (stdio_client/streamablehttp_client
# + ClientSession) : entrés manuellement via __aenter__ sans jamais être
# sortis (connexions gardées ouvertes tant que l'app tourne), leur garbage
# collection prématurée casse le nettoyage interne d'anyio (cancel scope
# ouvert/fermé dans des tâches différentes) — on les garde donc en vie ici.
_session_ctxs = {}   # nom de serveur -> (transport_ctx, session_ctx)


def _ensure_loop(server_name):
    """Boucle asyncio dédiée à `server_name` — jamais une boucle globale
    partagée entre serveurs. Vécu : comfyui-mcp (package communautaire) a
    fini par corrompre l'état interne d'anyio (cancel scope resté ouvert
    dans une tâche déjà terminée) au point de faire tourner sa boucle en
    boucle infinie, ce qui gelait TOUS les serveurs MCP pour le reste de
    la session puisqu'ils partageaient la même boucle. Avec une boucle
    par serveur, un tel blocage reste cantonné au serveur fautif.
    """
    with _loops_lock:
        entry = _loops.get(server_name)
        if entry is not None:
            return entry[0]
        ready = threading.Event()
        holder = {}

        def _run():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            holder["loop"] = loop
            ready.set()
            loop.run_forever()

        thread = threading.Thread(
            target=_run, daemon=True, name=f"mcp-loop-{server_name}")
        thread.start()
        ready.wait(timeout=5)
        _loops[server_name] = (holder["loop"], thread)
        return holder["loop"]


def _run_sync(server_name, coro, timeout=30):
    loop = _ensure_loop(server_name)
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


async def _connect_server(server_cfg):
    """Ouvre une session MCP (stdio ou http) et la garde active."""
    from mcp import ClientSession

    name = server_cfg["name"]
    ctx = None
    session_ctx = None
    if server_cfg.get("transport") == "http":
        from mcp.client.streamable_http import streamablehttp_client

        auth = None
        headers = {}
        if server_cfg.get("auth") == "oauth":
            from mcp.client.auth import OAuthClientProvider
            from mcp.shared.auth import OAuthClientMetadata
            token_storage = _KeyringTokenStorage(name)
            auth = OAuthClientProvider(
                server_url=server_cfg["url"],
                client_metadata=OAuthClientMetadata(
                    redirect_uris=[_OAUTH_REDIRECT_URI],
                    client_name="Hub Image Manipulation",
                    # Client public (PKCE, pas de secret) : certains
                    # serveurs MCP (Notion) rejettent l'échange de token
                    # si le client présente à la fois un secret et PKCE
                    # ("Client must not use multiple authentication
                    # methods"). Sans ce champ explicite, l'enregistrement
                    # dynamique peut aboutir à un client jugé incompatible.
                    token_endpoint_auth_method="none",
                ),
                storage=token_storage,
                redirect_handler=_oauth_redirect_handler,
                callback_handler=_oauth_callback_handler,
                timeout=300,
            )
            # Le SDK ne recalcule l'expiration qu'après une authorization/
            # refresh fraîche, jamais après un simple rechargement depuis le
            # stockage — sans ça, un token expiré passe pour valide jusqu'au
            # premier 401, qui déclenche une réautorisation complète
            # (navigateur) au lieu d'un rafraîchissement silencieux. On la
            # restaure nous-mêmes avant la première requête.
            stored_expiry = token_storage.get_expiry()
            if stored_expiry is not None:
                auth.context.token_expiry_time = stored_expiry
        elif server_cfg.get("auth") == "token":
            # Jeton statique généré côté serveur MCP (page "Members" de
            # PrestaShop par ex.), lié à un compte précis plutôt qu'à la
            # session OAuth du navigateur — stocké via credentials.py,
            # jamais en clair. Voir credentials.py "set" pour l'enregistrer.
            token = credentials.get_credential(f"mcp_token_{name}", "token")
            if token:
                headers["Authorization"] = f"Bearer {token}"
        else:
            token_env = server_cfg.get("headers_env")
            if token_env:
                token = os.environ.get(token_env, "").strip()
                if token:
                    headers["Authorization"] = f"Bearer {token}"

        ctx = streamablehttp_client(
            server_cfg["url"], headers=headers or None, auth=auth)
    else:
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=server_cfg["command"],
            args=server_cfg.get("args", []),
            env=server_cfg.get("env"),
        )
        ctx = stdio_client(params)

    try:
        if server_cfg.get("transport") == "http":
            read, write, _ = await ctx.__aenter__()
        else:
            read, write = await ctx.__aenter__()
        session_ctx = ClientSession(read, write)
        session = await session_ctx.__aenter__()
        await session.initialize()
        _sessions[name] = session
        _session_ctxs[name] = (ctx, session_ctx)
        return session
    except BaseException as exc:
        # Démontage dans LA MÊME tâche que __aenter__. Sinon un ctx entré mais
        # jamais fermé (ex. échec 401 à initialize) est finalisé plus tard par
        # le GC dans une autre tâche → "Attempted to exit cancel scope in a
        # different task" + "Task exception was never retrieved" au terminal.
        _tb = exc.__traceback__
        if session_ctx is not None:
            try:
                await session_ctx.__aexit__(type(exc), exc, _tb)
            except BaseException:
                pass
        if ctx is not None:
            try:
                await ctx.__aexit__(type(exc), exc, _tb)
            except BaseException:
                pass
        raise


_pending_connects = {}   # nom de serveur -> Task de connexion en cours


async def _get_or_connect(server_cfg):
    name = server_cfg["name"]
    if name in _sessions:
        return _sessions[name]
    task = _pending_connects.get(name)
    if task is None:
        task = asyncio.ensure_future(_connect_server(server_cfg))
        _pending_connects[name] = task
    try:
        # Pas de asyncio.shield/wait_for ici : le timeout est appliqué
        # côté _run_sync (future.result(timeout=...), dans le thread
        # appelant, hors du monde async). Annuler cette tâche depuis
        # l'extérieur (ce que faisait l'ancien asyncio.wait_for) est ce
        # qui a fini par corrompre anyio (cancel scope fermé dans une
        # tâche différente de celle qui l'a ouvert). Sans annulation
        # asynchrone, la connexion en cours continue tranquillement sur
        # sa boucle dédiée et le message suivant la retrouve en vol.
        return await task
    finally:
        if task.done():
            _pending_connects.pop(name, None)


_DISCOVERY_TIMEOUT_PER_SERVER = 20   # secondes, par serveur


async def _discover_server_tools(server_cfg):
    session = await _get_or_connect(server_cfg)
    result = await session.list_tools()
    return result.tools


async def _call_tool(server_cfg, tool_name, arguments):
    session = await _get_or_connect(server_cfg)
    result = await session.call_tool(tool_name, arguments)
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    text = "\n".join(parts) or "(résultat vide)"
    return f"Erreur : {text}" if result.isError else text


def mcp_get_all_tools():
    """Outils de tous les serveurs configurés, au format outil interne.

    [] si CONSTANTS.MCP_SERVERS est vide. Chaque serveur tourne sur sa
    propre boucle asyncio (_ensure_loop) avec son propre timeout de
    _DISCOVERY_TIMEOUT_PER_SERVER secondes : un serveur en échec, lent,
    ou dont la boucle se bloque est ignoré sans empêcher les autres de
    répondre, et sans plus jamais bloquer les appels futurs (contrairement
    à l'ancienne boucle unique partagée par tous les serveurs).
    """
    if not CONSTANTS.MCP_SERVERS:
        return []
    tools = []
    for server_cfg in CONSTANTS.MCP_SERVERS:
        name = server_cfg["name"]
        try:
            server_tools = _run_sync(
                name, _discover_server_tools(server_cfg),
                timeout=_DISCOVERY_TIMEOUT_PER_SERVER,
            )
        except Exception as exc:
            _logger.warning(
                "découverte des outils échouée pour %r : %r", name, exc,
                exc_info=True)
            continue
        for tool in server_tools:
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


def _backup_dir():
    """Dossier de sauvegarde (sous Data/), créé à la demande."""
    dirname = getattr(CONSTANTS, "AI_BACKUP_DIRNAME", ".ai_backups")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), dirname)


def _backup_mcp_mutation(qualified_name, arguments):
    """Instantané d'une mutation MCP avant exécution (filet anti-perte).

    Sauvegarde nom d'outil + arguments + horodatage dès que le nom de l'outil
    évoque une opération destructrice (AI_MCP_DESTRUCTIVE_KEYWORDS). Générique :
    tous les serveurs, pas seulement Notion. Ne lève jamais.
    """
    if not getattr(CONSTANTS, "AI_BACKUP_ENABLED", True):
        return
    _kw = getattr(CONSTANTS, "AI_MCP_DESTRUCTIVE_KEYWORDS", ())
    _low = qualified_name.lower()
    if not any(k in _low for k in _kw):
        return
    try:
        _dir = os.path.join(_backup_dir(), "mcp")
        os.makedirs(_dir, exist_ok=True)
        _ts = time.strftime("%Y%m%d_%H%M%S")
        _safe = "".join(c if c.isalnum() or c in "._-" else "_"
                        for c in qualified_name)[:80]
        _path = os.path.join(_dir, f"{_ts}_{_safe}.json")
        _n = 1
        while os.path.exists(_path):
            _path = os.path.join(_dir, f"{_ts}_{_safe}_{_n}.json")
            _n += 1
        with open(_path, "w", encoding="utf-8") as _f:
            json.dump(
                {"timestamp": _ts, "tool": qualified_name,
                 "arguments": arguments},
                _f, ensure_ascii=False, indent=2, default=str,
            )
    except Exception as exc:
        _logger.warning(
            "backup MCP avant mutation échoué pour %r : %r",
            qualified_name, exc)


def mcp_call_tool(qualified_name, arguments):
    """Appelle un outil MCP par son nom qualifié (mcp__<serveur>__<outil>).

    Retourne toujours une chaîne (résultat ou message d'erreur lisible
    par le modèle), ne lève jamais. Timeout à 300s (un appel d'outil, ex.
    génération d'image, peut être long) sur la boucle dédiée à ce serveur.

    Avant toute mutation destructrice, un instantané de l'appel est sauvegardé
    (voir _backup_mcp_mutation).
    """
    _backup_mcp_mutation(qualified_name, arguments)
    rest = qualified_name[len(_TOOL_PREFIX):]
    server_name, _, tool_name = rest.partition("__")
    server_cfg = next(
        (s for s in CONSTANTS.MCP_SERVERS if s["name"] == server_name), None)
    if server_cfg is None:
        return f"Serveur MCP inconnu : {server_name}"
    try:
        return _run_sync(
            server_name, _call_tool(server_cfg, tool_name, arguments or {}),
            timeout=300,
        )
    except Exception as exc:
        _logger.warning(
            "appel d'outil MCP %r échoué : %r", qualified_name, exc,
            exc_info=True)
        return f"Erreur outil MCP {qualified_name} : {exc}"
