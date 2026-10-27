# -*- coding: utf-8 -*-
"""
Parler à LA session Claude Code du Pi (tmux « claude ») depuis le
téléphone, comme « Parler à Claude » dans Hub — avec tous ses accès.

Pour Charles seul, triple verrou :
  - écoute sur l'adresse Tailscale du Pi uniquement (port 8551), donc
    jamais via le Funnel ni le tunnel public de la webapp ;
  - l'appareil appelant doit appartenir au compte Tailscale du Pi
    (tailscale whois) ;
  - code PIN (~/.claude_web_pin, une ligne) une fois par appareil, qui
    reste connecté 30 jours (sessions gardées dans ~/.claude_web_sessions,
    vider ce fichier déconnecte tout).
"""


import glob
import hmac
import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import push

HERE = os.path.dirname(os.path.abspath(__file__))
INBOX = os.path.expanduser("~/hub_inbox")
PIN_FILE = os.path.expanduser("~/.claude_web_pin")
PORT = 8551
IDLE = 30 * 24 * 3600
SESSIONS_FILE = os.path.expanduser("~/.claude_web_sessions")
try:
    with open(SESSIONS_FILE, encoding="utf-8") as _f:
        _sessions = json.load(_f)  # jeton -> dernière activité
except (OSError, ValueError):
    _sessions = {}


