"""Quiz : jeu de questions-réponses pour apprendre en s'amusant.

Webapp à part (port 8560), jouée en équipe ou en solo. Les questions
sont rédigées par Claude sur le Pi (hub-sync /claude, sans outils) ;
progression, révisions et questions déjà vues dans ~/quiz/state.json.
"""
import datetime
import json
import os
import random
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "Data"))
import hub_sync  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(HERE), "Mobile"))
import push  # noqa: E402

PORT = 8560
STATE = os.path.expanduser("~/quiz/state.json")
TEAM = "Ensemble"
SEEN_MAX = 400       # questions gardées pour éviter les répétitions
REVIEW_STEPS = [1, 3, 7, 30]  # jours avant chaque retour d'une ratée
DAILY_HOUR = 8       # heure de la question du jour
THEMES = ["Tout mélangé", "Histoire", "Géographie", "Sciences",
          "Nature et animaux", "Espace", "Corps humain", "Inventions",
          "Art et peinture", "Littérature", "Musique", "Cinéma",
          "Langue française", "Mythologie", "Cuisine", "Sport",
          "Belgique", "Photographie"]
LEVELS = ["Facile", "Accessible", "Moyen", "Corsé", "Difficile",
          "Expert", "Très expert", "Érudit", "Maître", "Légende"]
_lock = threading.Lock()


def _read():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"profiles": {}}


def _write(state):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(STATE + ".tmp", STATE)


def _profile(state, name):
    return state["profiles"].setdefault(name, {
        "points": 0, "good": 0, "bad": 0, "games": 0, "best_streak": 0,
        "best_game": 0, "seen": [], "review": []})


def _today():
    return datetime.date.today().isoformat()


def summary():
    state = _read()
    _profile(state, TEAM)
    return {"themes": THEMES, "levels": LEVELS, "team": TEAM,
            "profiles": {n: {k: p[k] for k in (
                "points", "good", "bad", "games", "best_streak",
                "best_game")} | {"review": sum(
                    r["due"] <= _today() for r in p["review"])}
                for n, p in state["profiles"].items()},
            "daily": state.get("daily")}


def _ask(theme, level, n, avoid, kind="qcm"):
    if kind == "vf":
        return _ask_vf(theme, level, n, avoid)
    rule = (
        f"Tu écris {n} questions de quiz de culture générale en français "
        f"pour un couple qui veut apprendre en s'amusant. Thème : "
        f"{'varié, un domaine différent par question' if theme == THEMES[0] else theme}. "
        f"Difficulté {level + 1}/10 ({LEVELS[level]}). Faits exacts et "
        "vérifiables uniquement ; pas de question piège ni ambiguë ; les "
        "mauvaises réponses doivent être plausibles. Réponds UNIQUEMENT "
        "par un tableau JSON : [{\"theme\": domaine en 1 ou 2 mots, "
        "\"q\": question, \"good\": bonne réponse, \"bad\": [3 mauvaises "
        "réponses], \"hint\": indice qui aide sans donner la réponse, "
        "\"explain\": 2 ou 3 phrases qui expliquent la réponse et "
        "ajoutent une anecdote à retenir}].")
    return _parse(rule, avoid, theme, level, "qcm")


def _ask_vf(theme, level, n, avoid):
    rule = (
        f"Tu écris {n} affirmations de culture générale en français, à "
        "juger vrai ou faux, pour un couple qui veut apprendre en "
        f"s'amusant. Thème : "
        f"{'varié, un domaine différent par affirmation' if theme == THEMES[0] else theme}. "
        f"Difficulté {level + 1}/10 ({LEVELS[level]}). Environ moitié "
        "vraies, moitié fausses ; les fausses sont des idées reçues ou des "
        "erreurs plausibles, jamais des pièges de formulation. Réponds "
        "UNIQUEMENT par un tableau JSON : [{\"theme\": domaine en 1 ou 2 "
        "mots, \"q\": affirmation, \"true\": true ou false, "
        "\"explain\": 1 ou 2 phrases surprenantes qui rétablissent les "
        "faits}].")
    return _parse(rule, avoid, theme, level, "vf")


def _parse(rule, avoid, theme, level, kind):
    if avoid:
        rule += " Questions déjà posées, à ne pas refaire : " + " | ".join(
            avoid[-150:])
    text = hub_sync.ask_claude(rule)
    start = text.find("[")
    items = (json.JSONDecoder().raw_decode(text[start:])[0]
             if start >= 0 else [])
    out = []
    for item in items:
        if kind == "vf":
            if "q" in item and isinstance(item.get("true"), bool):
                out.append({"theme": item.get("theme") or theme,
                            "q": item["q"], "choices": ["Vrai", "Faux"],
                            "answer": 0 if item["true"] else 1, "hint": "",
                            "explain": item.get("explain", ""),
                            "level": level})
            continue
        try:
            choices = [str(item["good"])] + [str(b) for b in item["bad"][:3]]
        except (KeyError, TypeError):
            continue
        if len(set(choices)) != 4:
            continue
        random.shuffle(choices)
        out.append({"theme": item.get("theme") or theme, "q": item["q"],
                    "choices": choices,
                    "answer": choices.index(str(item["good"])),
                    "hint": item.get("hint", ""),
                    "explain": item.get("explain", ""), "level": level})
    return out


