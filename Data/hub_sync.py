# -*- coding: utf-8 -*-
"""
Listes partagées entre machines via le Pi (service hub-sync derrière le
Tailscale Funnel) — remplace Notion pour la Liste de prix et la todo list.

Clé : Identifiants du Hub (repli : ~/.hub_sync, une ligne). Sans clé,
tout est local (available() renvoie False).

API :
  get(name) -> list | None   (None : absent sur le Pi)
  put(name, rows)
Les erreurs réseau remontent en exception ; c'est à l'appelant de garder
sa copie locale.
"""

__version__ = "2.10.89"


import json
import os
import urllib.error
import urllib.request

URL = "https://pictorsomni.taild63b02.ts.net:8443/hub/"
_KEY_FILE = os.path.expanduser("~/.hub_sync")


def _key():
    try:
        import credentials
        key = credentials.get_secret("hub_sync")
        if key:
            return key
    except Exception:
        pass
    try:
        with open(_KEY_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def available():
    return bool(_key())


def _req(method, name, body=None, timeout=8):
    req = urllib.request.Request(
        URL + name + ".json", data=body, method=method,
        headers={"X-Hub-Key": _key(), "Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=timeout)


def get(name, timeout=8):
    try:
        with _req("GET", name, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def put(name, rows):
    body = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    _req("PUT", name, body).close()
