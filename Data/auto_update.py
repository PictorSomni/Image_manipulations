"""Mise à jour de Hub au démarrage : git pull --ff-only du dépôt.

Une vieille version de Hub écrirait encore les tâches dans Notion au lieu
du Pi : chaque machine se met donc à jour seule. Jamais de question
(clé SSH ou rien), jamais de fusion : en cas de souci, on n'y touche pas.
"""
import os
import subprocess

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10"}


def _version():
    try:
        with open(os.path.join(REPO, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "?"


def pull():
    """(ancienne, nouvelle) version si Hub vient d'être mis à jour, None
    sinon (déjà à jour, pas de git, hors ligne, modifications locales)."""
    if not os.path.isdir(os.path.join(REPO, ".git")):
        return None
    before = _version()
    try:
        r = subprocess.run(["git", "-C", REPO, "pull", "--ff-only", "-q"],
                           capture_output=True, text=True, timeout=60,
                           env=_ENV,
                           creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    after = _version()
    return (before, after) if r.returncode == 0 and after != before else None
