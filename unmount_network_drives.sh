#!/bin/bash
# Démonte tous les lecteurs réseau puis remonte ceux listés ci-dessous.

SHARES=(
    # "smb://serveur/partage"
    # "smb://192.168.1.10/Photos"
)

# ── 1. Démontage ────────────────────────────────────────────────────────────

NETWORK_TYPES="smbfs|afpfs|nfs|webdav|cifs"
mapfile -t mounts < <(mount | grep -E "$NETWORK_TYPES" | awk '{print $3}')

if [ ${#mounts[@]} -eq 0 ]; then
    echo "Aucun lecteur réseau à démonter."
else
    for vol in "${mounts[@]}"; do
        echo "Démontage : $vol"
        diskutil unmount "$vol" 2>/dev/null || umount -f "$vol"
    done
fi

# ── 2. Remontage ─────────────────────────────────────────────────────────────

# if [ ${#SHARES[@]} -eq 0 ]; then
# echo "Aucun partage configuré."
# exit 0
# fi

# for share in "${SHARES[@]}"; do
# echo "Montage : $share"
# osascript -e "mount volume \"$share\""
# done

# echo "Terminé."
