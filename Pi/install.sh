#!/bin/sh
# Installe le service hub-sync et l'expose sur le Funnel existant (/hub).
set -e
# Code dans le dépôt (Pi/), lancé depuis ~/hub_sync par liens : données
# (data/, tasks/) et clés restent hors du dépôt.
mkdir -p ~/hub_sync
for f in server.py tasks.py check_pi.py; do
    ln -sf "$(cd "$(dirname "$0")" && pwd)/$f" ~/hub_sync/$f
done
[ -f ~/.hub_sync_key ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > ~/.hub_sync_key
chmod 600 ~/.hub_sync_key
sudo tee /etc/systemd/system/hub-sync.service >/dev/null <<'EOF'
[Unit]
Description=Hub - stockage JSON partagé des listes
After=network.target

[Service]
User=pictorsomni
ExecStart=/usr/bin/python3 /home/pictorsomni/hub_sync/server.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now hub-sync
sudo tailscale funnel --bg --https=8443 --set-path /hub http://127.0.0.1:8095
tailscale funnel status
echo "Clé à copier dans ~/.hub_sync sur chaque machine :"
cat ~/.hub_sync_key
