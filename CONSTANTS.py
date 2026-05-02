# -*- coding: utf-8 -*-
"""
Constantes partagées entre Dashboard.pyw et les scripts du dossier Data/.

Modifier ce fichier pour changer les paramètres globaux de l'application sans
toucher aux scripts eux-mêmes.
"""


# ─── Version ────────────────────────────────────────────────────────────────
VERSION = "2.2.5"


# ─── Interface (Dashboard) ──────────────────────────────────────────────────
WINDOW_WIDTH  = 1280
WINDOW_HEIGHT = 900


# ─── Palette de couleurs ────────────────────────────────────────────────────
# Utilisée dans le terminal intégré et les éléments de l'interface Dashboard.
COLOR_DARK         = "#222429"
COLOR_BACKGROUND   = "#373d4a"
COLOR_GREY         = "#2C3038"
COLOR_LIGHT_GREY   = "#9399A6"
COLOR_BLUE         = "#45B8F5"
COLOR_VIOLET       = "#B587FE"
COLOR_GREEN        = "#49B76C"
COLOR_YELLOW       = "#FBCD5F"
COLOR_HOVER_YELLOW = "#F9BA4E"
COLOR_ORANGE       = "#FFA071"
COLOR_RED          = "#F17171"
COLOR_WHITE        = "#c7ccd8"


# ─── Résolution d'impression ─────────────────────────────────────────────────
DPI = 300   # Points par pouce (ne pas modifier sauf matériel spécifique)


# ─── Formats d'impression ─────────────────────────────────────────────────
FORMATS = { # (largeur_mm, hauteur_mm) - en portrait
    "ID (36x46mm)": (36, 46),
    "9x13 (89x127mm)": (89, 127),
    "10x10 (102x102mm)": (102, 102),
    "10x15 (102x152mm)": (102, 152),
    "13x18 (127x178mm)": (127, 178),
    "15x20 (152x203mm)": (152, 203),
    "15x15 (152x152mm)": (152, 152),
    "18x24 (178x240mm)": (178, 240),
    "20x20 (203x203mm)": (203, 203),
    "20x30 (203x305mm)": (203, 305),
    "A4 (210x297mm)": (210, 297),
    "30x30 (305x305mm)": (305, 305),
    "30x40 (305x405mm)": (305, 405),
    "A3 (297x420mm)": (297, 420),
    "30x45 (305x455mm)": (305, 455),
    "40x50 (405x505mm)": (405, 505),
    "40x60 (405x605mm)": (405, 605),
    "50x70 (505x705mm)": (505, 705),
    "60x80 (605x805mm)": (605, 805),
    "60x90 (605x905mm)": (605, 905),
    "70x100 (705x1005mm)": (705, 1005)
}
# ─── Redimensionnement ───────────────────────────────────────────────────────
RESIZE_DEFAULT = 640   # Dimension max par défaut
RESIZE_QUALITY = 80    # Qualité JPEG des miniatures (0-100)
WATERMARK_ALPHA   = 0.35   # Opacité du filigrane (0.0 = invisible, 1.0 = opaque)


# ─── Remerciements ───────────────────────────────────────────────────────────
# Paramètres du script Remerciements.py (tirage 2-en-1 client).
REMERCIEMENTS_WIDTH   = 76    # Largeur individuelle en mm (doublée en 2-en-1)
REMERCIEMENTS_HEIGHT  = 102   # Hauteur individuelle en mm
REMERCIEMENTS_MAXSIZE = 512   # Dimension max (px) des miniatures remerciements
REMERCIEMENTS_QUALITY = 75    # Qualité JPEG remerciements
REMERCIEMENTS_ALPHA   = 0.42  # Opacité filigrane remerciements


# ─── Formats 2-en-1 ──────────────────────────────────────────────────────────
# Liste ordonnée affichée dans le dialogue Dashboard (premier = valeur par défaut).
# Chaque entrée : (label affiché, "largeurxhauteur" en mm)
TWO_IN_ONE_FORMATS = [
    ("2 10x15 sur 15×20", "102x152"),
    ("2 7x10 sur 10×15",  "76x102"),
    ("2 9x13 sur 13×18",  "89x127"),
    ("2 10x10 sur 10×20", "102x102"),
    ("2 15x20 sur 20×30", "152x203"),
]


# ─── Nettoyage automatique ───────────────────────────────────────────────────
# Utilisée par Nettoyer anciens fichiers.py.
CLEAN_DAYS = 60   # Fichiers plus vieux que N jours sont supprimés
