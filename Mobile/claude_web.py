# -*- coding: utf-8 -*-
"""
Parler à LA session Claude Code du Pi (tmux « claude ») depuis le
téléphone, comme « Parler à Claude » dans Hub — avec tous ses accès.

Pour Charles seul, triple verrou :
  - écoute sur l'adresse Tailscale du Pi uniquement (port 8551), donc
    jamais via le Funnel ni le tunnel public de la webapp ;
  - l'appareil appelant doit appartenir au compte Tailscale du Pi
    (tailscale whois) ;
  - code PIN (~/.claude_web_pin, une ligne), session fermée après
    30 min sans activité.
"""


import glob
import hmac
import json
import os
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PIN_FILE = os.path.expanduser("~/.claude_web_pin")
PORT = 8551
IDLE = 30 * 60
_sessions = {}  # jeton -> dernière activité
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
            m = json.loads(line).get("message") or {}
        except ValueError:
            continue
        if m.get("role") == "user" and isinstance(m.get("content"), str):
            out.append({"k": "user", "t": m["content"]})
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
                _sessions[tok] = now
                return True
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(min(n, 200_000)) or b"{}")

    def _guard(self):
        if not _is_owner(self.client_address[0]):
            self._send(403, {"error": "appareil refusé"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        path, _, query = self.path.partition("?")
        if path == "/":
            with open(os.path.join(HERE, "claude.html"), "rb") as f:
                return self._send(200, f.read(), "text/html")
        if not self._session_ok():
            return self._send(401, {"error": "PIN"})
        if path == "/poll":
            q = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            jl = _jsonl()
            if q.get("f") != os.path.basename(jl) or "pos" not in q:
                # Premier appel (ou nouvelle conversation) : les derniers
                # échanges (ligne coupée au début : ignorée par _events).
                ev, pos = _events(jl, max(0, os.path.getsize(jl) - 400_000))
                return self._send(200, {"f": os.path.basename(jl),
                                        "pos": pos, "ev": ev[-80:]})
            ev, pos = _events(jl, int(q["pos"]))
            return self._send(200, {"f": q["f"], "pos": pos, "ev": ev})
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
            return self._send(200, {"session": tok})
        if not self._session_ok():
            return self._send(401, {"error": "PIN"})
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


def serve():
    """Lancé en fil par mobile.py ; ne fait rien hors Tailscale."""
    global OWNER
    try:
        ip = _tailscale("ip", "-4").split()[0]
        OWNER = _owner()
    except (IndexError, ValueError, KeyError, OSError,
            subprocess.SubprocessError) as exc:
        print(f"[Claude web] Tailscale indisponible : {exc}", flush=True)
        return
    ThreadingHTTPServer((ip, PORT), Handler).serve_forever()


OWNER = None
