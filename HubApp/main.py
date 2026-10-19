# -*- coding: utf-8 -*-
"""
Hub compilé (flet build) : coquille qui exécute Hub.pyw DEPUIS LE DÉPÔT.
Hub et les outils se mettent donc à jour par git pull, sans rebuild ;
on ne recompile que pour changer de Flet ou ajouter un contrôle natif
(flet-terminal). Les outils (.pyw) sont lancés avec le Python de la
machine : sys.executable est remplacé avant l'exécution de Hub.

Dépôt : ~/Documents/GitHub/Image_manipulations, ou le chemin écrit dans
~/.hub_repo. Python : .venv du dépôt, sinon ~/.hub_python, sinon python3/py.
"""

__version__ = "2.10.48"

import os
import runpy
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")


def _read(name):
    try:
        with open(os.path.join(HOME, name), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _machine_python(repo):
    for p in (os.path.join(repo, ".venv", "bin", "python"),
              os.path.join(repo, ".venv", "Scripts", "pythonw.exe"),
              _read(".hub_python")):
        if p and os.path.isfile(p):
            return p
    if sys.platform == "darwin":
        # App lancée depuis le Finder : PATH minimal, on demande au shell
        # de connexion le python3 que Hub.command utiliserait.
        out = subprocess.run(["/bin/zsh", "-lc", "command -v python3"],
                             capture_output=True, text=True).stdout.strip()
        if out:
            return out
    for name in ("pythonw", "python3", "python", "py"):
        p = shutil.which(name)
        if p:
            return p
    return sys.executable


repo = _read(".hub_repo") or os.path.join(HOME, "Documents", "GitHub",
                                          "Image_manipulations")
os.environ.setdefault("TERM", "xterm-256color")
sys.executable = _machine_python(repo)
os.environ["HUB_APP"] = "1"
os.chdir(repo)
sys.path[:0] = [repo, os.path.join(repo, "Data")]
sys.argv = [os.path.join(repo, "Hub.pyw")]
runpy.run_path(sys.argv[0], run_name="__main__")
