# -*- coding: utf-8 -*-
"""
Constantes partagées entre Dashboard.pyw, les scripts du dossier Data/,
SidePanel.pyw et kiosk_flet.pyw.

Modifier ce fichier pour changer les paramètres globaux de l'application sans
toucher aux scripts eux-mêmes.
"""


# ─── Version ───────────────────────────────────────────────────────
__version__ = "2.6.5"


# ─── Extensions de fichiers ────────────────────────────────────────────────────────────
IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".ico", ".tiff", ".tif",
})
NOTEPAD_EXTS = frozenset({
    ".txt", ".md", ".log", ".ini", ".cfg", ".yaml", ".yml",
    ".rtf", ".py", ".toml", ".sh", ".bat", ".csv",
})
AI_DOCUMENT_EXTS = frozenset({
    ".txt", ".md", ".py", ".js", ".ts", ".json", ".csv", ".xml",
    ".html", ".htm", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".rst", ".pdf", ".docx", ".doc", ".rtf", ".odt",
})
AI_AUDIO_EXTS = frozenset({
    ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".opus", ".wma",
})
ROTATABLE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
})


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

# ─── Planche ID X4 en 10x20 ───────────────────────────────────────────────────────────────
# True  = 4 photos dans la moitié BASSE  (moitié haute blanche) — défaut imprimante bas
# False = 4 photos dans la moitié HAUTE (moitié basse blanche)
ID_X4_10x20_PHOTOS_BOTTOM = True


# ─── Performance de prévisualisation ─────────────────────────────────────────────────────────
# Taille maximale (en pixels, côté le plus long) de l'image de prévisualisation dans
# Recadrage.pyw. Une valeur plus élevée améliore la netteté au zoom mais ralentit le rendu.
# Réduire sur les machines moins puissantes (ex. 1200 = taille canvas exacte).
PREVIEW_MAX_PIXELS = 1024

# ─── Cache partagé de miniatures ─────────────────────────────────────────────────────────────
# Utilisé par Dashboard.pyw, SidePanel.pyw et kiosk_flet.pyw via thumb_cache.py.
# Un fichier SQLite (THUMB_CACHE_DB_NAME) est créé dans chaque dossier d'images.
THUMB_CACHE_SIZE    = 280   # Taille (px, côté le plus long) des miniatures mises en cache
THUMB_CACHE_QUALITY = 60    # Qualité JPEG du cache (0-100) — augmenter pour plus de détails
THUMB_CACHE_DB_NAME = ".thumbcache.db"  # Nom du fichier SQLite dans chaque dossier


