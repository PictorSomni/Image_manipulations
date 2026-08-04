# -*- coding: utf-8 -*-
"""
Constantes partagées entre Hub.pyw, les scripts du dossier Data/ et
kiosk_flet.pyw.

Modifier ce fichier pour changer les paramètres globaux de l application sans
toucher aux scripts eux-mêmes.
"""

import json
import os

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
#    4.4  2-en-1
# 5. RECADRAGE MANUEL.PYW ...................................... ~L 115
#    5.1  Performance de prévisualisation
#    5.2  Toggles (états initiaux)
#    5.3  Réglages image par défaut
# 6. INTERFACE (HUB) .................................... ~L 185
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

__version__ = "3.1.0"


# ==============================================================================
# 2. FICHIERS & EXTENSIONS
# ==============================================================================

IMAGE_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".ico", ".tiff", ".tif",
})
# Hub.pyw — fichiers vectoriels prévisualisables (miniature rendue via
# PyMuPDF/Wand, cf. thumb_cache.py), séparé de IMAGE_EXTS car les autres
# scripts (Redimensionner, Conversion JPG…) ouvrent leurs fichiers avec
# PIL, qui ne sait pas lire ces formats.
HUB_VECTOR_EXTS = frozenset({".svg", ".pdf"})
NOTEPAD_EXTS = frozenset({
    ".txt", ".md", ".log", ".ini", ".cfg", ".yaml", ".yml",
    ".rtf", ".py", ".pyw", ".toml", ".sh", ".bat", ".csv",
    ".desktop", ".astro"
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


# ── 3bis. SYSTÈME DE DESIGN — rôles & échelle ─────────────────────────────────
# Principe : une icône colorée doit porter un SENS, pas une décoration.
# Par défaut une icône d'action est NEUTRE ; la couleur signale un rôle précis.
# Modifier ici recolore toute l'interface d'un coup.

# Rôle de couleur (référence la palette ci-dessus).
# IMPORTANT : ne PAS utiliser de neutre (gris OU blanc) sur une icône seule —
# ça se lit « désactivé » et c'est terne. Toute icône d'action doit être
# COLORÉE.
ICON_ACTION  = COLOR_BLUE         # action primaire / fréquente (parcourir, rafraîchir)

# Échelle typographique — 2 crans : corps de texte, et titres de zone.
TEXT_SM = 13   # corps : dialogues, listes, boutons, noms de fichiers
TEXT_LG = 20   # titres de zone (Bloc-notes, Assistant IA, HUB, Actions)

# Échelle d'icônes — 2 crans : standard, et tactile proéminent.
ICON_SM = 20   # icône standard (barres d'outils, boutons, badges, listes)
ICON_LG = 28   # icône tactile proéminente (vignettes, panneau Actions,
               # barre de titre, visionneuse plein écran)

# Cible tactile minimale, en px logiques : plus petit carré qu'un doigt
# atteint de façon fiable. 44 est le plancher commun à Apple (44 pt) et
# Material (48 dp) ; on retient le plus petit des deux pour ne pas gonfler
# les panneaux de réglages, qui alignent beaucoup de contrôles.
# À utiliser pour tout bouton d'un écran utilisable SANS souris ni clavier
# (bornes tactiles) — les valeurs HUB_*_TAP_HEIGHT ci-dessous en sont des
# déclinaisons historiques, propres à une barre précise de Hub.pyw.
TOUCH_TARGET = 44

# Échelle d'espacement — 4 crans, en px (padding, spacing entre contrôles).
# Remplace les valeurs ad hoc (6, 10, 14…) éparpillées dans chaque écran.
SPACE_XS = 4   # hairline : entre un titre et son contenu direct
SPACE_SM = 8   # entre contrôles proches d'un même groupe
SPACE_MD = 12  # entre groupes de contrôles, padding intérieur standard
SPACE_LG = 16  # entre sections, padding extérieur d'un panneau

# Hub.pyw — vignettes et liste de fichiers : case à cocher agrandie pour
# l'écran tactile (icône/texte utilisent ICON_LG/TEXT_SM ci-dessus).
HUB_TILE_CHECKBOX_SCALE = 1.4  # agrandissement de la case à cocher (doigt)

# Hub.pyw — barre d'outils Fichiers (chemin, recherche, tri, vue, boutons
# dossier/actions) : hauteur commune à tous les contrôles de la ligne,
# pour éviter les décalages verticaux entre types de contrôle Flet.
HUB_TOOLBAR_H = 40

# Hub.pyw — champ de saisie compact des petits dialogues (renommer, créer
# un dossier/fichier, ajouter un programme, mot de passe sudo…). Même
# valeur que HUB_TOOLBAR_H par coïncidence, mais rôle distinct — nommé à
# part pour rester clair si l'un des deux change un jour.
HUB_DIALOG_FIELD_HEIGHT = 40

# Hub.pyw — barre de titre : cible de tap des icônes tactiles (Bluetooth,
# impression, navigateur, explorateur — taille ICON_LG ci-dessus),
# agrandie pour l'écran tactile (retour user).
HUB_TITLEBAR_TAP_HEIGHT = 48

# Hub.pyw — barre d'état (Terminal, Actions, curseur de taille des
# vignettes) : hauteur agrandie pour l'écran tactile (retour user), et
# cible de tap des boutons Terminal/Actions qu'elle contient.
HUB_STATUSBAR_HEIGHT     = 56
HUB_STATUSBAR_TAP_HEIGHT = 44


# ==============================================================================
# 4. IMPRESSION
# ==============================================================================

# ── 4.1  Résolution DPI ───────────────────────────────────────────────────────

DPI = 300   # Points par pouce (ne pas modifier sauf matériel spécifique)


# ── 4.2  Formats d'impression ─────────────────────────────────────────────────
# (largeur_mm, hauteur_mm) en portrait

FORMATS = {
    "ID"        : (36,  46),
    "7x10"    : (76, 102),
    "9x13"    : (89,  127),
    "10x10"  : (102, 102),
    "10x15"  : (102, 152),
    "10x20"  : (102, 203),
    "13x13"  : (127, 127),
    "13x15"  : (127, 152),
    "13x18"  : (127, 178),
    "13x20"  : (127, 203),
    "15x15"  : (152, 152),
    "15x18"  : (152, 178),    
    "15x20"  : (152, 203),
    "18x24"  : (178, 240),
    "20x20"  : (203, 203),
    "20x24"  : (203, 240),
    "20x30"  : (203, 305),
    "A4"       : (210, 297),
    "A3"       : (297, 420),
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


# ── 4.4  Formats 2-en-1 ───────────────────────────────────────────────────────
# Liste ordonnée affichée dans le dialogue Hub (premier = valeur par défaut).

TWO_IN_ONE_FORMATS = [
    ("2 10x15 sur 15x20", "102x152"),
    ("2 7x10 sur 10x15",  "76x102"),
    ("2 9x13 sur 13x18",  "89x127"),
    ("2 10x10 sur 10x20", "102x102"),
    ("2 15x20 sur 20x30", "152x203"),
]


# ==============================================================================
# 5. RECADRAGE MANUEL.PYW
# ==============================================================================

# ── 5.1  Performance de prévisualisation ──────────────────────────────────────
# Taille maximale (px, côté le plus long) de l'image de prévisualisation.
# Réduire sur les machines moins puissantes (ex. 800 pour les petits écrans).
# Sert désormais de PLANCHER : la taille réelle est calculée d'après celle du
# widget d'affichage (cf. PREVIEW_SUPERSAMPLING et PREVIEW_MAX_PIXELS_CEILING).

PREVIEW_MAX_PIXELS = 1024

# Facteur de suréchantillonnage des aperçus, pour les écrans HDPI/Retina.
#
# Flet dimensionne les contrôles en pixels LOGIQUES ; l'affichage les rend
# ensuite en pixels physiques, 2× plus nombreux sur un Retina, 1× sur un écran
# standard, et des valeurs intermédiaires ailleurs. Un aperçu rendu par PIL à
# la taille logique du widget est donc étiré par l'affichage, et on juge la
# netteté, le grain ou le bruit sur une image ré-échantillonnée.
#
# Flet n'expose pas le devicePixelRatio : 2.0 couvre le cas Retina/4K le plus
# courant, et `fit=CONTAIN` réduit proprement l'excédent sur un écran 1×.
# C'est un compromis mesurable, pas une valeur exacte : monter à 3.0 pour un
# écran très dense, redescendre à 1.0 sur une machine lente (l'aperçu live
# recalcule toute la chaîne à chaque réglage, et le coût suit le carré).
PREVIEW_SUPERSAMPLING = 2.0

# Plafond dur, en px : au-delà, l'aperçu live devient plus lent que le geste
# qu'il accompagne. Borne le produit taille du widget × suréchantillonnage sur
# les très grands écrans.
PREVIEW_MAX_PIXELS_CEILING = 2600


# ── 5.2  Affichage et hauteurs de panneaux ────────────────────────────────────
# Désactiver l'histogramme permet de gagner de la place verticale et d'éviter
# son recalcul pendant les rafraîchissements du preview.

RECADRAGE_SHOW_HISTOGRAM       = False   # Afficher et calculer l'histogramme
RECADRAGE_FORMAT_LIST_HEIGHT    = 350    # Hauteur MAX de la liste des formats (grands écrans)
RECADRAGE_FORMAT_LIST_MIN_HEIGHT = 150   # …et son plancher sur les petits écrans (la liste défile)
RECADRAGE_CUSTOM_PANEL_HEIGHT   = 110     # Hauteur du panneau Dimensions (mm)


# ── 5.2  Toggles — états initiaux ─────────────────────────────────────────────
# Chaque constante correspond à l'état initial d'un toggle (Switch ou bouton).

RECADRAGE_BORDER_POLAROID = False   # Mise en page Polaroid (format 10x10)
RECADRAGE_BORDER_ID2      = False   # Planche ID X2
RECADRAGE_BORDER_ID4      = True    # Planche ID X4
RECADRAGE_ID4_10x20       = True    # Format 10x20 pour la planche ID X4
RECADRAGE_SAVE_TO_NETWORK = True    # Sauvegarder les ID X4 sur le réseau par défaut
RECADRAGE_IS_BW           = False   # Noir et blanc
RECADRAGE_IS_SHARPEN      = True    # Netteté activée
RECADRAGE_FIT_IN          = False   # Mode Fit-in (image entière dans le format)
RECADRAGE_WHITE_BORDER    = False   # Bord blanc 5 mm (image réduite, canvas inchangé)
RECADRAGE_SHOW_GRID       = True    # Afficher la grille de cadrage
RECADRAGE_REMBG_BG_WHITE  = True    # Fond blanc après suppression IA (vs flou)
RECADRAGE_REMBG_HUMAN_SEG = True    # Segmentation humain (vs généraliste)
RECADRAGE_REMBG_MODE      = 2       # 0 = rapide (u2net), 1 = précis (birefnet), 2 = instantané (flood, sans IA)
RECADRAGE_FLOOD_TOLERANCE = 40      # Mode instantané : distance couleur max (RGB, 0-441) au point cliqué — cf. image_ops.flood_background_mask
# Mode instantané : lancer une passe depuis les coins/bords dès l'activation,
# sans attendre un clic. Taillé pour la photo d'identité sur fond quasi blanc
# (le fond touche les 4 bords) : détourage immédiat, à compléter au clic si
# besoin. Mettre à False pour repartir systématiquement d'un clic.
RECADRAGE_FLOOD_AUTO_BORDER = True
RECADRAGE_SCROLL_ROTATES  = False   # Molette = rotation (Tab pour basculer)


# ── 5.3  Réglages image — valeurs par défaut ──────────────────────────────────

RECADRAGE_DEFAULT_CONTRAST      =   0   # Contraste       (-20 ... +20)
RECADRAGE_DEFAULT_SATURATION    =  20   # Saturation      (-100 ... +100)
RECADRAGE_DEFAULT_EXPOSURE      =  20   # Exposition      (-100 ... +100)
RECADRAGE_DEFAULT_SHADOWS       =  0   # Ombres          (-100 ... +100)
RECADRAGE_DEFAULT_HIGHLIGHTS    =   0   # Hautes lumières (-100 ... +100)
RECADRAGE_DEFAULT_HUE           =   0   # Teinte          (-180 ... +180)
RECADRAGE_DEFAULT_WHITE_BALANCE =   0   # Balance blancs  (-100 ... +100)

# Recadrage automatique (mode fit) : ecart entre les tuiles (mm)
RECADRAGE_FORCE_TILE_GAP_MM = 3


# ==============================================================================
# 6. INTERFACE (HUB)
# ==============================================================================

# ── 6.1  Fenêtre principale ───────────────────────────────────────────────────

WINDOW_WIDTH       = 1400
WINDOW_HEIGHT      = 920
MAXIMIZED          = True
TERMINAL_FONT_SIZE    = 16   # Taille du texte dans le terminal, le bloc-notes et les options
TERMINAL_HEIGHT       = 170  # Hauteur du panneau terminal compact (px) — toujours visible
WDA_HEIGHT            = 100  # Hauteur de la WindowDragArea (barre de titre custom, en px)
HUB_TERMINAL_HEIGHT           = 200  # Hauteur du panneau terminal compact de Hub.pyw (px)
HUB_TERMINAL_AUTOHIDE_DELAY   = 2.5  # Délai (secondes) avant fermeture auto du terminal de Hub.pyw
HUB_TERMINAL_TOOL_CLOSE_DELAY = 1.5  # Délai (secondes) après un [OK] de _launch_tool avant fermeture
HUB_TERMINAL_LOG_MAX_BYTES    = 200_000  # Taille max de .hub_terminal.log avant purge (octets, ~2000 lignes)
HUB_TERMINAL_MAX_LINES        = 200  # Nombre max de lignes conservées dans le terminal de Hub.pyw
HUB_AI_MAX_BUBBLES            = 120  # Nombre max de bulles gardées à l'écran dans l'onglet IA (la conversation complète reste dans .ai_conversation_hub.json)
NOTEPAD_AUTOSAVE_DELAY = 10  # Délai (secondes) avant sauvegarde automatique du bloc-notes
NOTEPAD_DEFAULT_LANGUAGE = "MARKDOWN"  # Langage de coloration syntaxique par défaut du bloc-notes (voir fce.CodeLanguage)


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

TEMP_FOLDER = "\\\\Diskstation\\travaux en cours\\Z2026\\TEMP"   # Windows
TRANSFER_TEMP_CONFIRM_DELETE_SELECTED = True   # True = demande confirmation avant suppression des originaux si SOURCE_FILES est fourni par Hub


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
# Utilisés par Kiosk gauche.py et Nettoyer anciens fichiers.py.

import platform as _platform

if _platform.system() == "Windows":
    KIOSK_GAUCHE_SRC  = r"\\studioc-kiosk1\kiosk-data\it-HotFolder"
    KIOSK_GAUCHE_DEST = r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK GAUCHE"
    CLEAN_FOLDERS = [
        r"\\studioc-kiosk1\kiosk-data\it-HotFolder",
        r"\\studioc-kiosk2\kiosk-data\it-HotFolder",
        r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK GAUCHE",
        r"\\Diskstation\travaux en cours\z2026\kiosk\KIOSK DROITE",
        r"\\diskstation\travaux en cours\Z2026\TEMP",
    ]
else:
    
    _travaux = "/Volumes/TRAVAUX EN COURS"
    if not os.path.ismount(_travaux):
        for _suffix in ["-1", "-2", "-3", "-4"]:
            _candidate = f"{_travaux}{_suffix}"
            if os.path.ismount(_candidate):
                _travaux = _candidate
                break
    KIOSK_GAUCHE_SRC  = "/Volumes/kiosk-data/it-HotFolder"
    KIOSK_GAUCHE_DEST = f"{_travaux}/Z2026/KIOSK/KIOSK GAUCHE"
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
# Utilisé par Hub.pyw et kiosk_flet.pyw via thumb_cache.py.
# Un fichier SQLite (THUMB_CACHE_DB_NAME) est créé dans chaque dossier d'images.

THUMB_CACHE_SIZE    = 200                # Taille (px, côté le plus long) des miniatures —
                                          # réduite de 320 (retour user : cartes SD lentes,
                                          # moins de pixels à décoder/encoder/stocker par
                                          # miniature, sur toutes les apps qui partagent ce
                                          # cache)
THUMB_CACHE_QUALITY = 64                 # Qualité JPEG (0-100)
THUMB_CACHE_DB_NAME = ".thumbcache.db"   # Nom du fichier SQLite dans chaque dossier


# ==============================================================================
# 9bis. FICHIERS SYSTÈME À IGNORER (miniatures/cache OS)
# ==============================================================================
# Utilisé partout où on liste/copie/synchronise des fichiers, pour ne jamais
# copier les fichiers système générés par macOS/Windows/Linux (Finder, Explorer,
# gestionnaires de fichiers Linux…).

OS_JUNK_NAMES = frozenset({
    ".ds_store", "thumbs.db", "thumbs.db:encryptable",
    "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini",
    ".directory", ".spotlight-v100", ".trashes",
    THUMB_CACHE_DB_NAME.lower(),
})


def is_os_junk(name, is_dir=False):
    """
    Retourne True si `name` (nom de fichier/dossier, sans le chemin) est un
    fichier système à ignorer : ceux de OS_JUNK_NAMES, les sidecars macOS
    AppleDouble ('._xxx'), les sidecars SQLite WAL du cache de miniatures
    ('.thumbcache.db-shm', '.thumbcache.db-wal'), la corbeille Windows et
    les corbeilles Linux ('.Trash-1000/', un dossier par utilisateur).
    """
    name_lower = name.lower()
    return (
        name_lower in OS_JUNK_NAMES
        or name_lower.startswith("._")
        or name_lower.startswith(THUMB_CACHE_DB_NAME.lower() + "-")
        or name == "$RECYCLE.BIN"
        or (is_dir and name.startswith(".Trash-"))
    )


# ==============================================================================
# 10. INTELLIGENCE ARTIFICIELLE
# ==============================================================================

# ── 10.1  Modèles & paramètres ────────────────────────────────────────────────

AI_OLLAMA_URL          = "http://localhost:11434"      # URL de l'API Ollama locale
AI_MODEL_TEXT          = "gemini-3.5-flash-lite"           # Modèle texte par défaut
AI_MODEL_VISION        = "gemini-3.5-flash-lite"           # Modèle vision par défaut
AI_GEMINI_MODEL        = "gemini-3.5-flash-lite"           # Modèle Gemini principal (API Google)
AI_GEMINI_FALLBACK_CLOUD = "gemini-3.6-flash"  # Fallback cloud si modèle indisponible
AI_GEMINI_FALLBACK     = "gemma4:e4b"                 # Fallback Ollama local si hors-ligne
AI_GEMINI_IMAGE_TIMEOUT = 180                # Timeout max (s) pour generate/edit image via Gemini
AI_GEMINI_STREAM_TIMEOUT_MS = 180_000        # Timeout (ms) du streaming Gemini : au-delà de ce délai sans chunk, l'appel lève une erreur au lieu de figer l'app
AI_TEMPERATURE  = 0.7                        # Créativité (0.0 = déterministe, 1.0 = créatif)
AI_MAX_TOOL_ROUNDS = 20                      # Nb max d'allers-retours outil→modèle pour UNE question (garde-fou anti-boucle : chaque tour = 1 appel modèle facturé)
AI_HISTORY_LIMIT_CLOUD = 10                  # Nb max de messages envoyés à l'IA (Gemini / Claude)
AI_HISTORY_LIMIT_LOCAL = 10                  # Nb max de messages envoyés à l'IA (modèles Ollama locaux)
AI_URL_MAX_CHARS = 20_000                    # Nb max de caractères extraits d'une URL
AI_FILE_MAX_CHARS = 500_000                  # Nb max de caractères lus dans un fichier du dossier
AI_ORGANIZE_CONFIRM  = False                 # True = confirmation avant chaque tri de fichiers
AI_TERMINAL_CONFIRM  = False                 # True = confirmation avant chaque commande terminal
AI_DELETE_CONFIRM    = True                  # True = confirmation avant chaque suppression de fichiers
# ── Sauvegarde avant modification (filet anti-perte de données) ───────────────
# Avant TOUTE opération qui écrase/détruit des données — fichier local OU
# mutation MCP (Notion, Canva…) — on écrit un instantané de l'état/appel dans
# AI_BACKUP_DIRNAME. Général : s'applique à toute demande, pas à un service précis.
AI_BACKUP_ENABLED  = True
AI_BACKUP_DIRNAME  = ".ai_backups"           # Dossier de sauvegarde (créé sous Data/)
AI_MCP_DESTRUCTIVE_KEYWORDS = (              # Un outil MCP dont le nom contient l'un de ces mots est sauvegardé avant exécution
    "delete", "remove", "archive", "trash", "clear", "update", "patch",
    "replace", "overwrite", "move", "drop", "set-", "destroy", "purge",
)
AI_IMAGE_ATTACH_DEFAULT_ORIGINAL = False     # True = images jointes manuellement en taille réelle par défaut
AI_IMAGE_ATTACH_SELECTED_ORIGINAL = False    # True = images sélectionnées dans la preview en taille réelle
AI_SHOW_REFINED_IMAGE_PROMPT = True          # True = affiche dans le chat le prompt final envoyé à Nano Banana
AI_IMAGE_REFINER_MODEL = "gemini-3.6-flash"  # Modèle qui affine le prompt image (indépendant du cerveau de chat) — 1 appel/image, ~centimes, gros gain de qualité vs flash-lite
AI_IMAGE_ITERATE_MAX_PASSES = 2              # Passes max de la boucle iterate_image (critique visuelle → régénération). Chaque passe = 1 génération Nano Banana. Arrêt anticipé si l'objectif est atteint.
AI_USER_NAME         = "Charles"             # Appellation dans l'export de conversation
AI_SEPARATOR_WIDTH   = 80                    # Nb de '#' pour les séparateurs d'export

# Taille des lots pour la sélection IA de photos
AI_FOLDER_SELECT_BATCH_SIZE  = 5    # Nb d'images par appel IA (Ollama) — petits lots
AI_GEMINI_FOLDER_BATCH_SIZE  = 6    # Nb d'images par appel IA (Gemini). Petit = bien meilleur jugement par image (le modèle « regarde » vraiment chacune) ; coût ~identique, juste plus de requêtes.
AI_FOLDER_SELECT_IMAGE_SIZE  = 1024  # Résolution max (px) envoyée à l'IA
AI_FOLDER_SELECT_QUALITY     = 85    # Qualité JPEG des images envoyées à l'IA (assez fin pour juger netteté / dos vs visages / écharpes)

# Modèles affichés dans le dropdown de sélection rapide du Hub
AI_DROPDOWN_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.6-flash",
    "claude-sonnet-4-6",
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
    "Utilise ces outils directement sans chercher du code OpenCV ou PIL — tu n'as pas besoin de code pour ça.\n"
    "Quand l'utilisateur demande d'AMÉLIORER / ITÉRER / PEAUFINER une image « jusqu'à ce que ce soit bon » "
    "(plusieurs passes), utilise iterate_image (objectif précis) : chaque passe critique le rendu puis le régénère, "
    "avec arrêt anticipé dès que l'objectif est atteint. Pour une seule retouche, edit_image suffit.\n\n"
    "RÈGLES :\n"
    "- Pas de disclaimers ni de mises en garde inutiles (pas de 'consulte un professionnel', 'je ne suis pas médecin', etc.).\n"
    "- Si tu ne connais pas la réponse, fais une recherche web plutôt que d'inventer.\n"
    "- Cite toujours tes sources avec les URLs complètes quand tu fais une recherche web.\n"
    "- Quand tu organises des fichiers, explique ta logique clairement.\n\n"
    "Reste naturel et engageant, n'hésite pas à utiliser des émoticônes ou de l'humour quand c'est pertinent."
)


# ── 10.3  Voix — TTS (synthèse vocale Gemini) ────────────────────────────────

AI_VOICE_TTS_ENABLED     = False   # Lire la réponse IA à voix haute après chaque réponse complète
AI_VOICE_TTS_BTN_VISIBLE = True    # Afficher le bouton TTS même si la lecture auto est désactivée
AI_VOICE_TTS_MODE        = "chunked"  # "live" = Gemini Live (voix conversationnelle) | "chunked" = lecture fidèle du texte
AI_VOICE_TTS_MODEL       = "gemini-3.1-flash-tts-preview"   # Modèle TTS classique (mode "chunked")
AI_VOICE_LIVE_MODEL      = "gemini-3.1-flash-live-preview"  # Modèle Gemini Live (mode "live")
AI_VOICE_TTS_VOICE       = "Kore"   # Voir AI_AVAILABLE_VOICES ci-dessous
AI_VOICE_TTS_SAMPLE_RATE = 24000    # Fréquence de sortie PCM (Hz — ne pas modifier)
AI_VOICE_TTS_LANGUAGE    = "fr"     # Code ISO 639-1 pour la langue de synthèse

# ── Réduction de latence du mode "live" ──────────────────────────────────────
# Coussin audio (jitter buffer) : on accumule ce nombre de ms d'audio avant de
# démarrer la lecture, pour éviter les trous si le réseau hoquette. 0 = démarrer
# au premier échantillon (latence minimale, moins tolérant aux à-coups).
AI_VOICE_TTS_PREROLL_MS = 400

# Lecture incrémentale : commencer à parler dès que ~MIN_CHARS de texte propre
# sont générés, sans attendre la réponse complète (mode "live" uniquement).
# Chunks plus gros = plus stable mais démarrage plus tardif ; plus petits =
# plus réactif mais coutures plus fréquentes. False = comportement d'origine
# (parler une fois la réponse complète).
AI_VOICE_TTS_STREAM = False
AI_VOICE_TTS_STREAM_MIN_CHARS = 200

# ── Dictée vocale — STT (transcription Gemini, push-to-talk) ─────────────────
# Bouton micro dans les zones IA : maintenir pour parler, relâcher pour
# transcrire. L'audio est envoyé à Gemini (aucun fournisseur externe).
AI_VOICE_STT_MODEL       = "gemini-3.5-flash-lite"  # Modèle de transcription (le moins cher)
AI_VOICE_STT_LANGUAGE    = "fr"     # Langue de dictée par défaut (ISO 639-1)
AI_VOICE_STT_SAMPLE_RATE = 0        # 0 = fréquence native du micro (recommandé ; forcer une fréquence déforme l'audio)

# Touche du bouton PTT matériel (macropad CircuitPython). Doit être un nom
# d'attribut valide de pynput.keyboard.Key ("f13".."f20") — seule plage
# portable sur Windows/macOS/Linux. Changer ici + reprogrammer le firmware
# du macropad pour émettre la même touche.
AI_VOICE_PTT_KEY = "f15"


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


# ── 10.4  Augmentation IA — sélection d'objet SAM2 ──────────────────────────
# Clic (sans glisser) en mode Retouche IA = segmentation de l'objet sous le
# curseur via SAM2, plutôt que le rectangle littéral du glisser-déposer.

# Checkpoint + config Hydra utilisés (cf. sam2/sam2/configs/ dans le paquet
# installé) — variante "small", meilleur compromis vitesse/qualité pour un
# clic ponctuel (pas de segmentation vidéo/batch) sur config modeste.
SAM2_CHECKPOINT   = "sam2.1_hiera_small.pt"
SAM2_CONFIG       = "configs/sam2.1/sam2.1_hiera_s.yaml"

# Élargissement du masque SAM2 avant le fondu — évite de voir le contour net
# de la sélection sur le résultat recollé (retour user). Exprimé en fraction
# de la plus petite dimension de l'OBJET détecté (pas un nombre de px fixe,
# même principe qu'AI_RETOUCH_FEATHER_RATIO) : un objet fin (ex. un contour
# de quelques centaines de px) a besoin d'une dilatation proportionnellement
# plus généreuse qu'un gros objet pour couvrir tout son pourtour (retour
# user : un plafond fixe en px ne "remplissait" pas assez un objet étroit).
SAM2_MASK_DILATE_RATIO     = 0.08   # valeur par défaut du curseur
SAM2_MASK_DILATE_RATIO_MAX = 0.5    # jusqu'à 50 % du plus petit côté de l'objet

# Le fondu d'un masque d'objet (silhouette précise) doit rester bien plus
# fin que celui d'un rectangle (bords déjà nets, pas besoin d'un grand
# dégradé) — même curseur "Fondu des bords" que le rectangle, mais son
# rayon en pixels est divisé par ce facteur pour un masque SAM2.
SAM2_MASK_FEATHER_DIVISOR = 5

# Adoucissement des bords lors du recollage d'une retouche Gemini (Retouche IA).
# Le rayon vaut RATIO × plus petit côté de la sélection, borné à MIN px minimum.
# Plus grand = raccord plus fondu (mais retouche plus diluée sur les bords).
# Défaut abaissé (retour user : 0.166 mangeait toujours trop la retouche sur
# les bords) — ajustable ensuite via feather_slider sans rappeler Gemini.
AI_RETOUCH_FEATHER_RATIO = 0.05    # ~1/20 de la plus petite dimension
AI_RETOUCH_FEATHER_MIN   = 12      # rayon minimum en px

# Même principe pour le recollage de l'extension de cadre (Étendre l'image /
# outpainting) : fondu au raccord entre la photo d'origine (jamais régénérée)
# et la marge générée par Gemini. Le fondu est ANCRÉ sur le vrai bord de la
# photo (jonction photo/marge), PAS sur la frontière de la bande de contexte
# envoyée à Gemini (AI_EXPAND_CONTEXT_RATIO, bien plus profonde) : ancrer là
# mélangerait la vraie photo avec la propre reproduction de Gemini de cette
# même zone (jamais identique au pixel près), ce qui expose un dédoublement
# sur les motifs structurés (ballons, texture répétitive) qu'aucune largeur
# de flou ne corrige, seulement déplace (retour user : changer le slider ne
# changeait rien à la ligne visible). Exprimé en fraction de la largeur
# RÉELLEMENT AJOUTÉE (px de marge de ce côté) — déjà proportionnel à
# l'ampleur de l'extension, pas besoin de recalculer à la main.
AI_EXPAND_FEATHER_RATIO = 0.4      # ~40 % de la largeur de marge ajoutée
AI_EXPAND_FEATHER_MIN   = 4        # rayon minimum en px

# Profondeur de contexte envoyée à Gemini pour l'extension de cadre,
# quand un seul côté est étendu à la fois (pas de coin à combler).
# Envoyer la photo ENTIÈRE + la marge dilue les couleurs/textures près du
# bord dans le rabotage ~4K côté API (thumbnail avant envoi) sur les
# photos de plusieurs milliers de px — exactement là où la continuité de
# teinte compte le plus (retour user : couleurs pas respectées après
# extension). Exprimée en fraction de la dimension côté bord étendu
# (pas un nombre de px fixe : sinon trop généreux sur une petite image,
# insuffisant sur une énorme). Remonté de 0.15 à 0.30 (retour user :
# 15 % ne donnait pas assez de matière à Gemini sur un arrière-plan
# chargé — la marge générée n'avait plus rien à voir avec la vraie scène
# et créait une ligne de raccord visible même fondu à fond). Modifiable
# ici directement si besoin de retoucher au cas par cas.
AI_EXPAND_CONTEXT_RATIO   = 0.30    # ~30 % de la dimension étendue gardée en contexte
AI_EXPAND_CONTEXT_MIN_PX  = 300     # plancher en px

# Consigne ajoutée automatiquement à chaque retouche IA (inpainting), pour que
# Gemini ne modifie que ce qui est demandé et préserve le reste de la zone.
# Le prompt de l'utilisateur est ajouté après cette consigne.
AI_RETOUCH_SYSTEM_PROMPT = (
    "Respecte le reste de l'image telle qu'elle est, sans toucher ni aux "
    "formes, couleurs et lumières. Modification demandée : "
)


# ── 10.5  Musique — Lyria ─────────────────────────────────────────────────────

AI_MUSIC_CLIP_MODEL = "lyria-3-clip-preview"   # Clip 30 s fixe
AI_MUSIC_PRO_MODEL  = "lyria-3-pro-preview"    # Pro ~2 min, structuré


# ── 10.6  Score photos — tri IA structuré ────────────────────────────────────
# Critères universels toujours notés 0-10 par l'outil score_photos, avec
# une raison courte par note (voir .ai_photo_scores.json dans le dossier
# analysé). Les critères propres à un tri précis (mariage, ID, groupe…)
# sont fournis par Charles au moment de la demande, pas stockés ici.

AI_PHOTO_SCORE_CRITERIA = {
    "nettete":    "Netteté",
    "cadrage":    "Cadrage / composition",
    "expression": "Expression / regard",
    "exposition": "Exposition / lumière",
}

# Score global (moyenne des critères, 0-10) à partir duquel Hub
# copie l'image dans AI_PHOTO_SCORE_SELECTION_FOLDER. Volontairement
# haut : Charles est photographe, l'objectif est de ne garder que ses
# meilleurs clichés pour les retoucher ensuite à la main, pas une
# présélection large.
AI_PHOTO_SCORE_THRESHOLD = 8.0

# Sous-dossier créé (dans le dossier analysé) pour les copies au-dessus
# du seuil.
AI_PHOTO_SCORE_SELECTION_FOLDER = "SELECTION"

# Nom du fichier JSON de scores écrit dans le dossier analysé — éditable
# à la main pour affiner les notes/raisons avant de copier la sélection.
AI_PHOTO_SCORE_FILE = ".ai_photo_scores.json"


# ── 10.7  Serveurs MCP (Model Context Protocol) ──────────────────────────────
# Chaque entrée greffe automatiquement les outils d'un serveur MCP externe
# dans l'IA (Hub), quel que soit le modèle actif — voir
# Data/mcp_client.py. "auth": "oauth" déclenche un login navigateur au
# premier appel (token ensuite gardé dans le coffre OS, voir
# credentials.py) ; "auth": "token" lit un jeton statique déjà généré
# côté serveur (ex. page "Members" de PrestaShop) depuis le coffre OS
# (python credentials.py set mcp_token_<name> token) ; "headers_env"
# résout un jeton statique depuis une variable d'environnement. Jamais
# de secret en dur ici (fichier versionné) — même principe que
# credentials.py / DEST_FOLDER.
#
# Autres exemples de forme :
# {"name": "exemple", "transport": "stdio",
#  "command": "uvx", "args": ["mon-serveur-mcp"]}
# {"name": "exemple_http", "transport": "http",
#  "url": "https://...", "headers_env": "MON_TOKEN_ENV"}
MCP_SERVERS = [
    {"name": "notion", "transport": "http",
     "url": "https://mcp.notion.com/mcp", "auth": "oauth"},
    # Canva (via Affinity) : serveur MCP distant hébergé, OAuth 2.1. Expose
    # les outils Canva cloud (search-designs, generate-design, export…).
    # Activer aussi le toggle « Enable Affinity MCP » dans les réglages
    # d'Affinity.
    {"name": "canva", "transport": "http",
     "url": "https://mcp.canva.com/mcp", "auth": "oauth"},
    # PrestaShop MCP restreint l'accès aux emails listés dans sa page
    # "Members" (back-office du module) — le login OAuth navigateur
    # échoue si le compte connecté n'y figure pas. Jeton statique lié
    # au membre commande@studiocleuze.be à la place.
    {"name": "prestashop", "transport": "http",
     "url": "https://monobjet.be/mcp", "auth": "token"},
    # comfy-cloud : jamais autorisé (Charles utilise ComfyUI en local via
    # comfyui-local ci-dessous) — laissé actif, cette entrée brûlait 20s
    # (timeout OAuth par serveur) sur CHAQUE message, avant même d'atteindre
    # comfyui-local dans la boucle de découverte. À réactiver seulement si
    # Charles veut vraiment le service cloud en plus du local.
    # {"name": "comfy-cloud", "transport": "http",
    #  "url": "https://cloud.comfy.org/mcp", "auth": "oauth"},
    # ComfyUI local (instance sur cette machine, http://127.0.0.1:8188) —
    # serveur MCP communautaire (artokun/comfyui-mcp), lancé via npx en
    # stdio. Nécessite Node.js et ComfyUI démarré avant l'appel.
    # Désactivé temporairement le 2026-07-13 : échoue à 100% des tentatives
    # depuis le début de la session avec McpError('Connection closed') dès
    # session.initialize() — le sous-processus npx se ferme sans qu'on sache
    # encore pourquoi. Charge inutile (tentative + échec) à chaque message
    # en attendant. Réactiver une fois la cause trouvée.
    # {"name": "comfyui-local", "transport": "stdio",
    #  "command": "npx", "args": ["-y", "comfyui-mcp"],
    #  "env": {"COMFYUI_URL": "http://127.0.0.1:8188"}},
]


# ── 10.8  Serveurs SSH connus ─────────────────────────────────────────────────
# Registre de raccourcis pour l'outil ssh_command (Data/ai_tools.py) : donner
# "name" au lieu de host/username à chaque appel. Le mot de passe reste
# résolu via le coffre OS (credentials.py) / overlay Hub, jamais ici.
# Forme : {"name": "alias", "host": "...", "username": "...", "port": 22}
SSH_SERVERS = [
    {"name": "monobjet", "host": "ssh.cluster100.hosting.ovh.net",
     "username": "monobjs"},
     {"name": "raspberry pi maison", "host": "pictorsomni",
          "username": "pictorsomni"},
]


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

# Frais d'amorce par commande (mode PRINTS uniquement) — partagé entre le
# mode commande de Hub.pyw et kiosk_flet.pyw (anciennement dupliqué).
ORDER_SETUP_FEE = 1.50

SIZES = STUDIOS   # Alias conservé pour compatibilité ascendante


# ==============================================================================
# 12. DÉBRUITAGE & GRAIN PELLICULE
# ==============================================================================

# ── 12.1  Débruitage (Retouche par lot.pyw) ───────────────────────────────────
# Algorithme Non-Local Means (OpenCV fastNlMeansDenoisingColored).
# h          : force sur la luminance  (3-5 = léger, 8-12 = moyen, 15-25 = fort)
# h_color    : force sur la couleur    (idem, généralement h_color ≤ h)
# template   : taille de la fenêtre de comparaison (doit être impair, typiquement 7)
# search     : taille de la fenêtre de recherche   (doit être impair, typiquement 21)

DENOISE_H               = 4  # Force luminance
DENOISE_H_COLOR         = 2  # Force couleur
DENOISE_TEMPLATE_WINDOW = 7     # Fenêtre de comparaison (px, impair)
DENOISE_SEARCH_WINDOW   = 21    # Fenêtre de recherche   (px, impair)


# ── 12.2  Grain pellicule (Retouche par lot.pyw) ──────────────────────────────
# Simulation de grain argentique avec pondération par luminance.
# amount            : intensité du grain  (0.0 = aucun, 0.05 = fin ISO 100, 0.15 = ISO 800, 0.30 = ISO 3200)
# size              : taille du grain en % de la plus petite dimension (0.1 = fin, 0.3 = moyen, 0.6 = gros)
# color_ratio       : part de grain couleur mélangée au grain monochrome
#                     0.0 = grain 100 % monochrome (aucune variation de teinte)
#                     0.3 = légère variation chromatique (réaliste, style film négatif)
#                     1.0 = variation couleur maximale par canal R/G/B
# shadow_boost      : concentration du grain sur les mi-tons (1 = large/plat, 2 = centré, 3 = serré)
# chroma_shift      : décalage spatial en % de la plus petite dimension entre les canaux R/G/B
#                     (simule le désalignement des couches d'émulsion argentique).
#                     0 = désactivé, 0.1 = subtil, 0.3 = prononcé.

GRAIN_AMOUNT       = 0.015  # Micro-grain subtil
GRAIN_SIZE         = 0.06  # Très fin (~2.4 px sur 4000 px)
GRAIN_COLOR_RATIO  = 0.15  # Couleur très discrète
GRAIN_SHADOW_BOOST = 1.5  # Distribution assez large
GRAIN_CHROMA_SHIFT = 0.15  # Léger décalage du micro-grain
GRAIN_FLOOR        = 0.3  # Grain résiduel dans les zones sombres

GRAIN2_AMOUNT       = 0.01  # Couche 2 — intensité
GRAIN2_SIZE         = 0.18  # Couche 2 — taille (% de la plus petite dimension)
GRAIN2_COLOR_RATIO  = 0.25  # Couche 2 — part couleur
GRAIN2_SHADOW_BOOST = 3.0  # Couche 2 — concentration mi-tons
GRAIN2_CHROMA_SHIFT = 0.25  # Couche 2 — décalage inter-canal
GRAIN2_FLOOR        = 0.3  # Grain résiduel dans les zones sombres


# ── 12.3  Halation & Bloom (Retouche par lot.pyw) ─────────────────────────────
# Halation : halo rougeâtre autour des hautes lumières, reproduisant la lumière
#            qui rebondit sur la base du film et expose l'émulsion une seconde fois.
# threshold  : luminance minimale pour qualifier un pixel de haute lumière
#              (0.55 = hautes lumières larges, 0.65 = standard, 0.80 = éclats seuls)
# radius     : rayon du flou exprimé en % de la plus petite dimension de l'image
#              (1 = discret, 5 = standard, 15 = très prononcé)
# intensity  : intensité additive (0.0 = aucun, 0.4 = visible, 1.0 = très fort)
# red_shift  : force du décalage chaud/rouge   (0.0 = neutre, 0.8 = standard, 1.0 = rouge vif)

HALATION_ENABLED    = False
HALATION_THRESHOLD  = 0.72  # 0.55 large · 0.65 standard · 0.80 éclats seuls
HALATION_RADIUS     = 5  # % de la plus petite dimension
HALATION_INTENSITY  = 0.5  # additif : 0.1 discret · 0.3 visible · 0.6 fort
HALATION_RED_SHIFT  = 0.42  # 0.0 neutre · 0.5 chaud · 1.0 rouge vif

# Bloom : glow général obtenu en superposant l'image floutée en mode Screen.
# radius    : rayon du flou exprimé en % de la plus petite dimension de l'image
#             (2 = discret, 6 = standard, 15 = prononcé)
# intensity : intensité additive (0.0 = aucun, 0.4 = visible, 1.0 = très fort)

BLOOM_ENABLED    = False
BLOOM_RADIUS     = 16
BLOOM_INTENSITY  = 0.64

# ── 12.4  Désaturation des extrêmes + boost mi-tons (Retouche par lot.pyw) ────
# Les films argentiques perdent de la saturation dans les ombres très sombres
# et dans les hautes lumières très claires (compression des couleurs aux extrêmes).
# shadow_threshold    : luma en dessous duquel l'effet s'applique (0.0–1.0)
# shadow_intensity    : force de la désaturation dans les ombres   (0.0 = aucun, 1.0 = gris pur)
# highlight_threshold : luma au-dessus duquel l'effet s'applique   (0.0–1.0)
# highlight_intensity : force de la désaturation dans les hautes lumières
# midtone_boost       : saturation supplémentaire dans les mi-tons (0 = aucun, 0.3 = prononcé)
#                       masque = (1 - shadow_mask) × (1 - highlight_mask) — pic en plein mi-ton

DESAT_ENABLED             = False
DESAT_SHADOW_THRESHOLD    = 0.2  # ombres sous 25 % de luminosité
DESAT_SHADOW_INTENSITY    = 1.0  # désaturation dans les noirs
DESAT_HIGHLIGHT_THRESHOLD = 0.8  # hautes lumières au-dessus de 80 %
DESAT_HIGHLIGHT_INTENSITY = 1.0  # désaturation dans les blancs
DESAT_MIDTONE_BOOST       = 0.1  # boost de saturation en mi-tons (0 = aucun, 0.3 = prononcé)


# ── 12.6  Aberrations chromatiques optiques (Retouche par lot.pyw) ───────────
# Simule le désalignement focal des canaux R/G/B d'une vieille optique :
# le canal R est légèrement agrandi (zoom radial vers l'extérieur) et le canal B
# légèrement rétréci, G restant la référence. L'effet produit des franges colorées
# sur les bords des contrastes, accentuées vers les coins de l'image.
# strength : intensité en % de la diagonale (0.3 = subtil, 1.0 = prononcé, 2.0 = fort)

CA_ENABLED     = False
CA_STRENGTH    = 0.05  # % de la diagonale de l'image
CA_AXIAL_RATIO = 0.64  # part de la composante axiale (0 = purement radial, 1 = égal au radial)


# ── 12.7  Virage / teinte (Retouche par lot.pyw) ──────────────────────────────
# Vieilles photos scannées : le jaunissement d'origine varie d'un scan à
# l'autre — colorize_hsl/colorize_multiply (image_ops.py) repartent d'un
# noir et blanc pur puis colorisent chaque préréglage selon l'un des deux
# modes ci-dessous (retour user : chacun est meilleur selon l'effet visé —
# pas un remplace l'autre).
#
#   "colorize" : substitution HSL, comme "Teinte et saturation > Coloriser"
#                dans Photoshop/Affinity (noir en L=0, blanc en L=1, teinte
#                pleine au milieu). Meilleur rendu pour SEPIA/N&B ANCIEN.
#                Champs : hue (0-360), sat (% 0-100).
#   "multiply"  : calque couleur unie HSL + mode de fusion "Multiplier"
#                (résultat = gris × couleur), comme dans Affinity/Photoshop.
#                La teinte reste visible jusque dans les hautes lumières au
#                lieu de désaturer vers le blanc pur — nécessaire pour JAUNI
#                (hautes lumières "cramées" en mode colorize sur un scan
#                déjà proche du blanc). Champs : hue, sat, light (% 0-100) —
#                mêmes chiffres que le sélecteur HSL d'Affinity/Photoshop.
#
# Une option de menu déroulant est générée dans Retouche par lot.pyw pour
# chaque entrée : ajouter/modifier un préréglage ici suffit, rien à changer
# côté interface.
# Repères de teinte : ~30-50° = sépia/jauni (brun-jaune), ~90-110° = vert,
# ~200-220° = bleu (cyanotype).
#
# "shadow_lift" (optionnel, % 0-100, défaut 0) : remonte le point noir AVANT
# colorisation — gris=0 -> shadow_lift, gris=255 -> inchangé (comme un pied
# de courbe argentique, cf. lift_shadows dans image_ops.py). Rend
# l'image moins sombre sans toucher les hautes lumières colorées (retour
# user : réduire la densité à l'impression pour éclaircir fait perdre la
# teinte des HL — il faut éclaircir dans le fichier, pas à l'imprimante).

VIRAGE_PRESETS = {
    "SEPIA":       {"mode": "colorize", "hue": 25,  "sat": 25},  # retour user : réglage Photoshop/Affinity habituel
    "JAUNI":       {"mode": "multiply", "hue": 46,  "sat": 85, "light": 85, "shadow_lift": 10},  # retour user : image trop sombre de base
    "N&B ANCIEN":  {"mode": "colorize", "hue": 150, "sat": 4},
    "N&B":         {"mode": "colorize", "hue": 0,   "sat": 0},
}
VIRAGE_DEFAULT_PRESET = "SEPIA"


# ── 12.8  Retouche par lot — réglages complémentaires (Retouche par lot.pyw) ──
# États "activé" par section et valeurs sans équivalent partagé ailleurs
# (couleur, netteté, virage manuel, copyright) — les autres champs de
# l'outil réutilisent les constantes 12.1-12.7 ci-dessus. Réécrites
# automatiquement par le bouton "Enregistrer comme réglages par défaut" de
# l'outil : modifier à la main ici change juste la valeur de repli tant que
# personne n'a encore cliqué ce bouton.

RETOUCHE_LOT_DENOISE_ENABLED = False

RETOUCHE_LOT_COULEUR_ENABLED       = False
RETOUCHE_LOT_COULEUR_EXPOSURE      = 0
RETOUCHE_LOT_COULEUR_CONTRAST      = 0
RETOUCHE_LOT_COULEUR_SATURATION    = 7
RETOUCHE_LOT_COULEUR_HUE           = 0
RETOUCHE_LOT_COULEUR_WHITE_BALANCE = 0
RETOUCHE_LOT_COULEUR_HIGHLIGHTS    = -10
RETOUCHE_LOT_COULEUR_SHADOWS       = 10
RETOUCHE_LOT_COULEUR_WHITES        = 0
RETOUCHE_LOT_COULEUR_BLACKS        = 0

RETOUCHE_LOT_VIRAGE_ENABLED = False
RETOUCHE_LOT_VIRAGE_MODE    = 'colorize'
RETOUCHE_LOT_VIRAGE_HUE     = 25
RETOUCHE_LOT_VIRAGE_SAT     = 25
RETOUCHE_LOT_VIRAGE_LIGHT   = 50

# LUT 3D (.cube, Adobe/DaVinci Resolve) — fichiers dans Data/LUTs, listés
# à la volée par Retouche par lot.pyw (rien à déclarer ici par LUT).
# NAME = nom de fichier retenu ("" = aucun), INTENSITY = mélange 0-100 %
# avec l'image d'origine.
RETOUCHE_LOT_LUT_ENABLED   = False
RETOUCHE_LOT_LUT_NAME      = 'M31 - Rec.709.cube'
RETOUCHE_LOT_LUT_INTENSITY = 15

RETOUCHE_LOT_NETTETE_ENABLED  = False
RETOUCHE_LOT_NETTETE_RADIUS1  = 4
RETOUCHE_LOT_NETTETE_PERCENT1 = 42
RETOUCHE_LOT_NETTETE_RADIUS2  = 2
RETOUCHE_LOT_NETTETE_PERCENT2 = 42

RETOUCHE_LOT_GRAIN_ENABLED  = False
RETOUCHE_LOT_GRAIN1_ENABLED = False
RETOUCHE_LOT_GRAIN2_ENABLED = False

RETOUCHE_LOT_COPYRIGHT_ENABLED     = False
RETOUCHE_LOT_COPYRIGHT_MODE        = 'date'
RETOUCHE_LOT_COPYRIGHT_CUSTOM_TEXT = ''

# Rayon de netteté (12.9) et fenêtres de débruitage (12.1) exprimés en px
# pour une image de cette taille (côté le plus petit) ; mis à l'échelle
# proportionnellement à la résolution réelle de chaque image traitée
# (aperçu réduit ou export plein format) — sans ça, un même réglage de
# netteté paraît beaucoup plus fort sur l'aperçu (réduit à
# RETOUCHE_LOT_PREVIEW_MAX_PIXELS) que sur l'export final en pleine
# résolution (retour user).
RETOUCHE_LOT_REFERENCE_PX = 4000

# Taille max (px, côté le plus long) du proxy d'aperçu — plus grande que
# PREVIEW_MAX_PIXELS (partagée avec Recadrage manuel.pyw) car cet outil a
# aussi besoin d'un aperçu fidèle du grain pellicule : sur un proxy trop
# petit affiché quasiment à l'échelle 1:1, le grain paraît plus grossier
# qu'il ne le sera réellement une fois affiché/imprimé en pleine résolution
# (retour user). Augmenter ralentit l'aperçu live (débruitage/netteté/
# grain recalculés à chaque réglage).
# Plancher : comme PREVIEW_MAX_PIXELS, la taille réelle du proxy est calculée
# d'après celle du widget d'aperçu × PREVIEW_SUPERSAMPLING, plafonnée par
# RETOUCHE_LOT_PREVIEW_CEILING.
RETOUCHE_LOT_PREVIEW_MAX_PIXELS = 1600

# Plafond propre à cet outil, plus haut que PREVIEW_MAX_PIXELS_CEILING pour la
# même raison que le plancher ci-dessus : le grain pellicule ne se juge pas sur
# un proxy trop réduit.
RETOUCHE_LOT_PREVIEW_CEILING = 3200


# ==============================================================================
# 13. WAND / IMAGEMAGICK (Conversion JPG.py, thumb_cache.py)
# ==============================================================================
def ensure_imagemagick_env():
    """Renseigne MAGICK_HOME sur macOS avant d'importer ``wand``.

    ``wand`` localise la lib via ctypes.util.find_library(), qui ne regarde
    pas dans /opt/homebrew/lib ni /usr/local/lib : sans MAGICK_HOME, l'import
    échoue même quand `brew install imagemagick` est à jour.
    """
    import platform
    if platform.system() != "Darwin" or os.environ.get("MAGICK_HOME"):
        return
    for prefix in ("/opt/homebrew/opt/imagemagick", "/usr/local/opt/imagemagick"):
        if os.path.isdir(os.path.join(prefix, "lib")):
            os.environ["MAGICK_HOME"] = prefix
            break


def is_icloud_placeholder(path, stat_result=None):
    """True si ``path`` est un fichier iCloud Drive pas encore rapatrié sur
    le disque (évincé par "Optimiser le stockage Mac").

    ``st_blocks == 0`` avec une taille non nulle = le contenu n'existe pas
    localement : l'ouvrir (miniature, PIL...) forcerait macOS à le
    télécharger. Sur un dossier de plusieurs centaines de fichiers ainsi
    évincés, ça déclenche une rafale de téléchargements iCloud qui peut
    saturer toute la machine (incident du 2026-07-18 : remonter deux fois
    de dossier dans Hub a suffi à geler tout le Mac, forçant un arrêt
    forcé).
    """
    import platform
    if platform.system() != "Darwin" or "Mobile Documents" not in path:
        return False
    try:
        st = stat_result or os.stat(path)
        return st.st_size > 0 and st.st_blocks == 0
    except OSError:
        return False


# ==============================================================================
# 13bis. PERSISTANCE JSON — lecture tolérante, écriture atomique
# ==============================================================================
# Utilisé par Hub.pyw (dossiers récents, favoris, commande, scores…) et
# ai_tools.py (historique de conversation). Une seule implémentation :
# c'est le chemin par lequel passent les données que l'utilisateur perdrait
# vraiment si un fichier était tronqué.

# Rapporteur d'échec d'écriture, posé par l'app hôte (Hub.pyw le branche
# sur son terminal intégré). Sans lui, un disque plein ou un dossier passé
# en lecture seule faisait disparaître la commande client sans un mot.
save_error_hook = {"fn": None}


def load_json(path, default):
    """Lit un JSON, renvoie ``default`` si le fichier manque ou est illisible."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    """Écrit ``data`` en JSON de façon atomique. Renvoie True si écrit.

    Passe par un fichier temporaire puis os.replace() (atomique sur
    Windows/macOS/Linux) : un open("w") direct VIDE le fichier avant
    d'écrire, donc un plantage ou une extinction en plein json.dump
    laissait un .order.json tronqué — la commande client en cours perdue.
    """
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as exc:
        try:
            os.remove(tmp)
        except OSError:
            pass
        report = save_error_hook["fn"]
        if report:
            report(f"[ERREUR] Échec d'enregistrement de "
                   f"{os.path.basename(path)} : {exc}")
        return False


# ==============================================================================
# 14. FLET — bandeau "Copier l'erreur" (Retouche par lot.pyw, Comparaison.pyw,
#     kiosk_flet.pyw, Recadrage manuel.pyw, Hub.pyw)
# ==============================================================================
def attach_error_copy_snackbar(page, ignore=()):
    """Sur une exception non interceptée (page.on_error), affiche le
    message dans un SnackBar avec un bouton Copier — pour le remonter sans
    avoir à le retaper à la main.

    ``ignore`` : sous-chaînes de messages à avaler silencieusement, pour les
    erreurs Flutter bénignes et auto-résolues (ex. la race de décodage
    "Codec failed..." lors de mises à jour rapides d'un ft.Image en
    base64 pendant le chargement — cf. Retouche par lot.pyw)."""
    import flet as ft

    def _on_error(e):
        message = str(getattr(e, "data", None) or e)
        if any(needle in message for needle in ignore):
            return

        async def _copy(_):
            await page.clipboard.set(message)

        page.show_dialog(ft.SnackBar(
            ft.Text(message, color="#000000", selectable=True),
            bgcolor=COLOR_RED, duration=6000, show_close_icon=True,
            action=ft.SnackBarAction(label="Copier", text_color="#000000",
                                     on_click=_copy),
        ))

    page.on_error = _on_error
