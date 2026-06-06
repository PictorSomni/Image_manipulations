# -*- coding: utf-8 -*-
"""
Constantes partagées entre Dashboard.pyw, les scripts du dossier Data/,
SidePanel.pyw et kiosk_flet.pyw.

Modifier ce fichier pour changer les paramètres globaux de l application sans
toucher aux scripts eux-mêmes.
"""

# ==============================================================================
# TABLE DES MATIÈRES
# ==============================================================================
# 1. VERSION ................................................... ~L  20
# 2. FICHIERS & EXTENSIONS .................................... ~L  25
# 3. COULEURS ................................................. ~L  45
# 4. IMPRESSION ............................................... ~L  65
#    4.1  Résolution DPI
#    4.2  Formats d impression
#    4.3  Planche ID X4
#    4.4  2-en-1 et Fit 203
# 5. RECADRAGE MANUEL.PYW ...................................... ~L 115
#    5.1  Performance de prévisualisation
#    5.2  Toggles (états initiaux)
#    5.3  Réglages image par défaut
# 6. INTERFACE (DASHBOARD) .................................... ~L 185
#    6.1  Fenêtre principale
#    6.2  Redimensionnement et filigrane
#    6.3  Remerciements
# 7. FICHIERS & DOSSIERS ...................................... ~L 215
#    7.1  Dossier TEMP
#    7.2  Nettoyage automatique
#    7.3  Comportement ZIP
# 8. RÉSEAU & KIOSKS .......................................... ~L 230
# 9. CACHE DE MINIATURES ...................................... ~L 270
# 10. INTELLIGENCE ARTIFICIELLE ............................... ~L 285
#     10.1 Modèles et paramètres
#     10.2 Prompts système
#     10.3 Voix - TTS (synthèse vocale Gemini)
# 11. KIOSK FLET .............................................. ~L 390
#     11.1 Extensions et grille
#     11.2 Panneau gauche
#     11.3 Tarifs d impression
# ==============================================================================


# ==============================================================================
# 1. VERSION
# ==============================================================================

__version__ = "2.7.6"


# ==============================================================================
# 2. FICHIERS & EXTENSIONS
# ==============================================================================

IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".ico", ".tiff", ".tif",
})
NOTEPAD_EXTS = frozenset({
    ".txt", ".md", ".log", ".ini", ".cfg", ".yaml", ".yml",
    ".rtf", ".py", ".pyw", ".toml", ".sh", ".bat", ".csv",
})
AI_DOCUMENT_EXTS = frozenset({
    ".txt", ".md", ".py", ".pyw", ".js", ".ts", ".json", ".csv", ".xml",
    ".html", ".htm", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".log",
    ".rst", ".pdf", ".docx", ".doc", ".rtf", ".odt",
})
ROTATABLE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp",
})


# ==============================================================================
# 3. COULEURS
# ==============================================================================
# Palette utilisée dans le terminal intégré et les éléments d'interface.

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


# ==============================================================================
# 4. IMPRESSION
# ==============================================================================

# ── 4.1  Résolution DPI ───────────────────────────────────────────────────────

DPI = 300   # Points par pouce (ne pas modifier sauf matériel spécifique)


# ── 4.2  Formats d'impression ─────────────────────────────────────────────────
# (largeur_mm, hauteur_mm) en portrait

FORMATS = {
    "ID"     : (36,  46),
    "9x13"   : (89,  127),
    "10x10"  : (102, 102),
    "10x15"  : (102, 152),
    "10x20"  : (102, 203),
    "13x13"  : (127, 127),
    "13x15"  : (127, 152),
    "13x18"  : (127, 178),
    "13x20"  : (127, 203),
    "15x20"  : (152, 203),
    "15x15"  : (152, 152),
    "18x24"  : (178, 240),
    "20x20"  : (203, 203),
    "20x24"  : (203, 240),
    "20x30"  : (203, 305),
    "A4"     : (210, 297),
    "A3"     : (297, 420),
    "30x30"  : (305, 305),
    "30x40"  : (305, 405),
    "30x45"  : (305, 455),
    "40x40"  : (405, 405),
    "40x50"  : (405, 505),
    "40x60"  : (405, 605),
    "50x50"  : (505, 505),
    "50x70"  : (505, 705),
    "60x80"  : (605, 805),
    "60x90"  : (605, 905),
    "70x100" : (705, 1005),
}


