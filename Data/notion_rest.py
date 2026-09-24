"""Accès Notion par clé API (intégration interne) pour le panneau Tâches.

Même interface que mcp_client.mcp_call_tool pour les 4 outils Notion
utilisés par le Kanban, et mêmes formes de retour (chaîne JSON, ou
"Erreur ..."), pour que Hub.pyw n'ait qu'à choisir l'un ou l'autre.
Avantage : marche sur n'importe quelle machine, quel que soit le compte
Notion connecté (retour user : Mac du boulot sur le compte du collègue).

Clé lue dans ~/.notion_token ou ~/.notion (hors du repo, jamais
commitée). Absente ->
TOKEN vide -> Hub retombe sur la connexion MCP/OAuth.
"""

__version__ = "2.2.0"

import json
import os
import ssl
import urllib.error
import urllib.request

# ".notion" accepté aussi : c'est le nom que Charles a donné au fichier.
TOKEN = ""
for _name in ("~/.notion_token", "~/.notion"):
    try:
        with open(os.path.expanduser(_name), encoding="utf-8-sig") as f:
            TOKEN = f.read().strip()
        break
    except OSError:
        pass

_API = "https://api.notion.com/v1"
_VERSION = "2025-09-03"  # data sources (collection://...) = cette version
_schema = {}  # data_source_id -> {nom propriété: type}


def _req(method, path, body=None):
    req = urllib.request.Request(
        _API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}",
                 "Notion-Version": _VERSION,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30,
                                context=ssl.create_default_context()) as r:
        return json.loads(r.read())


# ── Propriétés ──────────────────────────────────────────────────────────
def _rich(text):
    return [{"type": "text", "text": {"content": text}}] if text else []


def _plain(rich):
    return "".join(t.get("plain_text", "") for t in rich or [])


def _read_prop(p):
    t = p["type"]
    v = p.get(t)
    if t in ("title", "rich_text"):
        return _plain(v)
    if t in ("select", "status"):
        return v["name"] if v else ""
    if t == "date":
        return v["start"] if v else ""
    if t in ("number", "phone_number", "email", "url", "created_time",
             "checkbox"):
        return v if v is not None else ""
    return ""


def _write_prop(ptype, value):
    if ptype in ("title", "rich_text"):
        return {ptype: _rich(value or "")}
    if ptype in ("select", "status"):
        return {ptype: {"name": value} if value else None}
    if ptype == "date":
        return {"date": {"start": value} if value else None}
    if ptype in ("phone_number", "email", "url"):
        return {ptype: value or None}
    if ptype == "number":
        return {"number": float(value) if value not in (None, "") else None}
    if ptype == "checkbox":
        return {"checkbox": bool(value)}
    raise ValueError(f"type de propriété non géré : {ptype}")


def _props_for(data_source_id, props):
    if data_source_id not in _schema:
        ds = _req("GET", f"/data_sources/{data_source_id}")
        _schema[data_source_id] = {n: p["type"]
                                   for n, p in ds["properties"].items()}
    types = _schema[data_source_id]
    return {name: _write_prop(types[name], v) for name, v in props.items()}


def _parent_ds(page_id):
    return _req("GET", f"/pages/{page_id}")["parent"]["data_source_id"]


# ── Contenu (Notes) : texte simple <-> blocs ────────────────────────────
# ponytail: paragraphes, puces, numéros, cases, titres seulement — le
# reste (images, tableaux…) est ignoré en lecture et perdu si on réécrit.
_PREFIX = {"bulleted_list_item": "- ", "numbered_list_item": "1. ",
           "heading_1": "# ", "heading_2": "## ", "heading_3": "### "}


def _blocks_to_text(page_id):
    lines, cursor = [], None
    while True:
        q = f"?start_cursor={cursor}" if cursor else ""
        res = _req("GET", f"/blocks/{page_id}/children{q}")
        for b in res["results"]:
            t = b["type"]
            text = _plain(b.get(t, {}).get("rich_text"))
            if t == "to_do":
                box = "[x]" if b["to_do"].get("checked") else "[ ]"
                lines.append(f"- {box} {text}")
            elif t in _PREFIX:
                lines.append(_PREFIX[t] + text)
            elif t == "paragraph":
                lines.append(text if text else "<empty-block/>")
        if not res.get("has_more"):
            return "\n".join(lines)
        cursor = res["next_cursor"]


