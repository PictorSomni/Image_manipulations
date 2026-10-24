# -*- coding: utf-8 -*-
"""
Listes partagées entre machines via le Pi (service hub-sync derrière le
Tailscale Funnel) — remplace Notion pour la Liste de prix et la todo list.

Clé : Identifiants du Hub (repli : ~/.hub_sync, une ligne). Sans clé,
tout est local (available() renvoie False).

API :
  get(name) -> list | None   (None : absent sur le Pi)
  put(name, rows)
  sync_put(name, base, mine) -> list   fusion à 3 voies (édition
      simultanée sur deux appareils : aucune modification perdue)
Les erreurs réseau remontent en exception ; c'est à l'appelant de garder
sa copie locale.
"""


import json
import os
from collections import Counter
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


def _req(method, name, body=None, timeout=8, headers=None):
    req = urllib.request.Request(
        URL + name + ".json", data=body, method=method,
        headers={"X-Hub-Key": _key(), "Content-Type": "application/json",
                 **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def get(name, timeout=8):
    try:
        with _req("GET", name, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def put(name, rows, if_match=None):
    body = json.dumps(rows, ensure_ascii=False, indent=2).encode("utf-8")
    req = _req("PUT", name, body, headers={"If-Match": if_match}
               if if_match else None)
    req.close()


def _get_etag(name, timeout=8):
    try:
        with _req("GET", name, timeout=timeout) as resp:
            return (json.loads(resp.read().decode("utf-8")),
                    resp.headers.get("ETag"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, None
        raise


def _key_of(row):
    return json.dumps(row, ensure_ascii=False, sort_keys=True)


def merge3(base, mine, theirs):
    """Applique à `theirs` (version du Pi) ce que `mine` a changé depuis
    `base` (dernière version lue) : lignes retirées puis lignes ajoutées,
    chacune replacée après sa voisine de `mine`. Une ligne modifiée =
    ancienne retirée + nouvelle ajoutée, donc elle reste à sa place."""
    base, mine, theirs = base or [], mine or [], theirs or []
    if theirs == base:
        return list(mine)
    if mine == base:
        return list(theirs)
    removed = Counter(map(_key_of, base)) - Counter(map(_key_of, mine))
    added = Counter(map(_key_of, mine)) - Counter(map(_key_of, base))
    result = []
    for row in theirs:
        k = _key_of(row)
        if removed[k] > 0:
            removed[k] -= 1
        else:
            result.append(row)
    for i, row in enumerate(mine):
        k = _key_of(row)
        if added[k] <= 0:
            continue
        added[k] -= 1
        pos = len(result) if i else 0
        if i:
            prev = _key_of(mine[i - 1])
            for j in range(len(result) - 1, -1, -1):
                if _key_of(result[j]) == prev:
                    pos = j + 1
                    break
        result.insert(pos, row)
    return result


def sync_put(name, base, mine, tries=4):
    """Envoie `mine` sans écraser ce qu'un autre appareil a écrit depuis
    `base` : relit le Pi, fusionne, écrit avec If-Match ; réessaie si le
    fichier a encore changé entre-temps. Renvoie la version enregistrée
    (à garder comme nouvelle base)."""
    for _ in range(tries):
        theirs, tag = _get_etag(name)
        merged = merge3(base, mine, theirs) if theirs is not None else mine
        try:
            put(name, merged, if_match=tag)
            return merged
        except urllib.error.HTTPError as exc:
            if exc.code != 412:
                raise
    raise RuntimeError(f"{name} : trop de modifications simultanées")


def ask_claude(prompt, timeout=320):
    """Réponse de Claude sur le Pi (POST /claude, sans aucun outil)."""
    req = urllib.request.Request(
        URL + "claude", method="POST",
        data=json.dumps({"prompt": prompt}).encode(),
        headers={"X-Hub-Key": _key(),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    if data.get("error"):
        raise RuntimeError(data["error"])
    return data["text"]
