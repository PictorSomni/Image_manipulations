# -*- coding: utf-8 -*-
"""
Constantes partagées entre Dashboard.pyw, les scripts du dossier Data/,
Selecteur.pyw et kiosk_flet.pyw.

Modifier ce fichier pour changer les paramètres globaux de l'application sans
toucher aux scripts eux-mêmes.
"""


# ─── Version ───────────────────────────────────────────────────────
__version__ = "2.4.4"


# ─── Palette de couleurs ───────────────────────────────────────────────────────────────
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


# ─── Résolution d'impression ───────────────────────────────────────────────────────────────
DPI = 300   # Points par pouce (ne pas modifier sauf matériel spécifique)


# ─── Formats d'impression ───────────────────────────────────────────────────────────────
FORMATS = { # (largeur_mm, hauteur_mm) - en portrait
    "ID": (36, 46),
    "9x13": (89, 127),
    "10x10": (102, 102),
    "10x15": (102, 152),
    "13x18": (127, 178),
    "15x20": (152, 203),
    "15x15": (152, 152),
    "18x24": (178, 240),
    "20x20": (203, 203),
    "20x30": (203, 305),
    "A4": (210, 297),
    "A3": (297, 420),
    "30x30": (305, 305),
    "30x40": (305, 405),
    "30x45": (305, 455),
    "40x50": (405, 505),
    "40x60": (405, 605),
    "50x70": (505, 705),
    "60x80": (605, 805),
    "60x90": (605, 905),
    "70x100": (705, 1005)
}


# ─── Interface (Dashboard) ───────────────────────────────────────────────────────────────
WINDOW_WIDTH                = 1280
WINDOW_HEIGHT               = 940
MAXIMIZED                         =  False 
TERMINAL_FONT_SIZE       = 16   # Taille du texte dans le terminal, le bloc-notes et les options
TERMINAL_HEIGHT          = 170  # Hauteur du panneau terminal compact (px) - toujours visible
WDA_HEIGHT               = 96   # Hauteur de la WindowDragArea (barre de titre custom, en px)


# ─── Redimensionnement ───────────────────────────────────────────────────────────────
RESIZE_DEFAULT = 640   # Dimension max par défaut - y compris pour remerciements
RESIZE_QUALITY = 80    # Qualité JPEG des miniatures (0-100)
WATERMARK_ALPHA   = 0.35   # Opacité du filigrane (0.0 = invisible, 1.0 = opaque)


# ─── Remerciements ───────────────────────────────────────────────────────────────
# Paramètres du script Remerciements.py (tirage 2-en-1 client).
REMERCIEMENTS_WIDTH   = 76    # Largeur individuelle en mm (doublée en 2-en-1)
REMERCIEMENTS_HEIGHT  = 102   # Hauteur individuelle en mm
REMERCIEMENTS_QUALITY = 75    # Qualité JPEG remerciements
REMERCIEMENTS_ALPHA   = 0.42  # Opacité filigrane remerciements


# ─── Formats 2-en-1 ───────────────────────────────────────────────────────────────
# Liste ordonnée affichée dans le dialogue Dashboard (premier = valeur par défaut).
# Chaque entrée : (label affiché, "largeurxhauteur" en mm)
TWO_IN_ONE_FORMATS = [
    ("2 10x15 sur 15×20", "102x152"),
    ("2 7x10 sur 10×15",  "76x102"),
    ("2 9x13 sur 13×18",  "89x127"),
    ("2 10x10 sur 10×20", "102x102"),
    ("2 15x20 sur 20×30", "152x203"),
]


# ─── Formats Fit 203 ───────────────────────────────────────────────────────────────
# Liste ordonnée affichée dans le dialogue Dashboard (premier = valeur par défaut).
# Chaque entrée : (label affiché, "largeurxhauteur" en mm, "largeurxhauteur" du canvas en mm)
FIT_203_FORMATS = [
    ("10x15 sur 10×20", "102x152", "102x203"),
    ("13x18 sur 13x20",  "127x178", "127x203"),
    ("18x24 sur 20x24",  "180x240", "200x240"),
]


