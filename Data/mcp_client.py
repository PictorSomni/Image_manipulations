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
    # INFO (pas seulement WARNING) : quelques repères de progression sont
    # loggés pendant la connexion MCP pour localiser un blocage silencieux
    # (ex. CancelledError sans traceback exploitable — cf. _connect_server).
    _logger.setLevel(logging.INFO)
    # Le SDK mcp (et anyio) logue parfois lui-même la cause réelle d'un
    # échec interne (ex. tâche post_writer/handle_get_stream du transport)
    # avant qu'elle ne se perde dans un CancelledError nu côté appelant —
    # on capture ces loggers dans le même fichier pour ne rien manquer.
    for _name in ("mcp", "anyio", "httpx2", "httpcore", "httpcore2",
                  "httpx"):
        _sdk_logger = logging.getLogger(_name)
        _sdk_logger.addHandler(_handler)
        _sdk_logger.setLevel(logging.DEBUG)

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

    def clear_tokens(self):
        """Efface le token stocké (mais pas client_info : pas besoin de
        redemander une inscription dynamique du client pour ça)."""
        credentials.delete_credential(self._service, "tokens")
        credentials.delete_credential(self._service, "expiry")

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
    # Pas de print() : Hub tourne en .pyw, sans console attachée — stdout
    # y est invalide et un print() y lève un OSError (Errno 5) qui, une
    # fois relayé par le SDK, se perd en CancelledError nu côté appelant.
    _logger.info("connexion : lien d'autorisation OAuth ouvert (%s)", url)


async def _oauth_callback_handler():
    try:
        httpd = http.server.HTTPServer(
            ("localhost", _OAUTH_CALLBACK_PORT), _OAuthCallbackHandler)
    except OSError as exc:
        # Le port est probablement encore tenu par un essai précédent resté
        # bloqué indéfiniment sur handle_request() — cf. le commentaire plus
        # bas sur httpd.timeout, qui évite que ça se reproduise à l'avenir.
        _logger.warning(
            "callback OAuth local (port %d) : bind impossible (%r)",
            _OAUTH_CALLBACK_PORT, exc)
        raise
    httpd.oauth_code = None
    httpd.oauth_state = None
    # Timeout : si l'utilisateur ne termine jamais la connexion dans le
    # navigateur, handle_request() resterait sinon bloqué indéfiniment sur
    # un thread de l'executor — gardant le port occupé pour TOUT essai
    # suivant (symptôme déjà observé : échec quasi instantané d'un nouvel
    # essai, faute de pouvoir se lier à ce même port encore tenu).
    httpd.timeout = 300
    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, httpd.handle_request)
    finally:
        httpd.server_close()
    if httpd.oauth_code is None:
        raise TimeoutError(
            "Pas de retour du navigateur pour l'autorisation OAuth "
            f"(port {_OAUTH_CALLBACK_PORT}) — délai dépassé.")
    try:
        # mcp>=2.0 attend un AuthorizationCodeResult (accès à .code/.state/
        # .iss en interne, ex. oauth2.py::_perform_authorization_code_grant)
        # — un simple tuple (code, state) lève un AttributeError nu qui se
        # perd ensuite en CancelledError côté appelant (cf. laundering dans
        # _connect_server/_get_or_connect).
        from mcp.shared.auth import AuthorizationCodeResult
        return AuthorizationCodeResult(
            code=httpd.oauth_code, state=httpd.oauth_state)
    except ImportError:
        # SDK plus ancien (pré-2.0) : signature encore basée sur un tuple.
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


