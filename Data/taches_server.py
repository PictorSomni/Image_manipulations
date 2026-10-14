# -*- coding: utf-8 -*-
"""
API auto-hébergée pour le panneau Kanban "Tâches" de Hub, en remplacement
de Notion (voir discussion 2026-09-23 : indépendance des données, pas de
dépendance à un service tiers/token externe).

Tourne en permanence sur le Raspberry Pi (service systemd), accessible
uniquement via le réseau Tailscale de Charles (jamais exposée
publiquement). La base est un simple fichier SQLite, backupé comme le
reste du Pi.

Utilisation manuelle (débogage) :
    python3 "Data/taches_server.py"
Utilisation normale : voir Data/taches_server.service (systemd).
"""

import json
import os
import sqlite3
import time
from pathlib import Path

from flask import Flask, jsonify, request

#############################################################
#                         CONSTANTES                         #
#############################################################
DB_DIR = Path.home() / ".taches"
DB_PATH = DB_DIR / "taches.db"
LISTEN_HOST = "0.0.0.0"  # filtré par Tailscale, pas de risque public
LISTEN_PORT = 8787

# Jeton partagé simple : défense en profondeur si jamais l'ACL Tailscale
# était mal configurée. Généré une fois puis stocké à côté de la base
# (jamais dans git).
TOKEN_PATH = DB_DIR / "token.txt"

ETATS = ["À faire", "En cours / en attente", "Terminé",
          "A commander", "Commandé"]
PROJETS = ["Pas de projet", "Faire projet", "Projet envoyé",
           "Projet validé", "Fichiers prêts"]
PAYES = ["Non payé", "Payé"]

app = Flask(__name__)


#############################################################
#                       BASE DE DONNÉES                      #
#############################################################
def _get_token():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKEN_PATH.exists():
        import secrets
        TOKEN_PATH.write_text(secrets.token_hex(24), encoding="utf-8")
        TOKEN_PATH.chmod(0o600)
    return TOKEN_PATH.read_text(encoding="utf-8").strip()


def _db():
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS taches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            demande TEXT NOT NULL DEFAULT '',
            etat TEXT NOT NULL DEFAULT 'À faire',
            projet TEXT NOT NULL DEFAULT 'Pas de projet',
            paye TEXT NOT NULL DEFAULT 'Non payé',
            deadline TEXT DEFAULT '',
            telephone TEXT DEFAULT '',
            email TEXT DEFAULT '',
            prix REAL DEFAULT 0,
            notes TEXT DEFAULT '',
            cree_le TEXT NOT NULL,
            modifie_le TEXT NOT NULL,
            notion_page_id TEXT UNIQUE,
            pending_notion_sync INTEGER NOT NULL DEFAULT 0,
            notion_synced_le TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def _row_to_dict(row):
    return {k: row[k] for k in row.keys()}


#############################################################
#                          SÉCURITÉ                          #
#############################################################
@app.before_request
def _check_token():
    expected = _get_token()
    got = request.headers.get("X-Taches-Token", "")
    if got != expected:
        return jsonify({"error": "Token invalide"}), 401


#############################################################
#                          ENDPOINTS                         #
#############################################################
@app.route("/tasks", methods=["GET"])
def list_tasks():
    conn = _db()
    rows = conn.execute(
        "SELECT * FROM taches ORDER BY cree_le DESC").fetchall()
    conn.close()
    return jsonify([_row_to_dict(r) for r in rows])


@app.route("/tasks", methods=["POST"])
def create_task():
    data = request.get_json(force=True) or {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    conn = _db()
    cur = conn.execute(
        "INSERT INTO taches (demande, etat, projet, paye, deadline, "
        "telephone, email, prix, notes, cree_le, modifie_le) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (data.get("demande", ""),
         data.get("etat", "À faire"),
         data.get("projet", "Pas de projet"),
         data.get("paye", "Non payé"),
         data.get("deadline", ""),
         data.get("telephone", ""),
         data.get("email", ""),
         data.get("prix", 0),
         data.get("notes", ""),
         now, now))
    conn.commit()
    new_id = cur.lastrowid
    row = conn.execute(
        "SELECT * FROM taches WHERE id = ?", (new_id,)).fetchone()
    conn.close()
    return jsonify(_row_to_dict(row)), 201


@app.route("/tasks/<int:task_id>", methods=["PATCH"])
def update_task(task_id):
    data = request.get_json(force=True) or {}
    content_fields = {"demande", "etat", "projet", "paye", "deadline",
                       "telephone", "email", "prix", "notes"}
    sync_fields = {"notion_page_id", "pending_notion_sync",
                   "notion_synced_le"}
    fields = {k: v for k, v in data.items()
              if k in content_fields or k in sync_fields}
    if not fields:
        return jsonify({"error": "Aucun champ valide"}), 400
    conn = _db()
    existing = conn.execute(
        "SELECT id FROM taches WHERE id = ?", (task_id,)).fetchone()
    if not existing:
        conn.close()
        return jsonify({"error": "Tâche introuvable"}), 404
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [task_id]
    # modifie_le ne doit bouger que sur un vrai changement de contenu
    # (utilisateur) — pas quand Hub met juste à jour la comptabilité de
    # synchro Notion (notion_page_id, etc.), sinon la logique "qui a
    # changé en dernier" pour la réconciliation serait faussée.
    if any(k in content_fields for k in fields):
        set_clause += ", modifie_le = ?"
        values.insert(-1, time.strftime("%Y-%m-%d %H:%M:%S"))
    conn.execute(
        f"UPDATE taches SET {set_clause} WHERE id = ?",
        values)
    conn.commit()
    row = conn.execute(
        "SELECT * FROM taches WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return jsonify(_row_to_dict(row))


@app.route("/tasks/<int:task_id>", methods=["DELETE"])
def delete_task(task_id):
    conn = _db()
    conn.execute("DELETE FROM taches WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return "", 204


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    print(f"Token d'accès (à mettre dans Hub) : {_get_token()}")
    print(f"Base : {DB_PATH}")
    app.run(host=LISTEN_HOST, port=LISTEN_PORT)