# ─── Formats d'impression ───────────────────────────────────────────────────────────────
FORMATS = { # (largeur_mm, hauteur_mm) - en portrait
    "ID": (36, 46),
    "9x13": (89, 127),
    "10x10": (102, 102),
    "10x15": (102, 152),
    "13x13": (127, 127),
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
WINDOW_WIDTH             = 1300
WINDOW_HEIGHT            = 910
MAXIMIZED                =  True 
TERMINAL_FONT_SIZE       = 16   # Taille du texte dans le terminal, le bloc-notes et les options
TERMINAL_HEIGHT          = 170  # Hauteur du panneau terminal compact (px) - toujours visible
WDA_HEIGHT               = 100   # Hauteur de la WindowDragArea (barre de titre custom, en px)


# ─── Redimensionnement ───────────────────────────────────────────────────────────────
RESIZE_DEFAULT = 640   # Dimension max par défaut - y compris pour remerciements
RESIZE_QUALITY = 80    # Qualité JPEG des miniatures (0-100)
DASHBOARD_THUMB_SIZE = 50  # Taille des miniatures dans le panneau de prévisualisation (px)
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

# ─── Comportement ZIP ─────────────────────────────────────────────────────────────────────
# True  = supprime directement le .zip source après décompression (sans confirmation)
# False = affiche une boîte de dialogue Oui/Non avant de supprimer
DELETE_ZIP_AFTER_EXTRACT = True


# ─── Chemins réseau kiosks ───────────────────────────────────────────────────────────────
# Utilisés par Kiosk gauche.py, Kiosk droite.py et Nettoyer anciens fichiers.py.
import platform as _platform

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
    import os as _os
    _travaux = "/Volumes/TRAVAUX EN COURS"
    if not _os.path.ismount(_travaux):
        for _suffix in ["-1", "-2", "-3", "-4"]:
            _candidate = f"{_travaux}{_suffix}"
            if _os.path.ismount(_candidate):
                _travaux = _candidate
                break
    del _os
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
# Installez Ollama puis téléchargez un modèle : ollama pull gemma4:e4b

AI_OLLAMA_URL   = "http://localhost:11434"   # URL de l'API Ollama locale
AI_MODEL_TEXT   = "gemini-3.5-flash"         # Modèle texte par défaut
AI_MODEL_VISION = "gemini-3.5-flash"         # Modèle vision par défaut
AI_GEMINI_MODEL    = "gemini-3.5-flash"      # Modèle Gemini principal (API Google)
AI_GEMINI_FALLBACK = "gemma4:e4b"            # Fallback Ollama local si hors-ligne
AI_TEMPERATURE  = 0.7                        # Créativité (0.0 = déterministe, 1.0 = créatif)
AI_URL_MAX_CHARS = 12_000                    # Nb max de caractères extraits d'une URL (augmenter si le modèle a un grand contexte)
AI_ORGANIZE_CONFIRM  = False                  # True = dialog de confirmation avant chaque tri de fichiers ; False = exécution directe
AI_TERMINAL_CONFIRM = False                   # True = dialog de confirmation avant chaque commande terminal ; False = exécution directe
AI_FOLDER_SELECT_BATCH_SIZE = 5              # Nb d'images par appel IA (Ollama) — petits lots de 5 pour feedback fréquent et attention maximale par image
AI_GEMINI_FOLDER_BATCH_SIZE = 20            # Nb d'images par appel IA (Gemini) — lots plus grands, contexte large et quota par requête
AI_FOLDER_SELECT_IMAGE_SIZE = 800           # Résolution max (px) — 1024 pour bien distinguer netteté, expressions, exposition
AI_FOLDER_SELECT_QUALITY    = 70             # Qualité JPEG des images envoyées à l'IA pour l'analyse
AI_FOLDER_SELECT_SYSTEM_PROMPT = (
    "Tu es un éditeur photo professionnel spécialisé dans la sélection avant développement RAW.\n\n"
    "CONTEXTE IMPORTANT :\n"
    "Base ta sélection sur le POTENTIEL de chaque image (composition, contrastes, lumière, couleur, expression, moment) "
    "et non sur son rendu final. L'utilisateur retouchera ensuite les fichiers RAW correspondants.\n\n"
    "Il s'agit soit d'un reportage photo (événement, mariage, portrait…), soit des paysages / ambiances."
    "Si tu vois une série de portraits, il est probablement composé de personnes différentes (même si certaines sont toujours mises en avant) — "
    "Tu analyses le reportage par petits groupes successifs ; "
    "applique des critères cohérents à travers tous les groupes.\n\n"
    "CRITÈRES D'EXCLUSION (écarte uniquement si le défaut est clairement visible) :\n"
    "- Photos nettement floues ou avec un mouvement non intentionnel sur le sujet principal\n"
    "- Ombres complètement bouchées sans aucun détail récupérable\n"
    "- Yeux clairement fermés sur le/les sujet(s) principal(aux)\n"
    "- Mise au point clairement manquée sur le sujet principal\n"
    "- Cadrage clairement raté (sujet tronqué de façon non artistique, horizon très fortement penché)\n"
    "- Photos quasi-identiques prises en rafale du MÊME instant et du MÊME sujet "
    "(même cadre, même milliseconde) — ne retenir que la meilleure. "
    "NE PAS confondre avec des portraits de personnes différentes.\n\n"
    "CRITÈRES DE SÉLECTION POSITIFS :\n"
    "- Netteté sur le sujet principal (même légèrement plate en JPEG brut)\n"
    "- Exposition maîtrisée — un style lumineux, clair ou high-key est une qualité, pas un défaut\n"
    "- Expression authentique, émotion ou moment décisif\n"
    "- Composition équilibrée ou cadrage intéressant\n\n"
    "QUANTITÉ : sélectionne entre 30 % et 60 % des photos du groupe. "
    "Ne renvoie jamais une liste vide sauf si TOUTES les photos du groupe "
    "présentent un défaut rédhibitoire (flou net, yeux fermés, hors sujet total).\n\n"
    "OBLIGATION ABSOLUE : tu DOIS appeler l'outil select_photos avec le paramètre "
    "selected_files contenant EXPLICITEMENT le nom exact de chaque fichier retenu "
    "(ex. NZ6_0176.jpeg). "
    "Ne jamais écrire les noms uniquement dans le champ reason ou dans le texte libre. "
    "Si tu mentionnes dans reason que tu as sélectionné des photos, ces mêmes photos "
    "DOIVENT obligatoirement figurer dans selected_files — sinon elles seront perdues."
)
AI_USER_NAME    = "Charles"                      # Appellation de l'utilisateur dans l'export de conversation
AI_SEPARATOR_WIDTH = 80                      # Nombre de '#' pour les séparateurs de l'export de conversation
AI_SYSTEM_PROMPT = (
    f"On se tutoie. Tu parles à {AI_USER_NAME}.\n\n"
    "CAPACITÉS :\n"
    "Tu peux accéder à internet (web_search, fetch_url) et aux fichiers du dossier ouvert "
    "— les lister, lire leur contenu, les organiser par sous-dossiers, ou analyser visuellement les images.\n\n"
    "RÈGLES :\n"
    "- Pas de disclaimers ni de mises en garde inutiles (pas de 'consulte un professionnel', 'je ne suis pas médecin', etc.).\n"
    "- Si tu ne connais pas la réponse, fais une recherche web plutôt que d'inventer.\n"
    "- Cite toujours tes sources avec les URLs complètes quand tu fais une recherche web.\n"
    "- Les images que tu reçois sont des miniatures réduites : ne tire pas de conclusions sur la netteté ou le piqué "
    "de l'original — un flou apparent peut n'être dû qu'à la réduction de résolution.\n"
    "- Quand tu organises des fichiers, explique ta logique clairement.\n\n"
    "Reste naturel et engageant, n'hésite pas à utiliser des émoticônes ou de l'humour quand c'est pertinent."
)


# Modèles disponibles – (label affiché, identifiant, supporte_vision)
AI_AVAILABLE_MODELS = [
    ("Gemini 3.5 Flash  🌐🖼",        "gemini-3.5-flash", True),
    ("Gemma 4 E4B  (~9.6 GB) 🖼",    "gemma4:e4b",       True),
    ("Gemma 4 · 26B  (~18 GB) 🖼",   "gemma4:26b",       True),
    ("DeepSeek-R1 · 8B  (~5.2 GB)",  "deepseek-r1:8b",   False),
    ("DeepSeek-R1 · 14B  (~9 GB)",   "deepseek-r1:14b",  False),
]

# Modèles affichés dans le dropdown de sélection rapide du Dashboard.
AI_DROPDOWN_MODELS = [
    "gemini-3.5-flash",
    "gemma4:e4b",
]



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

STUDIOS = {
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

PRINTS = {
    "10x15"   : [0.50, 0.40, 0.35, 0.30, 0.25],  # Prix dégressif selon la quantité (<10, 11>50, 51>100, 101>200, >200)
    "13x18"   : [1.50, 1.40, 1.35, 1.30, 1.25],
    "15x20"   : [2.50, 2.20, 2.00, 1.80, 1.60],
    "20x30"   : [4.90, 4.70, 4.50, 4.30, 4.10],
    "30x40"   : [12.90, 12.50, 12.00, 11.50, 11.00],
    "40x60"   : [24.90, 24.50, 24.00, 23.50, 23.00],
    "50x70"   : [28.00, 26.50, 25.00, 24.50, 24.00],
    "60x90"   : [30.00, 29.50, 29.00, 28.50, 28.00],
}

SIZES = STUDIOS  # Alias conservé pour compatibilité ascendante