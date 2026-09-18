#!/usr/bin/env bash
#
# clean_macos.sh - Nettoyage des fichiers temporaires et caches sous macOS
#
# Usage :
#   ./clean_macos.sh              # tout nettoie directement, sans demander
#   ./clean_macos.sh --dry-run    # affiche ce qui serait supprimé, sans rien supprimer
#   ./clean_macos.sh --interactive  # redemande confirmation étape par étape

set -uo pipefail
# Pas de "set -e" : une étape en échec (permission refusée, brew/xcrun absent
# ou en erreur, sudo qui échoue...) ne doit pas arrêter tout le script avant
# les dossiers suivants (retour user : il fallait relancer plusieurs fois).

DRY_RUN=false
AUTO_YES=true

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --interactive) AUTO_YES=false ;;
        --yes|-y) AUTO_YES=true ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--interactive]"
            exit 0
            ;;
        *)
            echo "Option inconnue : $arg" >&2
            exit 1
            ;;
    esac
done

if [[ "$(uname)" != "Darwin" ]]; then
    echo "Ce script est prévu pour macOS uniquement." >&2
    exit 1
fi

confirm() {
    local message="$1"
    if [[ "$AUTO_YES" == true ]]; then
        return 0
    fi
    read -r -p "$message [y/N] " reponse
    [[ "$reponse" =~ ^[Yy]$ ]]
}

run_or_echo() {
    if [[ "$DRY_RUN" == true ]]; then
        echo "[dry-run] $*"
    else
        eval "$@" || echo "  (échec sur cette étape, on continue)"
    fi
}

human_size() {
    local path="$1"
    if [[ -e "$path" ]]; then
        du -sh "$path" 2>/dev/null | cut -f1
    else
        echo "0B"
    fi
}

echo "=== Nettoyage macOS ==="
[[ "$DRY_RUN" == true ]] && echo "(mode dry-run : aucune suppression ne sera effectuée)"
echo

# 1. Cache utilisateur
USER_CACHE="$HOME/Library/Caches"
echo "Cache utilisateur ($USER_CACHE) : $(human_size "$USER_CACHE")"
if confirm "Vider le cache utilisateur ?"; then
    run_or_echo "rm -rf \"$USER_CACHE\"/*"
fi
echo

# 2. Logs utilisateur
USER_LOGS="$HOME/Library/Logs"
echo "Logs utilisateur ($USER_LOGS) : $(human_size "$USER_LOGS")"
if confirm "Vider les logs utilisateur ?"; then
    run_or_echo "rm -rf \"$USER_LOGS\"/*"
fi
echo

# 3. Corbeille
TRASH="$HOME/.Trash"
echo "Corbeille ($TRASH) : $(human_size "$TRASH")"
if confirm "Vider la corbeille ?"; then
    run_or_echo "rm -rf \"$TRASH\"/*"
fi
echo

# 4. DerivedData Xcode (si présent)
XCODE_DERIVED="$HOME/Library/Developer/Xcode/DerivedData"
if [[ -d "$XCODE_DERIVED" ]]; then
    echo "DerivedData Xcode ($XCODE_DERIVED) : $(human_size "$XCODE_DERIVED")"
    if confirm "Vider les DerivedData Xcode ?"; then
        run_or_echo "rm -rf \"$XCODE_DERIVED\"/*"
    fi
    echo
fi

# 5. Simulateurs iOS non disponibles (si xcrun présent)
if command -v xcrun >/dev/null 2>&1; then
    if confirm "Supprimer les simulateurs iOS indisponibles (xcrun simctl delete unavailable) ?"; then
        run_or_echo "xcrun simctl delete unavailable"
    fi
    echo
fi

# 6. Cache Homebrew (si installé)
if command -v brew >/dev/null 2>&1; then
    if confirm "Nettoyer le cache Homebrew (brew cleanup) ?"; then
        run_or_echo "brew cleanup"
    fi
    echo
fi

# 7. Cache DNS (nécessite sudo)
if confirm "Vider le cache DNS (nécessite sudo) ?"; then
    run_or_echo "sudo dscacheutil -flushcache"
    run_or_echo "sudo killall -HUP mDNSResponder"
fi
echo

# 8. Cache système (nécessite sudo, plus sensible)
SYSTEM_CACHE="/Library/Caches"
echo "Cache système ($SYSTEM_CACHE) : $(human_size "$SYSTEM_CACHE")"
if confirm "Vider le cache système (nécessite sudo) ?"; then
    run_or_echo "sudo rm -rf \"$SYSTEM_CACHE\"/*"
fi
echo

echo "=== Nettoyage terminé ==="
