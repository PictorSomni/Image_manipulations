import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import CONSTANTS

## ─── Dossier par défaut ─────────────────────────────────────────────────────
ORIGIN = "C:\\TEST"

## ─── Extensions d'image acceptées ──────────────────────────────────────────
EXTENSION = (".jpg", ".jpeg", ".png")

## ─── Grille d'images (version Flet) ─────────────────────────────────────────
# Taille maximale d'une cellule de la grille (px) — plus grand = moins d'images par ligne
GRID_MAX_EXTENT = 340
# Ratio hauteur/largeur de chaque cellule (1.0 = carré, < 1.0 = paysage)
GRID_ASPECT_RATIO = 0.82
# Espacement entre les cellules (px)
GRID_SPACING = 12
# Taille des miniatures générées par PIL (px, côté le plus long)
THUMBNAIL_SIZE = 280

## ─── Prévisualisation plein écran ───────────────────────────────────────────
# Résolution max utilisée pour générer la version N&B en prévisualisation plein écran
PREVIEW_NB_SIZE = 1024

## ─── Panneau gauche ─────────────────────────────────────────────────────────
LEFT_PANEL_WIDTH = 210
FORMAT_BUTTON_HEIGHT = 48
ACTION_BUTTON_HEIGHT = 68

## ─── Tarifs d'impression (format : prix en €) ────────────────────────────────
SIZES = {
    "10x15"   : 3.00,
    "13x18"   : 5.50,
    "15x20"   : 7.00,
    "20x30"   : 12.00,
    "30x40"   : 18.00,
    "40x60"   : 28.00,
    "50x70"   : 36.00,
    "60x90"   : 40.00,
    "Montage" : 0.00,
    "Autres"  : 0.00,
}

## ─── Couleurs de l'interface ─────────────────────────────────────────────────
COLOR_DARK         = CONSTANTS.COLOR_DARK
COLOR_BACKGROUND   = CONSTANTS.COLOR_BACKGROUND
COLOR_GREY         = CONSTANTS.COLOR_GREY
COLOR_LIGHT_GREY   = CONSTANTS.COLOR_LIGHT_GREY
COLOR_BLUE         = CONSTANTS.COLOR_BLUE
COLOR_VIOLET       = CONSTANTS.COLOR_VIOLET
COLOR_GREEN        = CONSTANTS.COLOR_GREEN
COLOR_YELLOW       = CONSTANTS.COLOR_YELLOW
COLOR_HOVER_YELLOW = CONSTANTS.COLOR_HOVER_YELLOW
COLOR_ORANGE       = CONSTANTS.COLOR_ORANGE
COLOR_RED          = CONSTANTS.COLOR_RED
COLOR_WHITE        = CONSTANTS.COLOR_WHITE