# ── 4.3  Planche ID X4 ────────────────────────────────────────────────────────
# True  = 4 photos dans la moitié BASSE  (moitié haute blanche) — défaut imprimante bas
# False = 4 photos dans la moitié HAUTE  (moitié basse blanche)

ID_X4_10x20_PHOTOS_BOTTOM = True


# ── 4.4  Formats 2-en-1 et Fit 203 ───────────────────────────────────────────
# Liste ordonnée affichée dans le dialogue Dashboard (premier = valeur par défaut).

TWO_IN_ONE_FORMATS = [
    ("2 10x15 sur 15x20", "102x152"),
    ("2 7x10 sur 10x15",  "76x102"),
    ("2 9x13 sur 13x18",  "89x127"),
    ("2 10x10 sur 10x20", "102x102"),
    ("2 15x20 sur 20x30", "152x203"),
]

# Chaque entree : (label affiche, "LxH" en mm, "LxH" du canvas en mm)
FIT_203_FORMATS = [
    ("10x15 sur 10x20", "102x152", "102x203"),
    ("13x18 sur 13x20", "127x178", "127x203"),
    ("18x24 sur 20x24", "180x240", "200x240"),
]


# ==============================================================================
# 5. RECADRAGE MANUEL.PYW
# ==============================================================================

# ── 5.1  Performance de prévisualisation ──────────────────────────────────────
# Taille maximale (px, côté le plus long) de l'image de prévisualisation.
# Réduire sur les machines moins puissantes (ex. 800 pour les petits écrans).

PREVIEW_MAX_PIXELS = 1024


# ── 5.2  Affichage et hauteurs de panneaux ────────────────────────────────────
# Désactiver l'histogramme permet de gagner de la place verticale et d'éviter
# son recalcul pendant les rafraîchissements du preview.

RECADRAGE_SHOW_HISTOGRAM       = False   # Afficher et calculer l'histogramme
RECADRAGE_FORMAT_LIST_HEIGHT    = 350    # Hauteur de la liste des formats
RECADRAGE_CUSTOM_PANEL_HEIGHT   = 110     # Hauteur du panneau Dimensions (mm)


# ── 5.2  Toggles — états initiaux ─────────────────────────────────────────────
# Chaque constante correspond à l'état initial d'un toggle (Switch ou bouton).

RECADRAGE_TWO_IN_ONE      = False   # 2-en-1 (formats 10x15, 13x18, 15x20)
RECADRAGE_BORDER_13x15    = False   # Mise en page 13x15 (format 10x15)
RECADRAGE_BORDER_10x20    = False   # Mise en page 10x20 (format 10x15)
RECADRAGE_BORDER_13x20    = False   # Mise en page 13x20 (format 13x18)
RECADRAGE_BORDER_20x24    = False   # Mise en page 20x24 (format 18x24)
RECADRAGE_BORDER_13x10    = False   # Mise en page 13x10 (format 10x10)
RECADRAGE_BORDER_POLAROID = False   # Mise en page Polaroid (format 10x10)
RECADRAGE_BORDER_ID2      = False   # Planche ID X2
RECADRAGE_BORDER_ID4      = True    # Planche ID X4
RECADRAGE_ID4_10x20       = True    # Format 10x20 pour la planche ID X4
RECADRAGE_SAVE_TO_NETWORK = True    # Sauvegarder les ID X4 sur le réseau par défaut
RECADRAGE_IS_BW           = False   # Noir et blanc
RECADRAGE_IS_SHARPEN      = True    # Netteté activée
RECADRAGE_FIT_IN          = False   # Mode Fit-in (image entière dans le format)
RECADRAGE_SHOW_GRID       = True    # Afficher la grille de cadrage
RECADRAGE_REMBG_BG_WHITE  = True    # Fond blanc après suppression IA (vs flou)
RECADRAGE_REMBG_HUMAN_SEG = True    # Segmentation humain (vs généraliste)
RECADRAGE_REMBG_PRECISE   = False   # Mode précis/lent (birefnet) vs rapide (u2net)
RECADRAGE_SCROLL_ROTATES  = False   # Molette = rotation (Tab pour basculer)


# ── 5.3  Réglages image — valeurs par défaut ──────────────────────────────────