def _drop_loop(server_name):
    """Jette la boucle dédiée à `server_name` (potentiellement corrompue
    après une connexion ratée, cf. _ensure_loop) et l'état de session qui
    va avec, pour qu'un prochain appel reparte sur une boucle neuve plutôt
    que de réutiliser un état anyio éventuellement cassé. Peut être appelé
    depuis une coroutine tournant SUR cette boucle elle-même — on se
    contente de l'oublier (le prochain _ensure_loop en recrée une neuve),
    jamais de join/close/stop synchrone : ça retarderait la livraison du
    résultat de CET appel-ci, qui doit encore transiter par cette même
    boucle. L'ancien thread (daemon) tourne à vide et meurt avec l'appli.
    """
    _sessions.pop(server_name, None)
    _session_ctxs.pop(server_name, None)
    with _loops_lock:
        _loops.pop(server_name, None)


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
    # Repères de progression : en cas d'échec silencieux (ex. CancelledError
    # sans traceback exploitable, la tâche asyncio ayant été annulée plutôt
    # qu'une exception levée dans notre code), ces logs disent où on en
    # était rendu — le dernier repère atteint borne l'étape fautive.
    _logger.info("connexion %r : début", name)
    if server_cfg.get("transport") == "http":
        try:
            # mcp>=2.2 a renommé streamablehttp_client -> streamable_http_client.
            from mcp.client.streamable_http import streamablehttp_client
        except ImportError:
            from mcp.client.streamable_http import (
                streamable_http_client as streamablehttp_client)

        auth = None
        headers = {}
        if server_cfg.get("auth") == "oauth":
            from mcp.client.auth import OAuthClientProvider
            from mcp.shared.auth import OAuthClientMetadata
            token_storage = _KeyringTokenStorage(name)
            _oauth_metadata = OAuthClientMetadata(
                redirect_uris=[_OAUTH_REDIRECT_URI],
                client_name="Hub Image Manipulation",
                # Client public (PKCE, pas de secret) : certains
                # serveurs MCP (Notion) rejettent l'échange de token
                # si le client présente à la fois un secret et PKCE
                # ("Client must not use multiple authentication
                # methods"). Sans ce champ explicite, l'enregistrement
                # dynamique peut aboutir à un client jugé incompatible.
                token_endpoint_auth_method="none",
            )
            try:
                auth = OAuthClientProvider(
                    server_url=server_cfg["url"],
                    client_metadata=_oauth_metadata,
                    storage=token_storage,
                    redirect_handler=_oauth_redirect_handler,
                    callback_handler=_oauth_callback_handler,
                    timeout=300,
                )
            except TypeError:
                # mcp>=2.2 a retiré `timeout` du constructeur (le timeout
                # global de _run_sync/_call_tool couvre déjà l'appel).
                auth = OAuthClientProvider(
                    server_url=server_cfg["url"],
                    client_metadata=_oauth_metadata,
                    storage=token_storage,
                    redirect_handler=_oauth_redirect_handler,
                    callback_handler=_oauth_callback_handler,
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
            else:
                # Expiration inconnue (jamais enregistrée, ou effacée
                # séparément d'un vieux token encore présent) : le SDK
                # considère alors un token stocké comme valide *pour
                # toujours* (`is_token_valid()` : `not token_expiry_time`
                # → True) et l'attache tel quel à la requête — s'il est en
                # réalité expiré/révoqué, ça produit côté serveur un rejet
                # qui ne remonte jamais proprement en 401 côté client
                # (déconnexion brute → CancelledError nu, sans traceback
                # exploitable). On efface donc aussi le token lui-même
                # dans ce cas, pour forcer une ré-authentification propre
                # plutôt que d'envoyer un Bearer dont on ignore la validité.
                token_storage.clear_tokens()
            _logger.info(
                "connexion %r : OAuthClientProvider prêt (expiry stocké "
                "= %r)", name, stored_expiry)
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

        try:
            ctx = streamablehttp_client(
                server_cfg["url"], headers=headers or None, auth=auth)
        except TypeError:
            # mcp>=2.2 : streamable_http_client() ne prend plus headers/auth
            # directement — ils passent par un client HTTP dédié
            # (http_client=..., un httpx2.AsyncClient, fork interne au SDK).
            import ssl
            from mcp.client.streamable_http import httpx2
            # httpx2 utilise par défaut truststore.SSLContext (magasin de
            # certificats natif de l'OS) — sur certaines installations
            # macOS (Python.org 3.11 + truststore récent), le handshake
            # TLS plante avec un RecursionError interne à truststore
            # (boucle __getattr__ entre son SSLContext et le vrai
            # ssl.SSLContext), qui remonte comme un CancelledError nu et
            # sans traceback côté appelant. On force un ssl.SSLContext
            # standard pour contourner truststore entièrement.
            http_client = httpx2.AsyncClient(
                headers=headers or None, auth=auth,
                verify=ssl.create_default_context())
            ctx = streamablehttp_client(server_cfg["url"],
                                        http_client=http_client)
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
        _logger.info("connexion %r : ouverture du transport…", name)
        streams = await ctx.__aenter__()
        # mcp>=2.2 : streamable_http_client() ne renvoie plus le callback
        # get_session_id, juste (read, write) — comme stdio_client. Ancien
        # SDK : (read, write, get_session_id) pour le transport http.
        read, write = streams[0], streams[1]
        _logger.info("connexion %r : transport ouvert, création session…",
                     name)
        session_ctx = ClientSession(read, write)
        session = await session_ctx.__aenter__()
        _logger.info("connexion %r : session créée, initialize()…", name)
        await session.initialize()
        _logger.info("connexion %r : initialize() OK", name)
        _sessions[name] = session
        _session_ctxs[name] = (ctx, session_ctx)
        return session
    except BaseException as exc:
        # Log ICI, dans la même tâche que l'échec réel : une fois remontée
        # jusqu'à mcp_call_tool via _run_sync/run_coroutine_threadsafe, une
        # authentique CancelledError levée en interne (pas une annulation
        # externe de notre part) perd sa trace d'origine — _chain_future ne
        # laisse passer que "CancelledError()" nu côté concurrent.futures.
        # Ce log-ci, avec la trace complète, dit où ça a vraiment planté.
        _logger.warning("connexion %r : échec réel — %s", name,
                        _describe_exception(exc), exc_info=True)
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
    except BaseException:
        # Une connexion ratée peut laisser l'état interne d'anyio corrompu
        # sur LA boucle dédiée à ce serveur (cancel scope resté ouvert dans
        # une tâche déjà terminée, cf. commentaire plus haut) — les essais
        # suivants échoueraient alors instantanément (CancelledError sans
        # cause visible) même après correction du problème d'origine. On
        # jette la boucle pour repartir sur une base saine au prochain
        # appel plutôt que d'exiger un redémarrage complet de l'app.
        _drop_loop(name)
        raise
    finally:
        if task.done():
            _pending_connects.pop(name, None)


_DISCOVERY_TIMEOUT_PER_SERVER = 20   # secondes, par serveur


async def _discover_server_tools(server_cfg):
    session = await _get_or_connect(server_cfg)
    result = await session.list_tools()
    return result.tools


async def _call_tool(server_cfg, tool_name, arguments):
    name = server_cfg["name"]
    session = await _get_or_connect(server_cfg)
    _logger.info("appel outil %r : session prête, call_tool(%r)…",
                 name, tool_name)
    result = await session.call_tool(tool_name, arguments)
    _logger.info("appel outil %r : call_tool(%r) terminé", name, tool_name)
    parts = [c.text for c in result.content if getattr(c, "text", None)]
    text = "\n".join(parts) or "(résultat vide)"
    # `isError` (camelCase, alias JSON) n'est pas forcément exposé tel
    # quel comme attribut Python — le SDK expose le champ pydantic sous
    # son nom snake_case `is_error` selon la version.
    is_error = getattr(result, "is_error", getattr(result, "isError", False))
    return f"Erreur : {text}" if is_error else text


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
            # `inputSchema` (camelCase, alias JSON) n'est pas forcément le
            # nom d'attribut Python exposé selon la version du SDK mcp —
            # même piège que `is_error`/`isError` plus haut. Repli sur le
            # nom snake_case si besoin.
            input_schema = getattr(
                tool, "inputSchema", getattr(tool, "input_schema", None))
            tools.append({
                "type": "function",
                "function": {
                    "name": f"{_TOOL_PREFIX}{name}__{tool.name}",
                    "description": tool.description or "",
                    "parameters": input_schema
                    or {"type": "object", "properties": {}},
                },
            })
    return tools


def _backup_dir():
    """Dossier de sauvegarde (sous Data/), créé à la demande."""
    dirname = getattr(CONSTANTS, "AI_BACKUP_DIRNAME", ".ai_backups")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), dirname)


