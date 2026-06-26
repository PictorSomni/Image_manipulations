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

# ── 2. Nettoyage stubs APFS (-1) ─────────────────────────────────────────────
# Quand macOS crée NAME et NAME-1 simultanément, NAME est un stub vide.
# On démonte NAME-1 et on supprime le stub NAME pour un remontage propre.

for vol_with_suffix in /Volumes/*-[0-9]; do
    [ -d "$vol_with_suffix" ] || continue
    base="${vol_with_suffix%-*}"
    [ -d "$base" ] || continue
    echo "Stub détecté : $base (stub) + $vol_with_suffix"
    echo "  Démontage : $vol_with_suffix"
    diskutil unmount "$vol_with_suffix" 2>/dev/null || umount -f "$vol_with_suffix" 2>/dev/null
    echo "  Suppression du stub : $base"
    rmdir "$base" 2>/dev/null || echo "  Impossible de supprimer $base (non vide ?)"
done

# ── 3. Remontage ─────────────────────────────────────────────────────────────

# if [ ${#SHARES[@]} -eq 0 ]; then
# echo "Aucun partage configuré."
# exit 0
# fi

# for share in "${SHARES[@]}"; do
# echo "Montage : $share"
# osascript -e "mount volume \"$share\""
# done

# echo "Terminé."
