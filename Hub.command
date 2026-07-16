#!/bin/bash
# Lanceur double-clic macOS : s'ouvre dans Terminal (app autorisée au
# micro), contrairement à Python Launcher qui ne peut pas demander la
# permission Microphone à un sous-process — d'où la dictée muette.
cd "$(dirname "$0")"
python3 Hub.pyw
# Ferme cette fenêtre Terminal (identifiée par son tty, pas les autres
# fenêtres ouvertes) une fois Hub.pyw quitté — sans ça la fenêtre reste
# ouverte avec "[Process completed]" (retour user).
osascript -e 'tell application "Terminal" to close (every window whose tty is "'"$(tty)"'")' &
exit 0