RECADRAGE_DEFAULT_CONTRAST      =   0   # Contraste       (-20 ... +20)
RECADRAGE_DEFAULT_SATURATION    =  30   # Saturation      (-100 ... +100)
RECADRAGE_DEFAULT_EXPOSURE      =  10   # Exposition      (-100 ... +100)
RECADRAGE_DEFAULT_SHADOWS       =  20   # Ombres          (-100 ... +100)
RECADRAGE_DEFAULT_HIGHLIGHTS    =   0   # Hautes lumières (-100 ... +100)
RECADRAGE_DEFAULT_HUE           =   0   # Teinte          (-180 ... +180)
RECADRAGE_DEFAULT_WHITE_BALANCE =   0   # Balance blancs  (-100 ... +100)

# Recadrage automatique (mode fit) : ecart entre les tuiles (mm)
RECADRAGE_FORCE_TILE_GAP_MM = 3


# ==============================================================================
# 6. INTERFACE (DASHBOARD)
# ==============================================================================

# ── 6.1  Fenêtre principale ───────────────────────────────────────────────────

WINDOW_WIDTH       = 1350
WINDOW_HEIGHT      = 920
MAXIMIZED          = True
TERMINAL_FONT_SIZE = 16    # Taille du texte dans le terminal, le bloc-notes et les options
TERMINAL_HEIGHT    = 170   # Hauteur du panneau terminal compact (px) — toujours visible
WDA_HEIGHT         = 100   # Hauteur de la WindowDragArea (barre de titre custom, en px)


# ── 6.2  Redimensionnement & filigrane ────────────────────────────────────────

RESIZE_DEFAULT       = 640    # Dimension max par défaut (y compris remerciements)
RESIZE_QUALITY       = 80     # Qualité JPEG des miniatures (0-100)
DASHBOARD_THUMB_SIZE = 50     # Taille des miniatures dans le panneau de prévisualisation (px)
WATERMARK_ALPHA      = 0.35   # Opacité du filigrane (0.0 = invisible, 1.0 = opaque)


# ── 6.3  Remerciements ────────────────────────────────────────────────────────
# Paramètres du script Remerciements.py (tirage 2-en-1 client).

REMERCIEMENTS_WIDTH   = 76     # Largeur individuelle en mm (doublée en 2-en-1)
REMERCIEMENTS_HEIGHT  = 102    # Hauteur individuelle en mm
REMERCIEMENTS_QUALITY = 75     # Qualité JPEG
REMERCIEMENTS_ALPHA   = 0.42   # Opacité filigrane


# ==============================================================================
# 7. FICHIERS & DOSSIERS
# ==============================================================================

# ── 7.1  Dossier TEMP ─────────────────────────────────────────────────────────
# Destination par défaut pour le transfert (Transfert vers TEMP.py).
# Peut être surchargé via la variable d'environnement DEST_FOLDER.

TEMP_FOLDER = "Z:/temp"
TRANSFER_TEMP_CONFIRM_DELETE_SELECTED = True   # True = demande confirmation avant suppression des originaux si SOURCE_FILES est fourni par Dashboard


# ── 7.2  Nettoyage automatique ────────────────────────────────────────────────
# Utilisée par Nettoyer anciens fichiers.py.

CLEAN_DAYS = 60   # Fichiers plus vieux que N jours sont supprimés


# ── 7.3  Comportement ZIP ─────────────────────────────────────────────────────
# True  = supprime directement le .zip source après décompression (sans confirmation)
# False = affiche une boîte de dialogue Oui/Non avant de supprimer

DELETE_ZIP_AFTER_EXTRACT = False


# ==============================================================================
# 8. RÉSEAU & KIOSKS
# ==============================================================================
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


# ==============================================================================
# 9. CACHE DE MINIATURES
# ==============================================================================
# Utilisé par Dashboard.pyw, SidePanel.pyw et kiosk_flet.pyw via thumb_cache.py.
# Un fichier SQLite (THUMB_CACHE_DB_NAME) est créé dans chaque dossier d'images.

THUMB_CACHE_SIZE    = 280                # Taille (px, côté le plus long) des miniatures
THUMB_CACHE_QUALITY = 60                 # Qualité JPEG (0-100)
THUMB_CACHE_DB_NAME = ".thumbcache.db"   # Nom du fichier SQLite dans chaque dossier


# ==============================================================================
# 10. INTELLIGENCE ARTIFICIELLE
# ==============================================================================

# ── 10.1  Modèles & paramètres ────────────────────────────────────────────────

