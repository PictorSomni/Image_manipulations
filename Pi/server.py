"""Stockage JSON partagé du Hub (listes) — GET/PUT /<nom>.json, clé
X-Hub-Key. Exposé via Tailscale Funnel sur /hub.

POST /claude {"prompt"} → {"text"} : Claude Code en mode -p, SANS aucun
outil (--tools ""), sans session gardée : il ne peut que répondre.

Fichiers joints aux tâches : /files/<page_id> (GET : liste) et
/files/<page_id>/<nom> (GET, PUT corps brut, DELETE → _Supprimés).

POST /tasks {"tool", "args"} : tâches stockées sur le Pi (tasks.py),
recopiées vers Notion en fond."""
import shutil
import time
import urllib.parse
import hashlib
import hmac
import http.server
import json
import os
import re
import subprocess
import threading

import check_pi
import tasks
import mail_reply  # noqa: E402  (Data/ ajouté au chemin par tasks)
import mail_watch  # noqa: E402

ROOT = os.path.expanduser("~/hub_sync/data")
KEY = open(os.path.expanduser("~/.hub_sync_key")).read().strip()
# Une clé par appareil (« nom clé » par ligne, relu à chaque requête :
# retirer une ligne révoque l'appareil sans redémarrer). KEY reste valable.
KEYS_FILE = os.path.expanduser("~/.hub_sync_keys")
# Appels à Claude : 60 par heure au plus, tous appareils confondus.
CLAUDE_MAX_PER_HOUR = 60
_claude_calls = []
FILES = os.path.expanduser("~/task_files")
PID_RE = re.compile(r"^[0-9a-f]{32}$")
NAME_RE = re.compile(r"^[a-z0-9_-]{1,40}\.json$")
# ETag = empreinte du contenu ; PUT avec If-Match refusé (412) si le
# fichier a changé entre-temps → le client fusionne puis réessaie.
LOCK = threading.Lock()
CLAUDE = os.path.expanduser("~/.local/bin/claude")
CLAUDE_SLOTS = threading.Semaphore(2)
CLAUDE_CWD = os.path.expanduser("~/hub_sync/claude_cwd")
SKILLS_DIR = os.path.expanduser("~/.claude/skills")


def _skill_text(name):
    """Contenu d'un skill installé (sans en-tête), à ajouter au système."""
    if not name or not re.fullmatch(r"[a-z0-9-]+", name):
        return ""
    try:
        with open(os.path.join(SKILLS_DIR, name, "SKILL.md"),
                  encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)
    return ("\n\nApplique ces règles d'expert pour cette tâche (réponds "
            "toujours avec le seul résultat, en français) :\n\n" + text)
os.makedirs(CLAUDE_CWD, exist_ok=True)
CLAUDE_SYSTEM = (
    "Tu es Claude. L'équipe du Studio Cleuze, studio photo, t'écrit "
    "depuis son app Hub. Réponds en français, en tutoyant, de façon directe "
    "et concise. Mise en forme Markdown légère si utile.")


def _key_ok(given):
    keys = [KEY]
    try:
        with open(KEYS_FILE, encoding="utf-8") as f:
            keys += [ln.split()[-1] for ln in f if ln.strip()]
    except OSError:
        pass
    return any(hmac.compare_digest(given, k) for k in keys)


def etag(body):
    return '"' + hashlib.sha256(body).hexdigest()[:32] + '"'


