"""Muse Image (Meta Model API) pour generate_image / edit_image du Hub.

Même retour que ai_tools._gemini_generate_image : (texte, octets image
ou None). API compatible OpenAI : /images/generations et /images/edits.

Clé lue dans MODEL_API_KEY (environnement) ou ~/.meta (hors du repo,
jamais commitée).
"""

__version__ = "2.3.0"

import base64
import json
import os
import ssl
import urllib.request

_API = "https://api.meta.ai/v1"
MODEL = "muse-image-1.0"


def _key():
    key = os.environ.get("MODEL_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(os.path.expanduser("~/.meta"), encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        return ""


def _mime(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/png"


def _body(prompt, input_image_bytes=None):
    body = {"model": MODEL, "prompt": prompt, "n": 1}
    if input_image_bytes:
        b64 = base64.b64encode(input_image_bytes).decode()
        body["images"] = [{"image_url":
                           f"data:{_mime(input_image_bytes)};base64,{b64}"}]
    return body


def _image_from(resp):
    item = (resp.get("data") or [{}])[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    if item.get("url"):
        with urllib.request.urlopen(item["url"], timeout=120) as r:
            return r.read()
    return None


def generate_image(prompt, input_image_bytes=None, **_ignored):
    # ponytail: ratio et résolution du Hub ignorés — valeurs de `size`
    # non documentées ; à brancher quand la doc les liste.
    key = _key()
    if not key:
        return ("[Erreur] Clé Meta absente : mets-la dans ~/.meta "
                "(ou MODEL_API_KEY).", None)
    path = "/images/edits" if input_image_bytes else "/images/generations"
    req = urllib.request.Request(
        _API + path, method="POST",
        data=json.dumps(_body(prompt, input_image_bytes)).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300,
                                    context=ssl.create_default_context()) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return f"[Erreur] Muse Image {exc.code} : {exc.read()[:300]!r}", None
    img = _image_from(resp)
    return ("" if img else f"[Erreur] Réponse sans image : {resp}"), img


if __name__ == "__main__":
    b = _body("x", b"\xff\xd8\xff\xe0")
    assert b["images"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert _image_from({"data": [{"b64_json": base64.b64encode(
        b"ok").decode()}]}) == b"ok"
    print("ok")
