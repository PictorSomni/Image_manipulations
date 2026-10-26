"""Bilan de santé du Pi, refait chaque heure par hub-sync (loop()).

Écrit ~/hub_sync/data/etat_pi.json {"at", "problemes": [...]} : Hub et
la webapp l'affichent en rouge s'il y a un problème, ou si le bilan est
trop vieux (le Pi ou cette vérification ne tourne plus).
"""
import datetime
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, "hub_sync", "data", "etat_pi.json")


def _age_h(path):
    return (time.time() - os.path.getmtime(path)) / 3600


def _active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet",
                           unit]).returncode == 0


def checks():
    pb = []
    try:
        key = open(os.path.join(HOME, ".hub_sync_key")).read().strip()
        req = urllib.request.Request(
            "http://127.0.0.1:8095/tasks", headers={"X-Hub-Key": key},
            data=b'{"tool": "notion-query-data-sources", "args": {}}')
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.read().startswith(b"Erreur"):
                pb.append("hub-sync : tâches illisibles")
    except Exception as exc:
        pb.append(f"hub-sync ne répond pas ({exc})")
    try:
        with open(os.path.join(HOME, "hub_sync", "tasks", "taches.json"),
                  encoding="utf-8") as f:
            pages = json.load(f)["pages"].values()
        limit = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(minutes=30)).strftime(
                     "%Y-%m-%dT%H:%M:%S")
        late = sum(1 for p in pages if p["dirty"]
                   and p["last_edited"][:19] < limit)
        if late:
            pb.append(f"{late} modification(s) pas encore recopiée(s) "
                      "dans Notion depuis plus de 30 min")
    except Exception as exc:
        pb.append(f"Tâches illisibles sur le Pi ({exc})")
    try:  # service utilisateur : invisible depuis hub-sync, on l'appelle
        urllib.request.urlopen("http://127.0.0.1:8550/", timeout=10)
    except urllib.error.HTTPError:
        pass  # répond (connexion demandée) : il tourne
    except Exception:
        pb.append("Webapp (hub-mobile) arrêtée")
    if not _active("cloudflared"):
        pb.append("Service cloudflared arrêté")
    try:
        last = int(subprocess.run(
            ["git", "-C", os.path.join(HOME, "pi-backup"), "log", "-1",
             "--format=%ct"], capture_output=True, text=True).stdout)
        if time.time() - last > 26 * 3600:
            pb.append("Sauvegarde GitHub de la nuit pas faite")
    except ValueError:
        pb.append("Sauvegarde GitHub introuvable")
    try:
        if _age_h(os.path.join(HOME, "notion_backup", "latest.json")) > 13:
            pb.append("Copie Notion du Pi vieille de plus de 13 h")
    except OSError:
        pb.append("Copie Notion du Pi introuvable")
    disk = shutil.disk_usage(HOME)
    if disk.free / disk.total < 0.10:
        pb.append(f"Disque du Pi presque plein "
                  f"({disk.free * 100 // disk.total} % libre)")
    return pb


def run():
    data = {"at": datetime.datetime.now().isoformat(timespec="seconds"),
            "problemes": checks()}
    with open(OUT + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(OUT + ".tmp", OUT)
    return data


def loop():
    time.sleep(60)  # laisse hub-sync démarrer
    while True:
        try:
            run()
        except Exception as exc:
            print(f"[Bilan Pi] {exc}", flush=True)
        time.sleep(3600)


if __name__ == "__main__":
    print(run())
