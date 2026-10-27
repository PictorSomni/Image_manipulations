#!/bin/bash
# Au démarrage de Claude Code dans ~, valide la question « confiance
# dans ce dossier » (jamais mémorisée pour le dossier personnel).
# Lancé après la création de la session tmux « claude » (crontab @reboot
# et « Relancer Claude » de l'app Claude Pi). N'agit que si la boîte de
# dialogue est affichée : sinon les flèches remonteraient l'historique.
ASK="trust the files in this folder|project you created or one you trust"
for _ in $(seq 60); do
    sleep 1
    pane=$(tmux capture-pane -p -t claude 2>/dev/null) || continue
    grep -qiE "$ASK" <<< "$pane" || continue
    if grep "❯" <<< "$pane" | grep -qiE "yes|accept"; then
        tmux send-keys -t claude Enter
        exit 0
    fi
    tmux send-keys -t claude Down
done