# ─── Dossier TEMP ───────────────────────────────────────────────────────────────
# Destination par défaut pour le transfert de fichiers (Transfert vers TEMP.py).
# Peut être surchargé via la variable d'environnement DEST_FOLDER.
TEMP_FOLDER = "Z:/temp"


# ─── Nettoyage automatique ───────────────────────────────────────────────────────────────
# Utilisée par Nettoyer anciens fichiers.py.
CLEAN_DAYS = 60   # Fichiers plus vieux que N jours sont supprimés


# ─── Chemins réseau kiosks ───────────────────────────────────────────────────────────────
# Utilisés par Kiosk gauche.py, Kiosk droite.py et Nettoyer anciens fichiers.py.
import platform as _platform

def _resolve_macos_volume(base_name: str) -> str:
    """Résout le chemin réel d'un volume macOS monté dans /Volumes/.
    macOS peut ajouter un suffixe '-1', '-2', etc. si le nom est déjà pris.
    Retourne le premier chemin existant, ou le nom de base si aucun n'est monté."""
    import os as _os
    candidates = [base_name] + [f"{base_name}-{i}" for i in range(1, 5)]
    for name in candidates:
        path = f"/Volumes/{name}"
        if _os.path.ismount(path):
            return path
    return f"/Volumes/{base_name}"

if _platform.system() == "Windows":
    KIOSK_GAUCHE_SRC  = r"\\studioc-kiosk1\kiosk-data\it-HotFolder"
    KIOSK_GAUCHE_DEST = r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK GAUCHE"
    KIOSK_DROITE_SRC  = r"\\studioc-kiosk2\kiosk-data\it-HotFolder"
    KIOSK_DROITE_DEST = r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK DROITE"
    CLEAN_FOLDERS = [
        r"\\studioc-kiosk1\kiosk-data\it-HotFolder",
        r"\\studioc-kiosk2\kiosk-data\it-HotFolder",
        r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK GAUCHE",
        r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK DROITE",
        r"\\diskstation\travaux en cours\Z2026\TEMP",
    ]
else:
    _travaux = _resolve_macos_volume("TRAVAUX EN COURS")
    KIOSK_GAUCHE_SRC  = "/Volumes/kiosk-data/it-HotFolder"
    KIOSK_GAUCHE_DEST = f"{_travaux}/Z2026/KIOSK/KIOSK GAUCHE"
    KIOSK_DROITE_SRC  = "/Volumes/kiosk-data-1/it-HotFolder"
    KIOSK_DROITE_DEST = f"{_travaux}/Z2026/KIOSK/KIOSK DROITE"
    TEMP_FOLDER       = f"{_travaux}/Z2026/TEMP"
    CLEAN_FOLDERS = [
        "/Volumes/kiosk-data-1/it-HotFolder",
        "/Volumes/kiosk-data-2/it-HotFolder",
        f"{_travaux}/Z2026/KIOSK/KIOSK GAUCHE",
        f"{_travaux}/Z2026/KIOSK/KIOSK DROITE",
        f"{_travaux}/Z2026/TEMP",
    ]
del _platform


# ─── Intelligence artificielle (Ollama) ───────────────────────────────────────────
# L'IA locale utilise Ollama (https://ollama.com).
# Installez Ollama puis téléchargez un modèle : ollama pull llama3.2:3b
#
# Recommandations par niveau de machine :
#   Très petite (2-4 GB RAM)  : gemma2:2b (~1.6 GB)  ou  qwen2.5:0.5b (~400 MB)
#   Petite      (4-8 GB RAM)  : phi3:mini (~2.3 GB)  ou  llama3.2:3b (~2 GB)
#   Moyenne     (8-16 GB RAM) : mistral:7b (~4.1 GB) ou  qwen2.5:7b (~4.4 GB)
#   Bonne       (16 GB+ RAM)  : llama3.1:8b (~4.7 GB) ou deepseek-r1:8b (~4.9 GB)