class H(http.server.BaseHTTPRequestHandler):
    def _path(self):
        if not _key_ok(self.headers.get("X-Hub-Key", "")):
            self.send_error(403)
            return None
        name = self.path.rstrip("/").rsplit("/", 1)[-1]
        if not NAME_RE.match(name):
            self.send_error(400)
            return None
        return os.path.join(ROOT, name)

    def _file(self):
        """(dossier de la carte, nom ou None) pour /files/…, sinon None."""
        if "/files/" not in self.path:
            return None
        if not _key_ok(self.headers.get("X-Hub-Key", "")):
            self.send_error(403)
            return False
        parts = [urllib.parse.unquote(p) for p in
                 self.path.split("/files/", 1)[1].strip("/").split("/")]
        name = parts[1] if len(parts) == 2 else None
        if not PID_RE.match(parts[0]) or len(parts) > 2 or name is not None \
                and (not name or name.startswith(".") or "\\" in name
                     or len(name) > 150):
            self.send_error(400)
            return False
        return os.path.join(FILES, parts[0]), name

    def _reply(self, code, body=b"", ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _files(self, method):
        f = self._file()
        if f is None:
            return False
        if f is False:
            return True
        folder, name = f
        if name is None:
            if method != "GET":
                self.send_error(405)
                return True
            names = sorted(n for n in os.listdir(folder)
                           if not n.startswith(("_", "."))) \
                if os.path.isdir(folder) else []
            self._reply(200, json.dumps(names, ensure_ascii=False).encode())
            return True
        path = os.path.join(folder, name)
        if method == "GET":
            if not os.path.isfile(path):
                self.send_error(404)
                return True
            with open(path, "rb") as fh:
                self._reply(200, fh.read(), "application/octet-stream")
        elif method == "PUT":
            size = int(self.headers.get("Content-Length", 0))
            if size > 100_000_000:
                self.send_error(413)
                return True
            os.makedirs(folder, exist_ok=True)
            with open(path + ".tmp", "wb") as fh:
                fh.write(self.rfile.read(size))
            os.replace(path + ".tmp", path)
            self._reply(204)
        elif method == "DELETE":
            if os.path.isfile(path):  # jamais rm : _Supprimés
                bin_ = os.path.join(folder, "_Supprimés")
                os.makedirs(bin_, exist_ok=True)
                shutil.move(path, os.path.join(
                    bin_, time.strftime("%Y%m%d_%H%M%S_") + name))
            self._reply(204)
        return True

    def do_DELETE(self):
        if not self._files("DELETE"):
            self.send_error(404)

    def do_GET(self):
        if self._files("GET"):
            return
        path = self._path()
        if not path:
            return
        if not os.path.exists(path):
            self.send_error(404)
            return
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", etag(body))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not _key_ok(self.headers.get("X-Hub-Key", "")):
            self.send_error(403)
            return
        if self.path.rstrip("/").rsplit("/", 1)[-1] == "tasks":
            size = int(self.headers.get("Content-Length", 0))
            try:
                req = json.loads(self.rfile.read(size))
                out = tasks.call_tool(req["tool"], req["args"])
            except (ValueError, KeyError):
                self.send_error(400)
                return
            self._reply(200, out.encode(), "text/plain; charset=utf-8")
            return
        if self.path.rstrip("/").rsplit("/", 1)[-1] == "mail":
            # Mails du studio (Data/mail_reply.py), envoyés après validation.
            size = int(self.headers.get("Content-Length", 0))
            try:
                out = {"ok": mail_reply.call(json.loads(
                    self.rfile.read(min(size, 40_000_000))))}
            except Exception as exc:
                out = {"error": str(exc)}
            self._reply(200, json.dumps(out, ensure_ascii=False).encode(),
                        "application/json")
            return
        if self.path.rstrip("/").rsplit("/", 1)[-1] != "claude":
            self.send_error(404)
            return
        size = int(self.headers.get("Content-Length", 0))
        if size > 200_000:
            self.send_error(413)
            return
        try:
            data = json.loads(self.rfile.read(size))
            prompt = str(data["prompt"])
            system = CLAUDE_SYSTEM + _skill_text(data.get("skill"))
        except (ValueError, KeyError, TypeError):
            self.send_error(400)
            return
        with LOCK:
            now = time.time()
            _claude_calls[:] = [t for t in _claude_calls if now - t < 3600]
            if len(_claude_calls) >= CLAUDE_MAX_PER_HOUR:
                self.send_error(429)
                return
            _claude_calls.append(now)
        with CLAUDE_SLOTS:
            try:
                r = subprocess.run(
                    # Isolé : ni mémoire (dossier vide), ni réglages
                    # utilisateur, plugins, hooks, MCP ou skills.
                    [CLAUDE, "-p", "--tools", "", "--no-session-persistence",
                     "--setting-sources", "project", "--strict-mcp-config",
                     "--disable-slash-commands",
                     "--model", "claude-opus-5-5", "--effort", "low",
                     "--output-format", "text",
                     "--system-prompt", system],
                    input=prompt, capture_output=True, text=True,
                    timeout=300, cwd=CLAUDE_CWD)
                out = {"text": r.stdout.strip()} if r.returncode == 0 \
                    else {"error": (r.stderr or r.stdout).strip()[-500:]}
            except subprocess.TimeoutExpired:
                out = {"error": "Pas de réponse après 5 minutes"}
        body = json.dumps(out, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_PUT(self):
        if self._files("PUT"):
            return
        path = self._path()
        if not path:
            return
        size = int(self.headers.get("Content-Length", 0))
        if size > 5_000_000:
            self.send_error(413)
            return
        body = self.rfile.read(size)
        try:
            json.loads(body)
        except ValueError:
            self.send_error(400)
            return
        with LOCK:
            want = self.headers.get("If-Match")
            if want:
                try:
                    with open(path, "rb") as f:
                        have = etag(f.read())
                except OSError:
                    have = None
                if have is not None and have != want:
                    self.send_error(412)
                    return
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(body)
            os.replace(tmp, path)
        self.send_response(204)
        self.end_headers()


os.makedirs(ROOT, exist_ok=True)
threading.Thread(target=tasks.mirror_loop, daemon=True).start()
threading.Thread(target=check_pi.loop, daemon=True).start()
threading.Thread(target=mail_watch.loop, daemon=True).start()
# Secours sur un autre ordinateur : HUB_SYNC_BIND = son adresse Tailscale.
http.server.ThreadingHTTPServer(
    (os.environ.get("HUB_SYNC_BIND", "127.0.0.1"),
     int(os.environ.get("HUB_SYNC_PORT", 8095))), H).serve_forever()
