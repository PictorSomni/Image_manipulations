"""Tâches et agenda stockés sur le Pi (source de vérité), Notion en miroir.

Même contrat que notion_rest.call_tool (outils notion-query-data-sources,
-update-page, -create-pages, -fetch, -trash-page, -restore-page, plus
« schema », réponse = chaîne JSON ou "Erreur …") : Hub et la webapp
n'ont qu'à changer de fonction d'appel.

Chaque écriture marque la page « à pousser » ; un fil la recopie vers
Notion (sens unique) et réessaie tant que Notion refuse ou est injoignable.
"""
import datetime
import json
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "..", "Data"))
import notion_rest  # noqa: E402

KANBAN = "34f4c64b-5c00-4415-99cb-76234faecef1"  # « Tâches »
SOURCES = [KANBAN,
           "ae971f83-22d1-4d53-8972-4c6302c6d371",   # Studio
           "42f7bb5c-84f2-416a-aad0-8aad7b1ea51a",   # Reportage
           "23f887c8-202a-4e37-91e1-812a4a6c7472"]   # Location
# Types que l'API Notion accepte en écriture (le reste : lecture seule).
WRITABLE = {"title", "rich_text", "select", "status", "multi_select",
            "date", "phone_number", "email", "url", "number", "checkbox"}
STORE = os.path.expanduser("~/hub_sync/tasks/taches.json")
LOCK = threading.RLock()
# {"sources": {ds: {"schema": notion_rest.schema()}}, "pages": {pid: page}}
_db = None


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


def _pid(page_id):
    return page_id.replace("-", "").rsplit("/", 1)[-1].split("?")[0]


def _save():
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE + ".tmp", "w", encoding="utf-8") as f:
        json.dump(_db, f, ensure_ascii=False, indent=1)
    os.replace(STORE + ".tmp", STORE)


def _import_source(ds):
    """Copie complète d'une base Notion (propriétés + notes)."""
    _db["sources"][ds] = {"schema": notion_rest.schema(ds)}
    rows = notion_rest._query(
        {"data": {"data_source_url": f"collection://{ds}"}})["results"]
    for r in rows:
        pid = _pid(r.pop("url"))
        edited = r.pop("last_edited", "") or _now()
        time.sleep(0.4)  # ~3 appels/s max chez Notion
        notes = notion_rest._blocks_to_text(pid)
        _db["pages"][pid] = {"ds": ds, "props": r, "notes": notes,
                             "last_edited": edited, "trashed": False,
                             "notion": pid, "dirty": False}


def _load():
    global _db
    if _db is not None:
        return _db
    try:
        with open(STORE, encoding="utf-8") as f:
            _db = json.load(f)
    except FileNotFoundError:
        _db = {"sources": {}, "pages": {}}
    if "types" in _db:  # ancien format : tâches seules
        _db = {"sources": {KANBAN: {"schema": {
            n: {"type": t, "options": []}
            for n, t in _db["types"].items()}}},
            "pages": {pid: {"ds": KANBAN, **p}
                      for pid, p in _db["pages"].items()}}
    for ds in SOURCES:
        try:  # options à jour (nouvelle option ajoutée dans Notion)
            if ds in _db["sources"]:
                _db["sources"][ds]["schema"] = notion_rest.schema(ds)
            else:
                _import_source(ds)
        except Exception as exc:
            if ds not in _db["sources"]:
                _db = None
                raise
            print(f"[Schéma Notion] {ds} : {exc}", flush=True)
    _save()
    return _db


def _types(ds):
    return {n: i["type"] for n, i in _db["sources"][ds]["schema"].items()}


def _key(types, name):
    """Nom de propriété Notion → clé de ligne (dates aplaties)."""
    if name.startswith("date:"):
        return name
    return f"date:{name}:start" if types.get(name) == "date" else name


def _set_props(page, props):
    types = _types(page["ds"])
    for name, v in props.items():
        t = types.get(name.split(":")[1] if name.startswith("date:")
                      else name)
        if t is None:
            raise ValueError(f"propriété inconnue : {name}")
        if t == "number":
            v = float(v) if v not in (None, "") else ""
        page["props"][_key(types, name)] = v if v is not None else ""


def _touch(page, notes=False):
    page["last_edited"] = _now()
    page["dirty"] = True
    if notes:
        page["notes_dirty"] = True


def _ds_of(args, key):
    ds = args.get(key) or KANBAN
    ds = ds.split("://", 1)[-1]
    if ds not in _db["sources"]:
        raise KeyError(f"base inconnue : {ds}")
    return ds


# ── Outils ──────────────────────────────────────────────────────────────
def _query(args):
    ds = _ds_of(args.get("data") or {}, "data_source_url")
    return {"results": [
        {"url": "https://www.notion.so/" + pid,
         "last_edited": p["last_edited"], **p["props"]}
        for pid, p in _db["pages"].items()
        if p["ds"] == ds and not p["trashed"]]}


def _page(page_id):
    page = _db["pages"].get(_pid(page_id))
    if page is None:
        raise KeyError(f"page introuvable : {page_id}")
    return page


def _update(args):
    page = _page(args["page_id"])
    if args["command"] == "update_properties":
        _set_props(page, args["properties"])
        _touch(page)
    elif args["command"] == "replace_content":
        page["notes"] = args["new_str"]
        _touch(page, notes=True)
    return {"ok": True}


