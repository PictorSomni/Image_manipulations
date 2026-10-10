#!/bin/bash
# Installation complète en une commande (macOS / Linux) :
#   curl -fsSL https://raw.githubusercontent.com/PictorSomni/Image_manipulations/main/setup.sh | bash
# Installe les prérequis, télécharge Hub dans ~/Image_manipulations,
# installe les dépendances, crée un raccourci et lance Hub.
set -e
REPO=https://github.com/PictorSomni/Image_manipulations.git
DIR="${HUB_DIR:-$HOME/Image_manipulations}"

missing() {
    ! command -v python3 >/dev/null || ! command -v git >/dev/null \
        || ! python3 -c "import venv, ensurepip" 2>/dev/null \
        || { ! command -v magick >/dev/null && ! command -v convert >/dev/null; }
}

if ! missing; then
    :
elif [ "$(uname)" = "Darwin" ]; then
    if ! command -v brew >/dev/null; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv)"
    fi
    brew install python@3.12 git imagemagick
elif command -v apt-get >/dev/null; then
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip git imagemagick
elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 python3-pip git ImageMagick
fi

if [ -d "$DIR/.git" ]; then
    git -C "$DIR" pull --ff-only
else
    git clone --depth 1 "$REPO" "$DIR"
fi
chmod +x "$DIR"/*.sh "$DIR/Hub.command"
"$DIR/install.sh"

# Raccourci
if [ "$(uname)" = "Darwin" ]; then
    ln -sf "$DIR/Hub.command" "$HOME/Desktop/Hub.command"
else
    APPS="$HOME/.local/share/applications"
    mkdir -p "$APPS"
    cat > "$APPS/hub.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Hub
Exec="$DIR/run.sh"
Path=$DIR
Icon=$DIR/assets/icon.png
Terminal=false
DESK
    [ -d "$HOME/Desktop" ] && cp "$APPS/hub.desktop" "$HOME/Desktop/" \
        && chmod +x "$HOME/Desktop/hub.desktop" || true
fi

echo "[OK] Hub est installé. Au premier lancement, renseignez vos identifiants."
nohup "$DIR/run.sh" >/dev/null 2>&1 &