def _text_to_blocks(text):
    blocks = []
    for line in text.split("\n"):
        if line.strip() == "<empty-block/>":
            line = ""
        t, content, extra = "paragraph", line, {}
        if line.startswith(("- [ ] ", "- [x] ")):
            t, content = "to_do", line[6:]
            extra = {"checked": line[3] == "x"}
        elif line.startswith("### "):
            t, content = "heading_3", line[4:]
        elif line.startswith("## "):
            t, content = "heading_2", line[3:]
        elif line.startswith("# "):
            t, content = "heading_1", line[2:]
        elif line.startswith(("- ", "* ")):
            t, content = "bulleted_list_item", line[2:]
        elif line[:3].rstrip(" ").rstrip(".").isdigit() and ". " in line[:4]:
            t, content = "numbered_list_item", line.split(". ", 1)[1]
        blocks.append({"type": t, t: {"rich_text": _rich(content), **extra}})
    return blocks


def _append(page_id, blocks):
    for i in range(0, len(blocks), 100):  # limite API : 100 blocs/appel
        _req("PATCH", f"/blocks/{page_id}/children",
             {"children": blocks[i:i + 100]})


# ── Outils (mêmes noms/arguments que via MCP) ───────────────────────────
def _query(args):
    ds_id = args["data"]["data_source_url"].split("://", 1)[-1]
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        res = _req("POST", f"/data_sources/{ds_id}/query", body)
        for pg in res["results"]:
            # URL courte (id seul) : Hub en extrait page_id (dernier segment)
            row = {"url": "https://www.notion.so/" + pg["id"].replace("-", "")}
            for name, p in pg["properties"].items():
                key = f"date:{name}:start" if p["type"] == "date" else name
                row[key] = _read_prop(p)
            rows.append(row)
        if not res.get("has_more"):
            return {"results": rows}
        cursor = res["next_cursor"]


def _update(args):
    page_id = args["page_id"]
    if args["command"] == "update_properties":
        _req("PATCH", f"/pages/{page_id}",
             {"properties": _props_for(_parent_ds(page_id),
                                       args["properties"])})
    elif args["command"] == "replace_content":
        cursor = None
        ids = []
        while True:
            q = f"?start_cursor={cursor}" if cursor else ""
            res = _req("GET", f"/blocks/{page_id}/children{q}")
            ids += [b["id"] for b in res["results"]]
            if not res.get("has_more"):
                break
            cursor = res["next_cursor"]
        for block_id in ids:
            _req("DELETE", f"/blocks/{block_id}")
        _append(page_id, _text_to_blocks(args["new_str"]))
    return {"ok": True}


def _create(args):
    ds_id = args["parent"]["data_source_id"]
    for pg in args["pages"]:
        created = _req("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": ds_id},
            "properties": _props_for(ds_id, pg["properties"])})
        if pg.get("content"):
            _append(created["id"], _text_to_blocks(pg["content"]))
    return {"ok": True}


def _trash(args):
    _req("PATCH", f"/pages/{args['page_id']}", {"in_trash": True})
    return {"ok": True}


def _fetch(args):
    body = _blocks_to_text(args["id"])
    return {"text": f"<page><content>\n{body}\n</content></page>"}


_TOOLS = {"notion-query-data-sources": _query,
          "notion-update-page": _update,
          "notion-create-pages": _create,
          "notion-fetch": _fetch,
          "notion-trash-page": _trash}  # pas d'équivalent MCP


def call_tool(qualified_name, arguments):
    """Même contrat que mcp_client.mcp_call_tool : toujours une chaîne."""
    try:
        return json.dumps(_TOOLS[qualified_name.rsplit("__", 1)[-1]](
            arguments), ensure_ascii=False)
    except urllib.error.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("message", "")
        except ValueError:
            msg = ""
        return f"Erreur Notion {exc.code} : {msg or exc.reason}"
    except Exception as exc:
        return f"Erreur : {exc}"


if __name__ == "__main__":
    # Auto-test hors ligne : aller-retour texte -> blocs -> texte.
    sample = "Titre\n<empty-block/>\n- puce\n- [x] fait\n1. un\n## Sous-titre"
    blocks = _text_to_blocks(sample)
    assert [b["type"] for b in blocks] == [
        "paragraph", "paragraph", "bulleted_list_item", "to_do",
        "numbered_list_item", "heading_2"], blocks
    assert blocks[3]["to_do"]["checked"] is True
    assert _write_prop("select", "") == {"select": None}
    assert _write_prop("number", "12.5") == {"number": 12.5}
    print("ok")