AI_OLLAMA_URL   = "http://localhost:11434"   # URL de l'API Ollama locale
AI_MODEL_TEXT   = "gemini-3.5-flash"         # Modèle texte par défaut
AI_MODEL_VISION = "gemini-3.5-flash"         # Modèle vision par défaut
AI_GEMINI_MODEL    = "gemini-3.5-flash"      # Modèle Gemini principal (API Google)
AI_GEMINI_FALLBACK = "gemma4:e4b"            # Fallback Ollama local si hors-ligne
AI_GEMINI_IMAGE_TIMEOUT = 180                 # Timeout max (s) pour generate/edit image via Gemini
AI_TEMPERATURE  = 0.7                        # Créativité (0.0 = déterministe, 1.0 = créatif)
AI_URL_MAX_CHARS = 12_000                    # Nb max de caractères extraits d'une URL
AI_ORGANIZE_CONFIRM  = False                 # True = confirmation avant chaque tri de fichiers
AI_TERMINAL_CONFIRM  = False                 # True = confirmation avant chaque commande terminal
AI_IMAGE_ATTACH_DEFAULT_ORIGINAL = True      # True = images jointes manuellement en taille réelle par défaut
AI_IMAGE_ATTACH_SELECTED_ORIGINAL = False    # True = images sélectionnées dans la preview en taille réelle
AI_SHOW_REFINED_IMAGE_PROMPT = True          # True = affiche dans le chat le prompt final envoyé à Nano Banana
AI_USER_NAME         = "Charles"             # Appellation dans l'export de conversation
AI_SEPARATOR_WIDTH   = 80                    # Nb de '#' pour les séparateurs d'export

# Taille des lots pour la sélection IA de photos
AI_FOLDER_SELECT_BATCH_SIZE  = 5    # Nb d'images par appel IA (Ollama) — petits lots
AI_GEMINI_FOLDER_BATCH_SIZE  = 20   # Nb d'images par appel IA (Gemini) — grands lots
AI_FOLDER_SELECT_IMAGE_SIZE  = 1024  # Résolution max (px) envoyée à l'IA
AI_FOLDER_SELECT_QUALITY     = 70    # Qualité JPEG des images envoyées à l'IA

# Modèles disponibles — (label affiché, identifiant, supporte_vision)
AI_AVAILABLE_MODELS = [
    ("Gemini 3.5 Flash  🌐🖼",        "gemini-3.5-flash",         True),
    ("Gemini 3.1 Pro  🌐🖼",          "gemini-3.1-pro-preview",   True),
    ("Gemma 4 E4B  (~9.6 GB) 🖼",    "gemma4:e4b",               True),
    ("Gemma 4 · 26B  (~18 GB) 🖼",   "gemma4:26b",               True),
    ("DeepSeek-R1 · 8B  (~5.2 GB)",  "deepseek-r1:8b",           False),
    ("DeepSeek-R1 · 14B  (~9 GB)",   "deepseek-r1:14b",          False),
]

# Modèles affichés dans le dropdown de sélection rapide du Dashboard
AI_DROPDOWN_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.1-pro-preview",
    "gemma4:e4b",
]


# ── 10.2  Prompts système ─────────────────────────────────────────────────────

AI_SYSTEM_PROMPT = (
    f"On se tutoie. Tu parles à {AI_USER_NAME}.\n\n"
    "CAPACITÉS :\n"
    "Tu peux accéder à internet (web_search, fetch_url) et aux fichiers du dossier ouvert "
    "— les lister, lire leur contenu, les organiser par sous-dossiers, ou analyser visuellement les images.\n"
    "Tu peux aussi GÉNÉRER et MODIFIER des images directement via Nano Banana 2 (generate_image, edit_image) : "
    "créer une image depuis un prompt, éditer une photo, changer le style, coloriser une image noir et blanc, etc. "
    "Utilise ces outils directement sans chercher du code OpenCV ou PIL — tu n'as pas besoin de code pour ça.\n\n"
    "RÈGLES :\n"
    "- Pas de disclaimers ni de mises en garde inutiles (pas de 'consulte un professionnel', 'je ne suis pas médecin', etc.).\n"
    "- Si tu ne connais pas la réponse, fais une recherche web plutôt que d'inventer.\n"
    "- Cite toujours tes sources avec les URLs complètes quand tu fais une recherche web.\n"
    "- Quand tu organises des fichiers, explique ta logique clairement.\n\n"
    "Reste naturel et engageant, n'hésite pas à utiliser des émoticônes ou de l'humour quand c'est pertinent."
)

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