def _save_sessions():
    with open(SESSIONS_FILE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(_sessions, f)
    os.chmod(SESSIONS_FILE + ".tmp", 0o600)
    os.replace(SESSIONS_FILE + ".tmp", SESSIONS_FILE)
_lock = threading.Lock()


def _tailscale(*args):
    return subprocess.run(["tailscale", *args], capture_output=True,
                          text=True, timeout=10).stdout


def _owner():
    return json.loads(_tailscale("whois", "--json", _tailscale(
        "ip", "-4").split()[0]))["UserProfile"]["LoginName"]


def _is_owner(ip):
    try:
        who = json.loads(_tailscale("whois", "--json", ip))
        return who["UserProfile"]["LoginName"] == OWNER
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        return False


def _jsonl():
    files = glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl"))
    return max(files, key=os.path.getmtime)


def _events(path, pos):
    """Nouveautés du journal depuis l'octet `pos` : (événements, pos)."""
    with open(path, encoding="utf-8") as f:
        f.seek(pos)
        chunk = f.read()
    end = chunk.rfind("\n") + 1
    pos += len(chunk[:end].encode("utf-8"))
    out = []
    for line in chunk[:end].splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        # Copies internes (« api-request-blob »…) : seuls user/assistant.
        if obj.get("type") not in ("user", "assistant"):
            continue
        m = obj.get("message") or {}
        u = m.get("usage")
        if u:  # taille du contexte au dernier appel du modèle
            out.append({"k": "ctx", "n": u.get("input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)})
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            # Long message collé par tmux : Claude Code l'entoure de
            # balises <pasted_content id=…>, inutiles à l'affichage.
            out.append({"k": "user", "t": re.sub(
                r"</?pasted_content[^>]*>\n?", "", m["content"]).strip()})
        if m.get("role") != "assistant":
            continue
        for b in m.get("content") or []:
            if b.get("type") == "text":
                out.append({"k": "text", "t": b["text"]})
            elif b.get("type") == "thinking" and b.get("thinking"):
                out.append({"k": "think", "t": b["thinking"].strip()})
            elif b.get("type") == "tool_use":
                i = b.get("input") or {}
                what = (i.get("description") or i.get("command")
                        or i.get("file_path") or i.get("pattern") or "")
                out.append({"k": "tool",
                            "t": f"{b.get('name')} : {str(what)[:300]}"})
        if m.get("stop_reason") == "end_turn":
            out.append({"k": "end"})
    return out, pos


def _ctx_max():
    """Seuil de compactage auto de Claude Code (réglages du Pi)."""
    try:
        with open(os.path.expanduser("~/.claude/settings.json"),
                  encoding="utf-8") as f:
            return int(json.load(f).get("autoCompactWindow", 1_000_000))
    except (OSError, ValueError):
        return 1_000_000


def _pane():
    return subprocess.run(["tmux", "capture-pane", "-p", "-t", "claude"],
                          capture_output=True, text=True, timeout=10).stdout


# Ligne d'activité de Claude Code (« ✶ Jitterbugging… (22s · …) »).
_BUSY = re.compile(r"^\S \S.*… \(\d+[smh]")


def _busy(pane):
    for line in reversed(pane.splitlines()):
        if _BUSY.match(line.strip()):
            return line.strip()
    return ""


# Mises à jour en attente, revérifiées toutes les 3 h : [(texte, action)].
_updates = {"list": [], "at": 0}


def _sh(cmd):
    return subprocess.run(["bash", "-lc", cmd], capture_output=True,
                          text=True, timeout=120).stdout.strip()


def _check_updates():
    out = []
    try:
        with urllib.request.urlopen("https://registry.npmjs.org/"
                                    "@anthropic-ai/claude-code/latest",
                                    timeout=20) as r:
            last = json.load(r)["version"]
        if _sh(f"{CLAUDE} --version").split()[0] != last:
            out.append((f"Claude {last}", "maj_claude"))
    except (OSError, ValueError, KeyError, IndexError):
        pass
    _sh(f"git -C {REPO} fetch -q")
    if _sh(f"git -C {REPO} rev-list --count HEAD..@{{u}}") not in ("", "0"):
        out.append(("Hub", "maj_hub"))
    # Paquets bloqués (apt-mark hold) : jamais mis à jour, on les ignore.
    n = _sh("apt list --upgradable 2>/dev/null | grep upgradable | "
            "grep -cvFf <(apt-mark showhold | sed 's|$|/|') || true")
    if n not in ("", "0"):
        out.append((f"Pi ({n} paquets)", "maj_pi"))
    _updates.update(list=out, at=time.time())


def _tmux(*keys, literal=False):
    subprocess.run(["tmux", "send-keys", "-t", "claude",
                    *(["-l"] if literal else []), *keys], timeout=10)


REPO = os.path.dirname(HERE)
CLAUDE = os.path.expanduser("~/.local/bin/claude")
# Actions d'entretien (boutons de la page) : une à la fois, sortie suivie
# par /job. Les relances de service passent en dernier (celle de la
# webapp coupe cette page quelques secondes).
ACTIONS = {
    "bilan": f"python3 {REPO}/Pi/check_pi.py",
    "maj_pi": "sudo -n apt-get update && sudo -n env "
              "DEBIAN_FRONTEND=noninteractive apt-get -y full-upgrade "
              "&& sudo -n apt-get -y autoremove",
    "maj_claude": f"{CLAUDE} update",
    "maj_hub": f"git -C {REPO} pull --ff-only && sudo -n systemctl restart "
               "hub-sync && echo 'Webapp relancée' && systemctl --user "
               "restart hub-mobile",
    "relancer_claude": "tmux kill-session -t claude; tmux new-session -d "
                       f"-s claude '{CLAUDE} --continue --chrome' "
                       "&& echo 'Session Claude relancée'",
    "reboot": "echo 'Redémarrage du Pi…' && sudo -n systemctl reboot",
}
_job = {"name": None, "out": "", "done": True, "code": None}


def _run_job(name):
    p = subprocess.Popen(["bash", "-lc", ACTIONS[name]],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True)
    for line in p.stdout:
        _job["out"] = (_job["out"] + line)[-20000:]
    _job["code"] = p.wait()
    _job["done"] = True
    _updates["at"] = 0  # la veille revérifie les MAJ dans les 4 s


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _session_ok(self):
        tok = self.headers.get("X-Session", "")
        with _lock:
            now = time.time()
            for t in [t for t, last in _sessions.items()
                      if now - last > IDLE]:
                del _sessions[t]
            if tok in _sessions:
                if now - _sessions[tok] > 3600:  # écrit au plus 1×/h
                    _sessions[tok] = now
                    _save_sessions()
                return True
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(min(n, 200_000)) or b"{}")

    def _guard(self):
        ip = self.client_address[0]
        if ip == MY_IP:  # via « tailscale serve » (HTTPS) : identité en tête
            ok = self.headers.get("Tailscale-User-Login") == OWNER
        else:
            ok = _is_owner(ip)
        if not ok:
            self._send(403, {"error": "appareil refusé"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        path, _, query = self.path.partition("?")
        static = {"/": ("claude.html", "text/html"),
                  "/icon.png": ("claude_icon.png", "image/png"),
                  "/sw.js": ("claude_sw.js", "text/javascript"),
                  "/manifest.json": ("claude_manifest.json",
                                     "application/manifest+json")}
        if path in static:
            name, ctype = static[path]
            with open(os.path.join(HERE, name), "rb") as f:
                return self._send(200, f.read(), ctype)
        if not self._session_ok():
            return self._send(401, {"error": "PIN"})
        if path == "/vapid":
            return self._send(200, {"key": push.public_key()})
        if path == "/poll":
            _watch["seen"] = time.time()
            q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            jl = _jsonl()
            if q.get("f") != os.path.basename(jl) or "pos" not in q:
                # Premier appel (ou nouvelle conversation) : les derniers
                # échanges (ligne coupée au début : ignorée par _events).
                ev, pos = _events(jl, max(0, os.path.getsize(jl) - 400_000))
                ctx = [e for e in ev if e["k"] == "ctx"][-1:]
                return self._send(200, {"f": os.path.basename(jl),
                                        "pos": pos, "max": _ctx_max(),
                                        "ev": ctx + [e for e in ev if
                                                     e["k"] != "ctx"][-80:]})
            ev, pos = _events(jl, int(q["pos"]))
            pane = _pane()
            upd = list(_updates["list"])
            if "Restart to update" in pane:  # MAJ installée, pas chargée
                upd.insert(0, ("Claude installé", "relancer_claude"))
            return self._send(200, {"f": q["f"], "pos": pos, "ev": ev,
                                    "busy": _busy(pane), "upd": upd})
        if path == "/job":
            return self._send(200, _job)
        if path == "/screen":
            out = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", "claude"],
                capture_output=True, text=True, timeout=10).stdout
            return self._send(200, {"text": out.rstrip()})
        self._send(404, {"error": "inconnu"})

    def do_POST(self):
        if not self._guard():
            return
        if self.path.startswith("/upload?"):
            # Fichier joint (corps brut) → ~/hub_inbox, comme Hub.
            if not self._session_ok():
                return self._send(401, {"error": "PIN"})
            name = os.path.basename(urllib.parse.unquote(
                self.path.split("n=", 1)[-1])).lstrip(".") or "fichier"
            size = int(self.headers.get("Content-Length", 0))
            if size > 200_000_000:
                return self._send(413, {"error": "trop gros"})
            os.makedirs(INBOX, exist_ok=True)
            dest = os.path.join(INBOX, name)
            base, ext = os.path.splitext(dest)
            n = 1
            while os.path.exists(dest):
                dest = f"{base}_{n}{ext}"
                n += 1
            with open(dest, "wb") as f:
                left = size
                while left:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            return self._send(200, {"path": dest})
        try:
            data = self._body()
        except ValueError:
            return self._send(400, {"error": "json"})
        if self.path == "/login":
            try:
                with open(PIN_FILE, encoding="utf-8") as f:
                    pin = f.read().strip()
            except OSError:
                pin = ""
            time.sleep(1)  # freine les essais
            if not pin or not hmac.compare_digest(
                    str(data.get("pin", "")), pin):
                return self._send(403, {"error": "PIN incorrect"})
            tok = secrets.token_urlsafe(24)
            with _lock:
                _sessions[tok] = time.time()
                _save_sessions()
            return self._send(200, {"session": tok})
        if not self._session_ok():
            return self._send(401, {"error": "PIN"})
        if self.path == "/subscribe":
            push.subscribe(data)
            push.send("Claude", "Notifications activées")
            return self._send(200, {"ok": True})
        if self.path == "/send":
            text = str(data.get("text", "")).strip()
            if text:
                _tmux(text, literal=True)
                time.sleep(0.3)
                _tmux("Enter")
            return self._send(200, {"ok": True})
        if self.path == "/action":
            name = data.get("a")
            if name not in ACTIONS:
                return self._send(400, {"error": "action inconnue"})
            with _lock:
                if not _job["done"]:
                    return self._send(409, {"error": "action en cours"})
                _job.update(name=name, out="", done=False, code=None)
            threading.Thread(target=_run_job, args=(name,),
                             daemon=True).start()
            return self._send(200, {"ok": True})
        if self.path == "/key":
            # Réponses aux demandes de permission / interruption.
            key = {"oui": "Enter", "non": "Escape", "1": "1", "2": "2",
                   "3": "3", "stop": "Escape"}.get(data.get("k"))
            if key:
                _tmux(key)
            return self._send(200, {"ok": bool(key)})
        self._send(404, {"error": "inconnu"})


# ── Notifications : fin de réponse, ou accord attendu ─────────────────
# Seulement quand la page n'est pas ouverte (pas de /poll depuis 30 s).
_watch = {"seen": 0}


def _watch_loop():
    jl = _jsonl()
    pos, asked = os.path.getsize(jl), False
    while True:
        time.sleep(4)
        try:
            if _jsonl() != jl:
                jl = _jsonl()
                pos = os.path.getsize(jl)
            ev, pos = _events(jl, pos)
            if time.time() - _updates["at"] > 3 * 3600:
                _check_updates()
            pane = _pane()
            # Accord demandé, ou confiance dans le dossier (redemandée à
            # chaque démarrage de Claude Code dans le dossier personnel).
            waiting = "Do you want" in pane or "trust" in pane
            if time.time() - _watch["seen"] < 30:
                asked = waiting
                continue
            texts = [e["t"] for e in ev if e["k"] == "text"]
            if any(e["k"] == "end" for e in ev):
                push.send("Claude a répondu",
                          texts[-1] if texts else "Réponse prête")
            if waiting and not asked:
                push.send("Claude attend ton accord",
                          pane.strip().splitlines()[-1][:200]
                          if pane.strip() else "")
            asked = waiting
        except Exception as exc:  # ne doit jamais arrêter la webapp
            print(f"[Claude web] veille : {exc}", flush=True)


def serve():
    """Lancé en fil par mobile.py ; ne fait rien hors Tailscale."""
    global OWNER, MY_IP
    # Au démarrage du Pi, Tailscale peut ne pas être prêt : on réessaie.
    while True:
        try:
            ip = MY_IP = _tailscale("ip", "-4").split()[0]
            OWNER = _owner()
            break
        except (IndexError, ValueError, KeyError, OSError,
                subprocess.SubprocessError) as exc:
            print(f"[Claude web] Tailscale indisponible : {exc}",
                  flush=True)
            time.sleep(15)
    threading.Thread(target=_watch_loop, daemon=True).start()
    ThreadingHTTPServer((ip, PORT), Handler).serve_forever()


OWNER = MY_IP = None