def _prune_backup_dir(base_dir, max_entries):
    """Garde seulement les `max_entries` sauvegardes JSON les plus
    récentes dans `base_dir` — filet anti-perte, pas un historique
    permanent (même motif que ai_tools._prune_backup_dir pour les
    sauvegardes de fichiers, retour user). Ne lève jamais."""
    try:
        entries = list(os.scandir(base_dir))
        entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        for stale in entries[max_entries:]:
            try:
                os.remove(stale.path)
            except OSError:
                pass
    except Exception as exc:
        _logger.warning("purge des anciennes sauvegardes MCP échouée : %r", exc)


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
        _prune_backup_dir(_dir, getattr(CONSTANTS, "AI_BACKUP_MAX_ENTRIES", 5))
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
        return (f"Erreur outil MCP {qualified_name} : "
                f"{_describe_exception(exc)}")


def _describe_exception(exc):
    """Description lisible d'une exception, même sans message (ex. un
    ExceptionGroup vide dont str() ne rend rien) : on affiche le type et,
    pour un groupe, on déplie récursivement les sous-exceptions."""
    sub_excs = getattr(exc, "exceptions", None)
    if sub_excs:
        details = "; ".join(_describe_exception(e) for e in sub_excs)
        return f"{type(exc).__name__}({details})"
    text = str(exc)
    if text:
        return f"{type(exc).__name__}: {text}"
    return type(exc).__name__