def _create(args):
    ds = _ds_of(args.get("parent") or {}, "data_source_id")
    created = [n for n, t in _types(ds).items() if t == "created_time"]
    ids = []
    for pg in args["pages"]:
        pid = uuid.uuid4().hex
        page = {"ds": ds, "props": {n: _now() for n in created},
                "notes": pg.get("content") or "", "trashed": False,
                "notion": ""}
        _set_props(page, pg["properties"])
        _touch(page, notes=bool(page["notes"]))
        _db["pages"][pid] = page
        ids.append(pid)
    return {"ok": True, "ids": ids}


def _fetch(args):
    return {"text": "<page><content>\n" + _page(args["id"])["notes"]
            + "\n</content></page>"}


def _trash(args, flag=True):
    page = _page(args["page_id"])
    page["trashed"] = flag
    _touch(page)
    return {"ok": True}


def _schema(args):
    return _db["sources"][_ds_of(args, "data_source_id")]["schema"]


_TOOLS = {"notion-query-data-sources": _query,
          "notion-update-page": _update,
          "notion-create-pages": _create,
          "notion-fetch": _fetch,
          "notion-trash-page": _trash,
          "notion-restore-page": lambda a: _trash(a, False),
          "schema": _schema}
_READ_ONLY = {"notion-query-data-sources", "notion-fetch", "schema"}


def call_tool(name, args):
    tool = name.rsplit("__", 1)[-1]
    try:
        with LOCK:
            _load()
            out = _TOOLS[tool](args)
            if tool not in _READ_ONLY:
                _save()
                _wake.set()
        return json.dumps(out, ensure_ascii=False)
    except Exception as exc:
        return f"Erreur : {exc}"


# ── Miroir vers Notion (sens unique) ────────────────────────────────────
_wake = threading.Event()


def _notion_props(page):
    types = _types(page["ds"])
    props = {}
    for k, v in page["props"].items():
        name = k.split(":")[1] if k.startswith("date:") else k
        if types.get(name) in WRITABLE:
            props[name] = v
    return props


def _push(page):
    nid, ds = page["notion"], page["ds"]
    if not nid:
        nid = notion_rest._req("POST", "/pages", {
            "parent": {"type": "data_source_id", "data_source_id": ds},
            "properties": notion_rest._props_for(
                ds, _notion_props(page))})["id"].replace("-", "")
        with LOCK:
            page["notion"] = nid
            _save()
    elif not page["trashed"]:
        notion_rest._req("PATCH", f"/pages/{nid}", {
            "in_trash": False,
            "properties": notion_rest._props_for(ds, _notion_props(page))})
    if page["trashed"]:  # Notion refuse d'éditer une page à la corbeille
        notion_rest._req("PATCH", f"/pages/{nid}", {"in_trash": True})
    elif page.get("notes_dirty"):
        notion_rest._update({"page_id": nid, "command": "replace_content",
                             "new_str": page["notes"]})


def mirror_loop():
    while True:
        _wake.wait(60)
        _wake.clear()
        time.sleep(2)  # regroupe les rafales de modifications
        try:
            with LOCK:
                _load()
                todo = [(pid, p, p["last_edited"])
                        for pid, p in _db["pages"].items() if p["dirty"]]
        except Exception as exc:  # Notion injoignable au premier import
            print(f"[Miroir Notion] chargement : {exc}", flush=True)
            continue
        for pid, page, stamp in todo:
            try:
                _push(page)
            except Exception as exc:
                print(f"[Miroir Notion] {pid} : {exc}", flush=True)
                continue
            with LOCK:
                if page["last_edited"] == stamp:  # pas re-modifiée entre-temps
                    page["dirty"] = False
                    if not page["trashed"]:
                        page.pop("notes_dirty", None)
                    _save()
                else:
                    _wake.set()


if __name__ == "__main__":
    # Auto-test sur un magasin jetable, sans Notion.
    import tempfile
    STORE = os.path.join(tempfile.mkdtemp(), "t.json")
    _db = {"sources": {KANBAN: {"schema": {
        "Demande": {"type": "title"}, "Deadline": {"type": "date"},
        "Prix": {"type": "number"}, "Créé le": {"type": "created_time"},
        "Calcul": {"type": "formula"}}}}, "pages": {}}
    r = json.loads(call_tool("notion-create-pages", {"pages": [
        {"properties": {"Demande": "x", "Deadline": "2026-11-04"}}]}))
    pid = r["ids"][0]
    call_tool("notion-update-page", {"page_id": pid, "command":
                                     "update_properties",
                                     "properties": {"Prix": "12"}})
    row = json.loads(call_tool("notion-query-data-sources", {}))[
        "results"][0]
    assert row["date:Deadline:start"] == "2026-11-04" and row["Prix"] == 12
    _db["pages"][pid]["props"]["Calcul"] = 3
    assert _notion_props(_db["pages"][pid]) == {
        "Demande": "x", "Deadline": "2026-11-04", "Prix": 12.0}
    call_tool("notion-trash-page", {"page_id": pid})
    assert not json.loads(call_tool("notion-query-data-sources", {}))[
        "results"]
    assert call_tool("notion-fetch", {"id": "nope"}).startswith("Erreur")
    assert call_tool("notion-query-data-sources", {"data": {
        "data_source_url": "collection://zz"}}).startswith("Erreur")
    print("ok")
