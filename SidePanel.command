#!/bin/bash
# Lanceur double-clic macOS : s'ouvre dans Terminal (app autorisée au
# micro), contrairement à Python Launcher qui ne peut pas demander la
# permission Microphone à un sous-process — d'où la dictée muette.
cd "$(dirname "$0")"
exec python3 Data/SidePanel.pyw