def questions(name, theme, level, n=10, kind="qcm"):
    level = max(0, min(int(level), len(LEVELS) - 1))
    with _lock:
        state = _read()
        prof = _profile(state, name)
        avoid = [q for p in state["profiles"].values() for q in p["seen"]]
        due = [r for r in prof["review"] if r["due"] <= _today()]
    out = [q for q in _ask(theme, level, n, avoid, kind) if q["q"] not in avoid]
    with _lock:  # vues dès l'envoi : le lot suivant ne les reprend pas
        state = _read()
        prof = _profile(state, name)
        prof["seen"] = (prof["seen"] + [q["q"] for q in out])[-SEEN_MAX:]
        _write(state)
    for r in random.sample(due, min(3, len(due))):  # révisions dues
        out.insert(random.randrange(len(out) + 1), dict(r["q"], review=True))
    return out


def answer(name, q, ok, streak, game_points):
    with _lock:
        state = _read()
        prof = _profile(state, name)
        prof["good" if ok else "bad"] += 1
        if ok:
            prof["points"] += 10 * (q.get("level", 0) + 1)
        prof["best_streak"] = max(prof["best_streak"], int(streak))
        prof["best_game"] = max(prof["best_game"], int(game_points))
        if q["q"] not in prof["seen"]:
            prof["seen"] = (prof["seen"] + [q["q"]])[-SEEN_MAX:]
        old = [r for r in prof["review"] if r["q"]["q"] == q["q"]]
        prof["review"] = [r for r in prof["review"] if r not in old]
        # Révision espacée : ratée → demain, puis 3, 7 et 30 jours si
        # elle est réussie à chaque retour.
        step = 0 if not ok else old[0].get("step", 0) + 1 if old else None
        if step is not None and step < len(REVIEW_STEPS):
            due = datetime.date.today() + datetime.timedelta(
                REVIEW_STEPS[step])
            prof["review"].append({"due": due.isoformat(), "step": step,
                                   "q": {k: v for k, v in q.items()
                                         if k != "review"}})
        _write(state)
    return summary()


def end_game(name):
    with _lock:
        state = _read()
        _profile(state, name)["games"] += 1
        _write(state)
    return summary()


def daily_loop():
    """Chaque matin, une question pour tous, annoncée par notification."""
    while True:
        try:
            today = _today()
            if (datetime.datetime.now().hour >= DAILY_HOUR
                    and (_read().get("daily") or {}).get("date") != today):
                qs = questions(TEAM, THEMES[0], 3, n=3)
                q = next(x for x in qs if not x.get("review"))
                with _lock:
                    state = _read()
                    state["daily"] = {"date": today, "q": q}
                    _write(state)
                push.send("Question du jour", q["q"])
        except Exception as exc:
            print(f"[Question du jour] {exc}", flush=True)
        time.sleep(600)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, body, ctype, code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code=200):
        self._send(json.dumps(data, ensure_ascii=False).encode(),
                   "application/json", code)

    def do_GET(self):
        files = {"/": ("index.html", "text/html; charset=utf-8"),
                 "/icon.png": ("icon.png", "image/png"),
                 "/manifest.json": ("manifest.json", "application/json")}
        path = self.path.split("?")[0]
        if path == "/api/state":
            return self._json(summary())
        if path not in files:
            return self._json({"error": "inconnu"}, 404)
        name, ctype = files[path]
        with open(os.path.join(HERE, name), "rb") as f:
            self._send(f.read(), ctype)

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(min(size, 100_000)))
            name = str(data.get("profile") or TEAM).strip()[:30] or TEAM
            if self.path == "/api/questions":
                out = questions(name, str(data.get("theme") or THEMES[0])
                                [:60], data.get("level", 0),
                                kind=data.get("kind", "qcm"))
            elif self.path == "/api/answer":
                out = answer(name, data["q"], bool(data["ok"]),
                             data.get("streak", 0), data.get("points", 0))
            elif self.path == "/api/end":
                out = end_game(name)
            elif self.path == "/api/profile":
                with _lock:
                    state = _read()
                    _profile(state, name)
                    _write(state)
                out = summary()
            else:
                return self._json({"error": "inconnu"}, 404)
            self._json(out)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


if __name__ == "__main__":
    threading.Thread(target=daily_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
