#!/bin/sh
# Secours si le Pi est en panne : hub-sync tourne sur cette machine (Mac
# ou Linux) avec les données de la dernière sauvegarde de la nuit.
#
#   sh Pi/secours.sh           démarre le secours (Ctrl+C pour l'arrêter)
#   sh Pi/secours.sh retour    Pi réparé : lui renvoie les données d'ici
#
# Pendant le secours, les autres machines doivent viser celle-ci : sur
# chacune, ~/.hub_sync_url contient l'adresse affichée au démarrage
# (supprimer ce fichier une fois le Pi revenu).
set -e
REPO="$(cd "$(dirname "$0")/.." && pwd)"
B="$HOME/pi-secours"
PY=python3; [ -x "$REPO/.venv/bin/python" ] && PY="$REPO/.venv/bin/python"

if [ "$1" = "retour" ]; then
    rsync -a "$HOME/hub_sync/tasks/" pictorsomni@pictorsomni:hub_sync/tasks/
    rsync -a "$HOME/hub_sync/data/" pictorsomni@pictorsomni:hub_sync/data/
    rsync -a "$HOME/task_files/" pictorsomni@pictorsomni:task_files/
    ssh pictorsomni@pictorsomni "sudo systemctl restart hub-sync"
    rm -f "$HOME/.hub_sync_url"
    echo "Données renvoyées au Pi, hub-sync relancé."
    exit 0
fi

if [ -d "$B/.git" ]; then
    git -C "$B" pull -q origin main
else
    git clone -q git@github.com:PictorSomni/pi-backup.git "$B"
fi
echo "Sauvegarde du $(git -C "$B" log -1 --format=%cd --date=short)"
mkdir -p "$HOME/hub_sync" "$HOME/task_files"
rsync -a "$B/files/hub_sync/data" "$HOME/hub_sync/"
rsync -a "$B/files/hub_sync/tasks" "$HOME/hub_sync/"
rsync -a "$B/files/task_files/" "$HOME/task_files/"

# Même clé que celle de Hub sur cette machine.
if [ ! -s "$HOME/.hub_sync_key" ]; then
    (cd "$REPO/Data" && "$PY" -c \
        "import hub_sync; print(hub_sync._key())") > "$HOME/.hub_sync_key"
    chmod 600 "$HOME/.hub_sync_key"
fi

IP="$(tailscale ip -4 2>/dev/null | head -1)"
IP="${IP:-127.0.0.1}"
PORT="${HUB_SYNC_PORT:-8095}"
echo "http://$IP:$PORT/" > "$HOME/.hub_sync_url"
echo "Secours actif. Sur les autres machines, ~/.hub_sync_url :"
echo "    http://$IP:$PORT/"
HUB_SYNC_BIND="$IP" HUB_SYNC_PORT="$PORT" exec "$PY" "$REPO/Pi/server.py"