AI_OLLAMA_URL   = "http://localhost:11434"   # URL de l'API Ollama locale
AI_MODEL_TEXT   = "gemma4:e4b"             # Modèle texte + vision (~9.6 GB) — recommandé
AI_MODEL_VISION = "gemma4:e4b"             # Modèle vision     (~9.6 GB)
AI_TEMPERATURE  = 0.7                        # Créativité (0.0 = déterministe, 1.0 = créatif)
AI_URL_MAX_CHARS = 12_000                    # Nb max de caractères extraits d'une URL (augmenter si le modèle a un grand contexte)
AI_SYSTEM_PROMPT = "On peut se tutoyer."

# Modèles disponibles – (label affiché, nom Ollama, supporte_vision)
# Modifiez AI_MODEL ci-dessus selon la config de la machine.
AI_AVAILABLE_MODELS = [
    # ── Gemma 4 — texte + vision natif (Google, 2025) ───────────────────────────────────
    ("Gemma 4 E4B  (recommandé, ~9.6 GB) 🖼",            "gemma4:e4b",          True),
    ("Gemma 4 E2B  (légère, ~7.2 GB) 🖼",                "gemma4:e2b",          True),
    ("Gemma 4 · 26B MoE  (~18 GB) 🖼",                   "gemma4:26b",          True),
    # ── Vision uniquement ─────────────────────────────────────────────────
    ("LLaVA-Phi3 · 3.8B  (~2.9 GB) 🖼",                  "llava-phi3",          True),
    ("LLaVA · 7B  (~4.1 GB) 🖼",                         "llava:7b",            True),
    ("Llama 3.2 Vision · 11B  (~8 GB) 🖼",               "llama3.2-vision:11b", True),
    ("Moondream 2  (légère, ~1.8 GB) 🖼",                 "moondream2",          True),
    # ── Texte uniquement ─────────────────────────────────────────────────
    ("Llama 3.1 · 8B  (~4.7 GB)",                        "llama3.1:8b",         False),
    ("Llama 3.2 · 3B  (~2 GB)",                          "llama3.2:3b",         False),
    ("Mistral 7B  (~4.1 GB)",                            "mistral:7b",          False),
    ("Phi-3 Mini · 3.8B  (~2.3 GB)",                     "phi3:mini",           False),
    ("Qwen 2.5 · 7B  (~4.4 GB)",                         "qwen2.5:7b",          False),
    ("Gemma 2 · 2B  (~1.6 GB)",                          "gemma2:2b",           False),
    ("Qwen 2.5 · 0.5B  (très légère, ~400 MB)",          "qwen2.5:0.5b",        False),
]

# Ensemble des noms de modèles supportant la vision (pour vérification rapide)
AI_VISION_MODELS = {entry[1] for entry in AI_AVAILABLE_MODELS if entry[2]}



#══════════════════════════════════════════════════════════════
#  KIOSK
#══════════════════════════════════════════════════════════════
# ─── Extensions d'image acceptées (kiosk) ────────────────────────────────────────
EXTENSION = (".jpg", ".jpeg", ".png")

# ─── Grille d'images (kiosk, version Flet) ─────────────────────────────────────────
# Taille maximale d'une cellule de la grille (px) — plus grand = moins d'images par ligne
GRID_MAX_EXTENT = 340
# Ratio hauteur/largeur de chaque cellule (1.0 = carré, < 1.0 = paysage)
GRID_ASPECT_RATIO = 0.82
# Espacement entre les cellules (px)
GRID_SPACING = 12
# Taille des miniatures générées par PIL (px, côté le plus long)
THUMBNAIL_SIZE = 280

# ─── Prévisualisation plein écran (kiosk) ─────────────────────────────────────────
# Résolution max utilisée pour générer la version N&B en prévisualisation plein écran
PREVIEW_NB_SIZE = 1024

# ─── Panneau gauche (kiosk) ───────────────────────────────────────────────────────────────
LEFT_PANEL_WIDTH = 210
FORMAT_BUTTON_HEIGHT = 48
ACTION_BUTTON_HEIGHT = 68

# ─── Tarifs d'impression (kiosk, format : prix en €) ────────────────────────────────────
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
