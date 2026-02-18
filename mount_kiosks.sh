#!/bin/bash
# Script de montage des partages SMB pour les kiosks
# À exécuter au démarrage du Mac

USER="StudioC"

# Points de montage
MOUNT1="/Volumes/kiosk1-hotfolder"
MOUNT2="/Volumes/kiosk2-hotfolder"

# Création des points de montage si nécessaire
mkdir -p "$MOUNT1"
mkdir -p "$MOUNT2"

# Démontage si déjà montés (évite les erreurs)
umount "$MOUNT1" 2>/dev/null
umount "$MOUNT2" 2>/dev/null

# Montage des partages
echo "Montage de kiosk1 (GAUCHE)..."
mount_smbfs "//${USER}@studioc-kiosk1/kiosk-data/it-HotFolder" "$MOUNT1"
if [ $? -eq 0 ]; then
    echo "✓ Kiosk1 monté sur $MOUNT1"
else
    echo "✗ Échec du montage de kiosk1"
fi

echo "Montage de kiosk2 (DROITE)..."
mount_smbfs "//${USER}@studioc-kiosk2/kiosk-data/it-HotFolder" "$MOUNT2"
if [ $? -eq 0 ]; then
    echo "✓ Kiosk2 monté sur $MOUNT2"
else
    echo "✗ Échec du montage de kiosk2"
fi

echo ""
echo "Montages terminés."
