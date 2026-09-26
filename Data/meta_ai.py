"""Meta Model API (Muse Image, Muse Spark) pour le Hub et Augmentation IA.

generate_image : même retour que ai_tools._gemini_generate_image.
chat_stream_with_tools : mêmes événements que
ai_tools._claude_chat_stream_with_tools. API compatible OpenAI.

Clé : variable MUSE_API_KEY (environnement ou .zshrc/.bashrc), ou
~/.meta (hors du repo, jamais commitée).
"""

__version__ = "2.3.6"

import base64
import json
import os
import ssl
import subprocess
import urllib.error
import urllib.request

_API = "https://api.meta.ai/v1"
IMAGE_MODEL = "muse-image-1.0"


def _open(req, tries=3):
    """urlopen avec 2 nouvelles tentatives si la connexion est coupée
    pendant l'envoi (WinError 10053/10054 vus côté Windows, retour user)."""
    import time
    for i in range(tries):
        try:
            return urllib.request.urlopen(
                req, timeout=300, context=ssl.create_default_context())
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, ConnectionError):
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _key():
    """MUSE_API_KEY (ou MODEL_API_KEY) dans l'environnement, sinon ~/.meta,
    sinon exportée dans .zshrc/.bashrc (une app lancée hors terminal ne
    les voit pas — même principe que la clé Gemini)."""
    for name in ("MUSE_API_KEY", "MODEL_API_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    try:
        with open(os.path.expanduser("~/.meta"), encoding="utf-8-sig") as f:
            return f.read().strip()
    except OSError:
        pass
    for shell in ("/bin/zsh", "/bin/bash"):
        if os.name != "nt" and os.path.exists(shell):
            try:
                key = subprocess.run(
                    [shell, "-li", "-c", "echo $MUSE_API_KEY"],
                    capture_output=True, text=True, timeout=2
                ).stdout.strip().splitlines()[-1:]
            except (OSError, subprocess.SubprocessError):
                continue
            if key and key[0].strip():
                os.environ["MUSE_API_KEY"] = key[0].strip()
                return key[0].strip()
    # Le shell de connexion échoue hors terminal (Pi, retour user) :
    # lecture directe de la ligne « export MUSE_API_KEY=… ».
    import re
    for rc in ("~/.zshrc", "~/.bashrc", "~/.zshenv", "~/.profile"):
        try:
            with open(os.path.expanduser(rc), encoding="utf-8") as f:
                m = re.search(r"^\s*export\s+MUSE_API_KEY=[\"']?([^\"'\s]+)",
                              f.read(), re.M)
        except OSError:
            continue
        if m:
            return m.group(1)
    return ""


def _mime(data):
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/png"


def _size(aspect_ratio):
    """Ratio du Hub ("3:4"…) -> une des 3 tailles Muse (~1K), sinon auto."""
    try:
        w, h = (float(x) for x in str(aspect_ratio).split(":"))
    except ValueError:
        return "auto"
    # Taille au ratio le plus proche (1, 2/3 ou 3/2) : le Hub/Augmentation
    # IA redimensionnent ensuite, un écart de ratio déformerait l'image.
    r = w / h
    return min((abs(r - 1), "1024x1024"), (abs(r - 2 / 3), "1024x1536"),
               (abs(r - 1.5), "1536x1024"))[1]


def _body(prompt, input_image_bytes=None, aspect_ratio=None):
    body = {"model": IMAGE_MODEL, "prompt": prompt, "n": 1,
            "size": _size(aspect_ratio)}
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


def generate_image(prompt, input_image_bytes=None, aspect_ratio=None,
                   **_ignored):
    # ponytail: résolution du Hub ignorée — Muse plafonne à ~1K
    # (1024x1024, 1024x1536, 1536x1024).
    key = _key()
    if not key:
        return ("[Erreur] Clé Meta absente : définis MUSE_API_KEY "
                "(ou ~/.meta).", None)
    path = "/images/edits" if input_image_bytes else "/images/generations"
    req = urllib.request.Request(
        _API + path, method="POST",
        data=json.dumps(_body(prompt, input_image_bytes,
                             aspect_ratio)).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with _open(req) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        return f"[Erreur] Muse Image {exc.code} : {exc.read()[:300]!r}", None
    except Exception as exc:
        return f"[Erreur] Muse Image : {exc}", None
    img = _image_from(resp)
    return ("" if img else f"[Erreur] Réponse sans image : {resp}"), img


# ── Muse Spark : discussion avec outils (Chat Completions, streaming) ───
def _to_openai(messages):
    """Messages au format Ollama du Hub -> format OpenAI. Les résultats
    d'outils n'ont pas d'id côté Hub : appariés par nom, dans l'ordre."""
    out, pending = [], {}
    for m in messages:
        role, content = m.get("role", ""), m.get("content", "") or ""
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for i, tc in enumerate(m["tool_calls"]):
                fn = tc.get("function", {})
                cid = tc.get("id") or f"call_{len(out)}_{i}"
                pending.setdefault(fn.get("name", ""), []).append(cid)
                args = fn.get("arguments", {})
                calls.append({"id": cid, "type": "function", "function": {
                    "name": fn.get("name", ""),
                    "arguments": args if isinstance(args, str)
                    else json.dumps(args, ensure_ascii=False)}})
            out.append({"role": "assistant", "content": content or None,
                        "tool_calls": calls})
            continue
        if role == "tool":
            name = m.get("name") or m.get("tool_name", "")
            ids = pending.get(name) or [f"call_{name}"]
            out.append({"role": "tool", "tool_call_id": ids.pop(0),
                        "content": str(content)})
            continue
        if m.get("images"):
            parts = [{"type": "text", "text": content}] if content else []
            parts += [{"type": "image_url", "image_url": {
                "url": f"data:{_mime(base64.b64decode(b[:24]))};base64,{b}"}}
                for b in m["images"]]
            content = parts
        out.append({"role": role, "content": content})
    return out


def chat_stream_with_tools(model, messages, tools=None, temperature=0.7):
    """Événements : ("token", str) et ("tool_calls", [{"id", "function":
    {"name", "arguments": dict}}]) — comme _claude_chat_stream_with_tools."""
    key = _key()
    if not key:
        yield ("token", "[Erreur : clé Meta absente (MUSE_API_KEY "
                        "ou ~/.meta)]")
        return
    body = {"model": model, "messages": _to_openai(messages),
            "temperature": temperature, "stream": True}
    if tools:
        body["tools"] = tools  # format Ollama = format OpenAI
    req = urllib.request.Request(
        _API + "/chat/completions", method="POST",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    calls = {}
    try:
        with _open(req) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                for ch in json.loads(data).get("choices", []):
                    delta = ch.get("delta", {})
                    if delta.get("reasoning_content"):
                        yield ("thinking", delta["reasoning_content"])
                    if delta.get("content"):
                        yield ("token", delta["content"])
                    for tc in delta.get("tool_calls") or []:
                        c = calls.setdefault(tc.get("index", 0),
                                             {"id": "", "name": "", "args": ""})
                        fn = tc.get("function", {})
                        c["id"] = tc.get("id") or c["id"]
                        c["name"] += fn.get("name") or ""
                        c["args"] += fn.get("arguments") or ""
    except urllib.error.HTTPError as exc:
        yield ("token", f"[Erreur Muse {exc.code} : "
                        f"{exc.read()[:300].decode('utf-8', 'replace')}]")
        return
    except Exception as exc:
        yield ("token", f"[Erreur Muse : {exc}]")
        return
    if calls:
        yield ("tool_calls", [
            {"id": c["id"], "function": {
                "name": c["name"], "arguments": json.loads(c["args"] or "{}")}}
            for _, c in sorted(calls.items())])


if __name__ == "__main__":
    b = _body("x", b"\xff\xd8\xff\xe0")
    assert b["images"][0]["image_url"].startswith("data:image/jpeg;base64,")
    assert _image_from({"data": [{"b64_json": base64.b64encode(
        b"ok").decode()}]}) == b"ok"
    assert _size("3:4") == "1024x1536" and _size("16:9") == "1536x1024"
    assert _size("1:1") == "1024x1024" and _size(None) == "auto"
    assert _size("1100:1000") == "1024x1024"
    conv = _to_openai([
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "f", "arguments": {"x": 1}}}]},
        {"role": "tool", "name": "f", "content": "r"}])
    assert conv[2]["tool_call_id"] == conv[1]["tool_calls"][0]["id"]
    assert conv[1]["tool_calls"][0]["function"]["arguments"] == '{"x": 1}'
    print("ok")