# ── 10.3  Voix — TTS (synthèse vocale Gemini) ────────────────────────────────

AI_VOICE_TTS_ENABLED     = False   # Lire la réponse IA à voix haute après chaque réponse complète
AI_VOICE_TTS_BTN_VISIBLE = True    # Afficher le bouton TTS même si la lecture auto est désactivée
AI_VOICE_TTS_MODE        = "live"  # "live" = Gemini Live (voix conversationnelle) | "chunked" = lecture fidèle du texte
AI_VOICE_TTS_MODEL       = "gemini-2.5-flash-preview-tts"   # Modèle TTS classique (mode "chunked")
AI_VOICE_LIVE_MODEL      = "gemini-3.1-flash-live-preview"  # Modèle Gemini Live (mode "live")
AI_VOICE_TTS_VOICE       = "Kore"   # Voir AI_AVAILABLE_VOICES ci-dessous
AI_VOICE_TTS_SAMPLE_RATE = 24000    # Fréquence de sortie PCM (Hz — ne pas modifier)
AI_VOICE_TTS_LANGUAGE    = "fr"     # Code ISO 639-1 pour la langue de synthèse
AI_VOICE_TTS_SINGLE_SHOT_MAX_CHARS = 1200  # Longueur max (caractères) pour forcer une seule requête TTS

# Voix disponibles pour le sélecteur (noms officiels Google Gemini TTS)
AI_AVAILABLE_VOICES = [
    "Puck",     # Voix décontractée masculine
    "Charon",   # Voix neutre masculine
    "Kore",     # Voix douce féminine
    "Fenrir",   # Voix grave masculine
    "Aoede",    # Voix légère féminine
    "Leda",     # Voix claire féminine
    "Orus",     # Voix profonde masculine
    "Zephyr",   # Voix aérienne féminine
    "Schedar",  # Voix chaleureuse masculine
    "Gacrux",   # Voix ferme masculine
]


# ── 10.4  Augmentation IA — aperçu SAM2 ─────────────────────────────────────

# Rayon de flou des bords du masque SAM2, exprimé en fraction de la plus petite
# dimension du rendu (0 = pas de flou, 0.01 = ~1 % → ~8 px sur 800 px).
SAM2_MASK_FEATHER_RATIO = 0.001


# ==============================================================================
# 11. KIOSK FLET
# ==============================================================================

# ── 11.1  Extensions & grille ─────────────────────────────────────────────────

EXTENSION = (".jpg", ".jpeg", ".png")   # Extensions acceptées

GRID_MAX_EXTENT   = 340    # Taille maximale d'une cellule de la grille (px)
GRID_ASPECT_RATIO = 0.82   # Ratio hauteur/largeur de chaque cellule (1.0 = carré)
GRID_SPACING      = 12     # Espacement entre les cellules (px)
THUMBNAIL_SIZE    = 280    # Taille des miniatures PIL (px, côté le plus long)
PREVIEW_NB_SIZE   = 1024   # Résolution max pour la prévisualisation N&B plein écran


# ── 11.2  Panneau gauche ──────────────────────────────────────────────────────

LEFT_PANEL_WIDTH     = 210
FORMAT_BUTTON_HEIGHT = 48
ACTION_BUTTON_HEIGHT = 68


# ── 11.3  Tarifs d'impression ─────────────────────────────────────────────────

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
    "10x15"   : [0.50, 0.40, 0.35, 0.30, 0.25],  # Prix dégressif : <10 | 11-50 | 51-100 | 101-200 | >200
    "13x18"   : [1.50, 1.40, 1.35, 1.30, 1.25],
    "15x20"   : [2.50, 2.20, 2.00, 1.80, 1.60],
    "20x30"   : [4.90, 4.70, 4.50, 4.30, 4.10],
    "30x40"   : [12.90, 12.50, 12.00, 11.50, 11.00],
    "40x60"   : [24.90, 24.50, 24.00, 23.50, 23.00],
    "50x70"   : [28.00, 26.50, 25.00, 24.50, 24.00],
    "60x90"   : [30.00, 29.50, 29.00, 28.50, 28.00],
}

SIZES = STUDIOS   # Alias conservé pour compatibilité ascendante
