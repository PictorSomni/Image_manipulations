#!/bin/sh
# Clé hub-sync propre à un appareil (sur le Pi) :
#   sh Pi/cle_appareil.sh mac-boulot      crée la clé et l'affiche
# À coller dans Identifiants > hub_sync de cet appareil. Pour révoquer,
# retirer sa ligne de ~/.hub_sync_keys (effet immédiat).
set -e
[ -n "$1" ] || { echo "Usage : $0 nom-de-l-appareil" >&2; exit 1; }
K="$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")"
echo "$1 $K" >> "$HOME/.hub_sync_keys"
chmod 600 "$HOME/.hub_sync_keys"
echo "$K"
