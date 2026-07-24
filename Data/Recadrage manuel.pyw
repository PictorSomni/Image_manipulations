# -*- coding: utf-8 -*-
"""
Recadrage manuel.pyw — Outil de recadrage photo interactif (Flet / PIL)
================================================================

Application de bureau multi-plateforme permettant de recadrer des photos
en lot selon des formats d'impression standards (tirages argentiques, photos
d'identité, etc.).

Fonctionnalités principales
----------------------------
* Recadrage interactif par glisser-déposer, zoom molette et pinch-to-zoom.
* Rotation fine (−15° … +15°) avec rendu aperçu en temps réel.
* Mode « Fit-in » : l'image entière tient dans le format (bords blancs).
* Noir & blanc, exposition, contraste, saturation, ombres, hautes lumières.
* Mise en page automatique : 2-en-1, ID ×2 / ×4, Polaroid, border 13x15,
  border 20x24, border 13x10.
* Formats multiples par image (plusieurs cadrages distincts sauvegardés
  en un seul clic via la liste « Formats multiples »).
* Mode batch interactif : toutes les images d'un dossier sont proposées
  l'une après l'autre ; l'opérateur valide ou ignore chaque photo.
* Export JPEG 300 dpi, espace colorimétrique sRGB avec profil ICC embarqué.

Dépendances
-----------
* flet    — interface graphique (widgets, événements, rendu)
* Pillow  — traitement d'image (recadrage, filtres, conversion couleur)
* numpy   — calculs LUT rapides (courbes ombres, hautes lumières, exposition)

Variables d'environnement reconnues
------------------------------------
FOLDER_PATH      : dossier source des images (défaut : répertoire courant)
SELECTED_FILES   : liste de noms de fichiers séparés par « | » à traiter
                   en priorité dans le dossier source

Raccourcis clavier
------------------
Entrée              : valider et passer à l'image suivante
Backspace / Suppr    : basculer l'orientation portrait / paysage
Espace              : ignorer l'image courante et passer à la suivante
Tab                 : basculer le mode de défilement de la souris entre zoom et rotation
+  /  =             : zoom avant
-                   : zoom arrière
0                   : réinitialiser le zoom à 1×
"""

__version__ = "3.1.0"

# ==============================================================================
# TABLE DES MATIÈRES — Recadrage manuel.pyw
# ==============================================================================
# 1. IMPORTS & CONFIGURATION ...................................... ~L 70
# 2. COULEURS ..................................................... ~L 100
# 3. CONSTANTES DE LAYOUT ......................................... ~L 115
# 4. FONCTIONS UTILITAIRES (mm→px, sRGB, érosion alpha) ........... ~L 125
# 5. CLASSE VerticalSlider ......................................... ~L 235
# 6. CLASSE PhotoCropper ........................................... ~L 405
#    6.1  __init__  — Initialisation de l'état ..................... ~L 430
#    6.2  Statut inline ............................................ ~L 880
#    6.3  Canvas & transformations ................................. ~L 925
#    6.4  Chargement des images .................................... ~L 1090
#    6.5  Traitement par lot ....................................... ~L 1300
#    6.6  Calcul du recadrage ...................................... ~L 1390
#    6.7  Mode Fit-in .............................................. ~L 1670
#    6.8  Construction des planches (2-en-1, ID×4, Polaroid) ....... ~L 1730
#    6.9  Amélioration & ajustements (couleurs, N&B, rembg) ........ ~L 1870
#    6.10 Rendu (histogramme, aperçu) .............................. ~L 2080
#    6.11 Gestionnaires de gestes (scroll, zoom, rotation) ......... ~L 2275
#    6.12 Réinitialisations & sliders .............................. ~L 2400
#    6.13 Format & orientation ..................................... ~L 3190
#    6.14 Formats multiples & exemplaires .......................... ~L 3410
#    6.15 Actions : validation & export ............................ ~L 3560
#    6.16 Ignorer une image ........................................ ~L 3995
# 7. INTERFACE PRINCIPALE main() .................................. ~L 4080
# ==============================================================================

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS
import image_ops
import shutil
import platform
import queue
import re
import threading
import time
from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageCms, ImageDraw
import asyncio
import contextlib
import math
import io
import base64
import numpy as np
import importlib.util

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")  # Supprimer les avertissements de performance d'onnxruntime
REMBG_AVAILABLE = importlib.util.find_spec("rembg") is not None

# ===================== Configuration ===================== #
MAX_CANVAS_SIZE = 1200  # Taille max du canvas
CONTROLS_WIDTH = 270    # Largeur de la colonne de contrôles
DPI = CONSTANTS.DPI  # Résolution d'export
PREVIEW_MAX_PIXELS = CONSTANTS.PREVIEW_MAX_PIXELS  # Taille max (px, côté le plus long) de la prévisualisation
ID_X4_10x20_PHOTOS_BOTTOM = CONSTANTS.ID_X4_10x20_PHOTOS_BOTTOM  # True = photos moitié basse, False = photos moitié haute
_IS_MAC = platform.system() == "Darwin"   # Raccourcis clavier spécifiques macOS
CANVAS_CHROME_WIDTH = 160  # Sliders latéraux + espacements autour du canevas

# Formats d'impression (largeur_mm, hauteur_mm) - en portrait
FORMATS = CONSTANTS.FORMATS
_CUSTOM_KEY = "Personnalisé"

# ===================== COULEURS ===================== #
DARK         = CONSTANTS.COLOR_DARK
BG           = CONSTANTS.COLOR_BACKGROUND
GREY         = CONSTANTS.COLOR_GREY
LIGHT_GREY   = CONSTANTS.COLOR_LIGHT_GREY
BLUE         = CONSTANTS.COLOR_BLUE
VIOLET       = CONSTANTS.COLOR_VIOLET
GREEN        = CONSTANTS.COLOR_GREEN
YELLOW       = CONSTANTS.COLOR_YELLOW
HOVER_YELLOW = CONSTANTS.COLOR_HOVER_YELLOW
ORANGE       = CONSTANTS.COLOR_ORANGE
RED          = CONSTANTS.COLOR_RED
WHITE        = CONSTANTS.COLOR_WHITE



# ===================== Layout ===================== #
LEFT_COL_WIDTH   = 250   # Largeur de la colonne de gauche (réglages sliders)
RIGHT_COL_WIDTH  = 250   # Largeur de la colonne de droite (formats + histogramme + boutons)
HISTOGRAM_HEIGHT = 85    # Hauteur de l'histogramme en pixels


# Géométrie/couleur/sRGB/érosion alpha : logique partagée avec Hub.pyw,
# extraite dans image_ops.py pour ne plus être dupliquée entre les deux
# apps (voir docs/HUB_SPEC.md §14).
mm_to_pixels = image_ops.mm_to_pixels
convert_to_srgb = image_ops.convert_to_srgb
_erode_alpha = image_ops.erode_alpha
_feather_alpha = image_ops.feather_alpha
_SRGB_ICC = image_ops._SRGB_ICC



# ================================================================ #
#                     SLIDER VERTICAL CUSTOM                       #
# ================================================================ #

class _VertSliderEvent:
    """Événement simulé pour compatibilité avec les callbacks (e.control.value / label / update)."""
    def __init__(self, control):
        self.control = control


class VerticalSlider:
    """
    Slider vertical personnalisé basé sur GestureDetector.

    Expose la même interface que ft.Slider (value, label, max, update())
    utilisée par le code PhotoCropper, avec une détection de gestes
    verticale correcte sur toute la hauteur du contrôle.

    Le bas correspond au minimum et le haut au maximum.
    Double-tap → callback on_double_tap (ex : reset).
    """

    _TRACK_W = 4
    _THUMB_D = 30
    _COL_W   = 44
    _LBL_OFFSET = 10  # espace entre le bord droit du thumb et le label

    def __init__(self, *, min_val, max_val, initial_val,
                 on_change=None, on_change_end=None, on_double_tap=None,
                 active_color=ft.Colors.BLUE, track_height=500):
        self._min      = float(min_val)
        self._max      = float(max_val)
        self._value    = float(initial_val)
        self._on_change     = on_change
        self._on_change_end = on_change_end
        self._on_dbl_tap    = on_double_tap
        self._color    = active_color
        self._h        = track_height
        self.label     = ""

        cx = (self._COL_W - self._TRACK_W) // 2  # centre horizontal de la piste

        self._bg_track = ft.Container(
            width=self._TRACK_W, height=track_height,
            bgcolor=ft.Colors.with_opacity(0.30, active_color),
            border_radius=self._TRACK_W,
            left=cx, top=0,
        )
        self._fg_track = ft.Container(
            width=self._TRACK_W, height=0,
            bgcolor=active_color,
            border_radius=self._TRACK_W,
            left=cx, top=track_height,
        )
        self._thumb = ft.Container(
            width=self._THUMB_D, height=self._THUMB_D,
            border_radius=self._THUMB_D // 2,
            bgcolor=active_color,
            left=(self._COL_W - self._THUMB_D) // 2,
            top=0,
        )
        self._lbl = ft.Text(
            "", size=11, color=active_color,
            weight=ft.FontWeight.BOLD,
            left=self._COL_W + self._LBL_OFFSET, top=0,
        )

        self._gesture = ft.GestureDetector(
            content=ft.Container(
                width=self._COL_W, height=track_height,
                bgcolor=ft.Colors.TRANSPARENT,
            ),
            on_pan_start=self._pan_start,
            on_pan_update=self._pan_update,
            on_pan_end=self._pan_end,
            on_double_tap=self._dbl_tap,
        )

        self.control = ft.Stack(
            controls=[self._bg_track, self._fg_track, self._thumb, self._lbl, self._gesture],
            width=self._COL_W,  # label déborde via clip_behavior=NONE sans occuper d'espace layout
            height=track_height,
            clip_behavior=ft.ClipBehavior.NONE,
        )
        self._refresh()

    # ── Propriétés (interface ft.Slider) ────────────────────────────────

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = float(v)
        self._refresh()

    @property
    def max(self):
        return self._max

    def update(self):
        """Synchronise le visuel avec l'état courant (appelé par les callbacks)."""
        self._refresh()
        self._thumb.update()
        self._fg_track.update()
        self._lbl.update()

    # ── Visuel ──────────────────────────────────────────────────────────

    def _val_to_top(self, v):
        """Convertit une valeur en position Y du centre du curseur (0=haut=max)."""
        ratio = (v - self._min) / (self._max - self._min)
        return int(self._h * (1.0 - ratio))

    def _top_to_val(self, top):
        ratio = 1.0 - top / self._h
        return max(self._min, min(self._max, self._min + ratio * (self._max - self._min)))

    def _refresh(self):
        center_y  = self._val_to_top(self._value)
        thumb_top = max(0, min(self._h - self._THUMB_D, center_y - self._THUMB_D // 2))
        self._thumb.top = thumb_top
        self._fg_track.top    = center_y
        self._fg_track.height = max(0, self._h - center_y)
        self._lbl.top   = max(0, thumb_top - 6)
        self._lbl.value = self.label

    def _update_thumb(self):
        """Mise à jour rapide pendant le glissement (sans update() du Stack)."""
        center_y  = self._val_to_top(self._value)
        thumb_top = max(0, min(self._h - self._THUMB_D, center_y - self._THUMB_D // 2))
        self._thumb.top = thumb_top
        self._fg_track.top    = center_y
        self._fg_track.height = max(0, self._h - center_y)
        self._thumb.update()
        self._fg_track.update()

    # ── Gestes ──────────────────────────────────────────────────────────
    # Flet 0.85 : DragUpdateEvent expose e.local_delta.y (pas e.local_y).
    # On accumule directement les deltas sur self._value.

    def _pan_start(self, e):
        pass  # rien à faire — on accumule les deltas dans _pan_update

    def _pan_update(self, e):
        dy = e.local_delta.y
        delta = -(dy / self._h) * (self._max - self._min)
        self._value = max(self._min, min(self._max, self._value + delta))
        self._update_thumb()
        if self._on_change:
            self._on_change(_VertSliderEvent(self))

    def _pan_end(self, e):
        if self._on_change_end:
            self._on_change_end(_VertSliderEvent(self))

    def _dbl_tap(self, e):
        if self._on_dbl_tap:
            self._on_dbl_tap(e)

    # ── Redimensionnement ────────────────────────────────────────────────

    def resize(self, new_height):
        """Met à jour la hauteur du slider (appelé lors du redimensionnement de la fenêtre)."""
        self._h = new_height
        self._bg_track.height          = new_height
        self._gesture.content.height   = new_height
        self.control.height            = new_height
        self._refresh()
        self.control.update()


#############################################################
#                         CONTENT                           #
#############################################################
class PhotoCropper:
    """
    Logique principale de l'application de recadrage photo.

    Cette classe centralise l'état de l'application, la construction des
    widgets Flet et toutes les méthodes de traitement d'image. Elle reçoit
    la `page` Flet fournie par le runtime et construit elle-même tous les
    contrôles (sliders, switches, boutons, canvas) qui sont ensuite montés
    dans la mise en page de la fonction `main`.

    Organisation interne
    --------------------
    État du batch
        image_paths, current_index, batch_mode, source_folder
    Configuration du canevas
        current_format, canvas_is_portrait, canvas_w, canvas_h
    Transformation interactive
        scale, offset_x, offset_y, base_scale, rotation
    Filtres actifs
        is_bw, is_sharpen, fit_in, contrast, saturation, exposure,
        shadows, highlights, enhance_toggle
    Mise en page / planches
        border_polaroid,
        border_id2, border_id4, copies_count, extra_formats
    Cache prévisualisation
        _preview_tmp_dir, _preview_counter, _prev_preview_path
    """

    def __init__(self, page: ft.Page):
        """
        Initialise l'application et construit tous les widgets Flet.

        La méthode réalise dans l'ordre :
          1. Création du répertoire de cache pour les prévisualisations
             temporaires (`.preview_cache`) et nettoyage des éventuels
             résidus d'une session précédente.
          2. Initialisation de toutes les variables d'état (voir attributs
             listés dans la docstring de la classe).
          3. Instanciation de chaque widget Flet (sliders, switches, boutons,
             GestureDetector, Stack, Container canvas).

          Les widgets ne sont PAS ajoutés à la page ici ; c'est la fonction
          `main` qui les monte dans la mise en page finale.

        Parameters
        ----------
        page : ft.Page
            La page Flet fournie par `ft.run(main)`.  Elle sert à :
            - déclencher les rafraîchissements visuels (page.update())
            - lire les dimensions courantes de la fenêtre
            - modifier le titre de la fenêtre
        """

        self.page = page

        # État du batch
        self.image_paths = []
        self.current_index = 0
        self.batch_mode = False
        self._preloaded = False
        self.source_folder = os.environ.get("FOLDER_PATH", os.getcwd())



        # Dossier de prévisualisation temporaire (au plus 1 fichier à la fois)
        self._preview_tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preview_cache")
        os.makedirs(self._preview_tmp_dir, exist_ok=True)



        # Vider les éventuels résidus d'une session précédente
        # (shutil.rmtree + makedirs est atomique et robuste même si le dossier
        #  est sur un volume USB avec des fichiers encore ouverts/verrouillés)
        try:
            shutil.rmtree(self._preview_tmp_dir, ignore_errors=True)
            os.makedirs(self._preview_tmp_dir, exist_ok=True)
        except OSError:
            pass
        self._preview_counter = 0
        self._prev_preview_path = None



        # Configuration du canvas (calculé dynamiquement)
        self.canvas_is_portrait = True
        self.current_format = FORMATS["ID"]
        self.current_format_label = "ID"
        self.custom_format = (100, 100)         # dimensions libres (Personnalisé)
        self.custom_fields_row = None            # initialisé dans main() avant usage
        self.custom_panel = None                 # container séparé, initialisé dans main()
        self.border_polaroid = CONSTANTS.RECADRAGE_BORDER_POLAROID
        self.border_id2 = CONSTANTS.RECADRAGE_BORDER_ID2
        self.border_id4 = CONSTANTS.RECADRAGE_BORDER_ID4
        self.id4_10x20 = CONSTANTS.RECADRAGE_ID4_10x20       # Planche ID X4 en format 10x20 (moitié haute blanche)
        self._id4_10x20_pending = None  # id_photo de la 1ère identité en attente de sa paire
        self._id4_10x20_seq = 0  # compteur séquentiel des feuillets 10x20 sauvegardés (ID_01, ID_02, ...)
        self.save_to_network = CONSTANTS.RECADRAGE_SAVE_TO_NETWORK  # Sauvegarder les ID X4 sur le réseau par défaut
        self.enhance_toggle = False  # Retro-compat snapshots anciens
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w * self.current_format[1] / self.current_format[0]
        self.display_w = int(self.canvas_w)   # initialisé avant tout chargement d'image
        self.display_h = int(self.canvas_h)   # pour éviter AttributeError dans _clamp_offsets



        # Gestion du zoom et transformation
        self.scale = 1.0          # Scale actuel
        self.offset_x = 0.0       # Offset X en pixels
        self.offset_y = 0.0       # Offset Y en pixels
        self.base_scale = 1.0
        self.pinch_start_scale = 1.0  # Scale au début du pinch
        self._last_pan_render = 0.0   # Throttle pan : horodatage du dernier update
        self._last_rotation_render = 0.0  # Throttle rotation
        self._last_zoom_render = 0.0      # Throttle zoom
        self._scroll_rotates = CONSTANTS.RECADRAGE_SCROLL_ROTATES       # Tab bascule défilement trackpad → rotation
        self._gesture_scale_start = 1.0    # Scale au début du geste (suivi pour le zoom)
        self._gesture_rotation_prev = 0.0  # Rotation cumulée depuis le début du geste (radians)



        # Option noir et blanc
        self.is_bw = CONSTANTS.RECADRAGE_IS_BW



        # Rotation
        self.rotation = 0.0

        # Sliders verticaux personnalisés (GestureDetector — détection sur toute la hauteur)
        self.rotation_slider = VerticalSlider(
            min_val=-15.0, max_val=15.0, initial_val=0.0,
            on_change=self.on_rotation_update,
            on_change_end=self.on_rotation_end,
            on_double_tap=lambda e: self.reset_rotation(e),
            active_color=BLUE,
            track_height=int(self.canvas_h),
        )

        self.rotation_slider_col = ft.Column([
            ft.Text("ROTATION", size=10, weight=ft.FontWeight.BOLD, color=BLUE),
            self.rotation_slider.control,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, alignment=ft.MainAxisAlignment.CENTER)

        self.zoom_slider = VerticalSlider(
            min_val=1.0, max_val=3.0, initial_val=1.0,
            on_change=self.on_zoom_update,
            on_change_end=self.on_zoom_end,
            on_double_tap=lambda e: self.reset_zoom(e),
            active_color=BLUE,
            track_height=int(self.canvas_h),
        )

        self.zoom_slider_col = ft.Column([
            ft.Text("ZOOM", size=10, weight=ft.FontWeight.BOLD, color=BLUE),
            self.zoom_slider.control,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10, alignment=ft.MainAxisAlignment.CENTER)



        # Ombres (Shadows — similaire à Camera Raw)
        self.shadows = float(CONSTANTS.RECADRAGE_DEFAULT_SHADOWS)
        self.shadows_slider = ft.Slider(
            value=self.shadows,
            min=-100,
            max=100,
            divisions=20,
            label=str(CONSTANTS.RECADRAGE_DEFAULT_SHADOWS),
            active_color=YELLOW,
            on_change=self.on_shadows_label,
            on_change_end=self.on_shadows_end,
        )



        # Hautes lumières (Highlights — similaire à Camera Raw)
        self.highlights = float(CONSTANTS.RECADRAGE_DEFAULT_HIGHLIGHTS)
        self.highlights_slider = ft.Slider(
            value=self.highlights,
            min=-100,
            max=100,
            divisions=20,
            label=str(CONSTANTS.RECADRAGE_DEFAULT_HIGHLIGHTS),
            active_color=YELLOW,
            on_change=self.on_highlights_label,
            on_change_end=self.on_highlights_end,
        )

        # Blancs / Noirs (points blanc et noir — similaire à Lightroom).
        # Contrairement à Hautes lumières/Ombres (courbes nulles aux
        # extrémités : le blanc pur et le noir pur ne bougent jamais),
        # ces curseurs déplacent les points EXTRÊMES — indispensable pour
        # recaler un scan trop clair dont le blanc doit redescendre
        # (retour user).
        self.whites = 0.0
        self.whites_slider = ft.Slider(
            value=self.whites,
            min=-100,
            max=100,
            divisions=20,
            label="0",
            active_color=YELLOW,
            on_change=self.on_whites_label,
            on_change_end=self.on_whites_end,
        )
        self.blacks = 0.0
        self.blacks_slider = ft.Slider(
            value=self.blacks,
            min=-100,
            max=100,
            divisions=20,
            label="0",
            active_color=YELLOW,
            on_change=self.on_blacks_label,
            on_change_end=self.on_blacks_end,
        )



        # Nombre d'exemplaires
        self.copies_count = 1
        self.copies_text = ft.Text(
            "1",
            size=22,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
            width=36,
            color=WHITE,
        )
        self.copies_minus_btn = ft.IconButton(
            icon=ft.Icons.REMOVE,
            icon_color=WHITE,
            icon_size=20,
            on_click=self.decrement_copies,
            tooltip="Moins",
        )
        self.copies_plus_btn = ft.IconButton(
            icon=ft.Icons.ADD,
            icon_color=BLUE,
            icon_size=20,
            on_click=self.increment_copies,
            tooltip="Plus",
        )



        # Formats multiples
        self.extra_formats = []  # list of snapshot dicts with full view state
        self.extra_formats_display = ft.Text("—", size=11, color=LIGHT_GREY, max_lines=1, text_align=ft.TextAlign.LEFT, no_wrap=True)



        # Image principale
        self.image_display = ft.Image(
            src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=", #1x1 pixel transparent GIF, plus léger que les placeholders de PIL
            fit=ft.BoxFit.COVER,
            gapless_playback=True,
        )
        
        # Container de l'image — positionné dans le Stack, transformé via LayoutControl
        self.image_container = ft.Container(
            content=self.image_display,
            left=(self.canvas_w - self.display_w) / 2,
            top=(self.canvas_h - self.display_h) / 2,
        )



        # Lignes de grille des tiers (fixées au canevas, pas à l'image)
        grid_line_color = ft.Colors.with_opacity(0.5, "#707070")
        self._grid_lines = [
            ft.Container(bgcolor=grid_line_color, left=self.canvas_w / 3,     top=0,                    width=1,             height=self.canvas_h, visible=True),
            ft.Container(bgcolor=grid_line_color, left=2 * self.canvas_w / 3, top=0,                    width=1,             height=self.canvas_h, visible=True),
            ft.Container(bgcolor=grid_line_color, left=0,                     top=self.canvas_h / 3,    width=self.canvas_w, height=1,             visible=True),
            ft.Container(bgcolor=grid_line_color, left=0,                     top=2 * self.canvas_h / 3,width=self.canvas_w, height=1,             visible=True),
        ]



        # Stack : image + grille en overlay fixe
        self.image_stack = ft.Stack(
            controls=[self.image_container, *self._grid_lines],
            width=self.canvas_w,
            height=self.canvas_h,
        )



        # GestureDetector couvrant tout le canevas pour le pan, zoom, rotation
        self.gesture_detector = ft.GestureDetector(
            content=self.image_stack,
            mouse_cursor=ft.MouseCursor.MOVE,
            # on_scale_start=self.on_gesture_start,   # trackpad désactivé (génère des saccades)
            # on_scale_update=self.on_gesture_update,  # trackpad désactivé
            # on_scale_end=self.on_gesture_end,        # trackpad désactivé
            on_pan_down=self.on_pan_down,                # clic pipette (mode Instantané) — position immédiate
            on_pan_update=self.on_pan_update,           # déplacement souris / glissé pipette
            on_pan_end=self.on_pan_end,                 # relâchement pipette
            on_secondary_tap=self.on_canvas_secondary_tap,  # clic droit (simple clic, pas glissé) : bascule ajoute/retire
            on_scroll=self.on_gesture_scroll,           # molette souris conservée
        )



        # Boutons d'action (créés ici pour que le main puisse les référencer)
        self.validate_button = ft.Button(
            "Valider & Suivant",
            icon=ft.Icons.CHECK,
            bgcolor=GREEN,
            color=DARK,
            on_click=self.validate_and_next,
        )



        # Bouton pour ignorer l'image courante
        self.ignore_button = ft.Button(
            "Ignorer Image",
            icon=ft.Icons.BLOCK,
            bgcolor=RED,
            color=DARK,
            on_click=self.ignore_image,
        )

        # Bouton pour revenir à l'image précédente
        self.previous_button = ft.Button(
            "Précédent",
            icon=ft.Icons.ARROW_BACK,
            bgcolor=ORANGE,
            color=DARK,
            on_click=self.go_previous,
            disabled=True,
        )
        self._last_saved_paths = []  # fichiers du dernier validate, pour annulation

        # ── Export en arrière-plan (validate_and_next) ────────────────
        # File FIFO + thread unique : l'UI passe à l'image suivante
        # immédiatement, le calcul/enregistrement pleine résolution se
        # fait derrière (retour user : latence à chaque Entrée avec un
        # client en attente). _export_jobs garde l'historique pour
        # go_previous (suppression des fichiers du dernier export).
        self._export_thread = None
        self._export_queue = None
        self._export_jobs = []
        # Parité d'appairage ID X4 10x20 côté UI (miroir synchrone de
        # _id4_10x20_pending, qui vit désormais dans le worker).
        self._id4_pair_waiting = False

        # ── Préchargement de l'image suivante ─────────────────────────
        # path -> {"img", "icc", "exif"} décodés en avance par un thread
        # pendant que l'opérateur recadre l'image courante.
        self._preload_cache = {}

        # ── Aperçu live pendant le drag des sliders ───────────────────
        self._live_req = 0
        self._live_running = False
        self._live_lock = threading.Lock()



        self.border_switch_polaroid = ft.Switch(label="Polaroid", active_color=ORANGE, value=CONSTANTS.RECADRAGE_BORDER_POLAROID, visible="10x10" in self.current_format_label, on_change=self.on_border_toggle_polaroid)
        self.border_switch_ID2 = ft.Switch(label="ID X2", active_color=ORANGE, value=CONSTANTS.RECADRAGE_BORDER_ID2, visible="ID" in self.current_format_label, on_change=self.on_border_toggle_id2)
        self.border_switch_ID4 = ft.Switch(label="ID X4", active_color=ORANGE, value=CONSTANTS.RECADRAGE_BORDER_ID4, visible="ID" in self.current_format_label, on_change=self.on_border_toggle_id4)
        self.id4_10x20_switch = ft.Switch(label="10x20", active_color=ORANGE, value=CONSTANTS.RECADRAGE_ID4_10x20, visible="ID" in self.current_format_label and self.border_id4, on_change=self.on_id4_10x20_toggle)
        self.network_switch = ft.Switch(label="Sauver sur réseau", active_color=GREEN, value=CONSTANTS.RECADRAGE_SAVE_TO_NETWORK, visible="ID" in self.current_format_label, on_change=self.on_network_toggle)
        self.sharpen_switch = ft.Switch(label="Netteté", active_color=BLUE, value=CONSTANTS.RECADRAGE_IS_SHARPEN, visible=True, on_change=self.on_sharpen_toggle)
        self.is_sharpen = CONSTANTS.RECADRAGE_IS_SHARPEN
        self.bw_switch = ft.Switch(label="Noir et blanc", active_color=YELLOW, value=CONSTANTS.RECADRAGE_IS_BW, on_change=self.on_bw_toggle)
        self.is_fit_in = CONSTANTS.RECADRAGE_FIT_IN
        self.fit_in_switch = ft.Switch(label="Fit-in", active_color=VIOLET, value=CONSTANTS.RECADRAGE_FIT_IN, on_change=self.on_fit_in_toggle)
        self.white_border = CONSTANTS.RECADRAGE_WHITE_BORDER
        self.white_border_switch = ft.Switch(label="Bord blanc 5mm", active_color=WHITE, value=CONSTANTS.RECADRAGE_WHITE_BORDER, on_change=self.on_white_border_toggle)
        self.show_grid = CONSTANTS.RECADRAGE_SHOW_GRID
        self.grid_switch = ft.Switch(label="Grille", active_color=BLUE, value=CONSTANTS.RECADRAGE_SHOW_GRID, on_change=self.on_grid_toggle)
        # "resolution" = recadrage mm×DPI (défaut), "ratio" = crop natif, "none" = retouche seule
        self.crop_mode = "resolution"



        # Suppression fond IA
        self._rembg_session = [None]        # birefnet-portrait / birefnet-general
        self._rembg_session_u2net = [None]  # u2net_human_seg / u2net
        self._rembg_original = None   # sauvegarde avant suppression du fond
        self._rembg_composite_cache = None  # (cache_key, PIL.Image RGB) — composite bg+mask à taille affichage
        # 0 = fond blanc, 1 = fond gris clair, 2 = fond flou
        self.rembg_bg_mode = 0 if CONSTANTS.RECADRAGE_REMBG_BG_WHITE else 2
        self.rembg_human_seg = CONSTANTS.RECADRAGE_REMBG_HUMAN_SEG
        self.rembg_mode = CONSTANTS.RECADRAGE_REMBG_MODE  # 0=rapide(u2net) 1=précis(birefnet) 2=instantané(flood)
        self._rembg_bg_label = ft.Text("Fond blanc", size=12, color=DARK)
        self.rembg_bg_btn = ft.Button(
            content=self._rembg_bg_label,
            bgcolor=ft.Colors.GREY_200,
            on_click=self.on_rembg_bg_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            width=90,
            tooltip="Fond blanc / Fond flou",
        )
        self._rembg_model_label = ft.Text("Humain", size=12, color=DARK)
        self.rembg_model_btn = ft.Button(
            content=self._rembg_model_label,
            bgcolor=VIOLET,
            on_click=self.on_rembg_model_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            tooltip="Portrait / Généraliste" if REMBG_AVAILABLE else "",
        )
        # Bouton à 3 états : Rapide (u2net) -> Précis (birefnet) ->
        # Instantané (pipette flood fill, sans IA — pas besoin de rembg installé).
        _REMBG_MODE_LABELS = {0: ("Rapide", BLUE), 1: ("Précis", VIOLET), 2: ("Instantané", GREEN)}
        _mode_label, _mode_color = _REMBG_MODE_LABELS[self.rembg_mode]
        self._rembg_precise_label = ft.Text(_mode_label, size=12, color=DARK)
        self.rembg_precise_btn = ft.Button(
            content=self._rembg_precise_label,
            bgcolor=_mode_color if (REMBG_AVAILABLE or self.rembg_mode == 2) else GREY,
            on_click=self.on_rembg_precise_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            tooltip="Rapide (u2net) / Précis (birefnet) / Instantané (fond uni, sans IA)",
        )



        # Érosion du masque — slider 0–2 % par tranche de 0,1 % (0 = désactivé)
        self.rembg_erosion_pct = 0.0
        self.rembg_erosion_slider = ft.Slider(
            value=0,
            min=0,
            max=2,
            divisions=20,
            label="{value} %",
            active_color=ORANGE,
            on_change=self.on_rembg_erosion_change,
            on_change_end=self.on_rembg_erosion_end,
            width=90,
        )

        # Adoucissement (flou) du bord du masque — lisse un contour en
        # escalier (ex. flood fill à résolution réduite) sans rétrécir la
        # zone détourée, contrairement à l'érosion ci-dessus.
        self.rembg_feather_pct = 0.0
        self.rembg_feather_slider = ft.Slider(
            value=0,
            min=0,
            max=0.5,  # plage réduite (retour user : 0-2 % était trop sensible pour un flou)
            divisions=20,
            label="{value} %",
            active_color=BLUE,
            on_change=self.on_rembg_feather_change,
            on_change_end=self.on_rembg_feather_end,
            width=90,
        )

        # Mode Instantané (pipette) : clic-glissé sur le fond dans le
        # canevas — le point de clic sert de graine au flood fill, la
        # distance du glissé ajuste la tolérance (sensibilité aux
        # variations de couleur) en direct, pas de slider dédié.
        # Ajoute ou retire de la sélection selon `pipette_sign_btn` (pas
        # le bouton de la souris — le clic droit ne se déclenche pas du
        # tout ici, cf. `on_pan_down`).
        # État interactif (partagé avec Augmentation IA.py, cf. image_ops.FloodPipette)
        self._pipette = image_ops.FloodPipette(CONSTANTS.RECADRAGE_FLOOD_TOLERANCE)
        self._pipette_start = None   # coordonnées écran (repère gesture_detector), propres à cette app
        self._rembg_tolerance_label = ft.Text(
            f"Tol. {self._pipette.tolerance}", size=11, color=LIGHT_GREY)
        self.pipette_sign_btn = ft.IconButton(
            icon=ft.Icons.ADD_CIRCLE_OUTLINE,
            icon_color=GREEN,
            tooltip="Pipette : ajoute à la sélection (cliquer pour passer en retrait)",
            on_click=self.on_pipette_sign_toggle,
            visible=self.rembg_mode == 2,  # cf. _sync_pipette_sign_btn pour l'icône/couleur
            icon_size=18,
            style=ft.ButtonStyle(padding=ft.Padding.all(2)),
        )
        self.rembg_btn = ft.IconButton(
            icon=ft.Icons.AUTO_FIX_HIGH,
            selected_icon=ft.Icons.AUTO_FIX_HIGH,
            selected=False,
            icon_color=LIGHT_GREY,
            selected_icon_color=VIOLET,
            tooltip="Supprimer le fond par IA (rembg)" if REMBG_AVAILABLE else "pip install rembg onnxruntime",
            on_click=self.on_rembg,
            style=ft.ButtonStyle(padding=ft.Padding.all(4)),
        )



        # Barre de statut inline (remplace les toasters/snackbars)
        self._status_text = ft.Text("", size=12, color=LIGHT_GREY, italic=True,
                                    text_align=ft.TextAlign.CENTER, expand=True)
        self._status_ring = ft.ProgressRing(width=14, height=14, stroke_width=2,
                                            color=BLUE, visible=False)
        self._status_row = ft.Row(
            [self._status_ring, self._status_text],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        self._status_clear_task = None



        # Sliders de réglages (panneau gauche)
        # Contraste
        self.contrast = float(CONSTANTS.RECADRAGE_DEFAULT_CONTRAST)
        self.contrast_slider = ft.Slider(
            value=CONSTANTS.RECADRAGE_DEFAULT_CONTRAST, min=-20, max=20, divisions=40, label=str(CONSTANTS.RECADRAGE_DEFAULT_CONTRAST),
            active_color=YELLOW,
            on_change=self.on_contrast_label,
            on_change_end=self.on_contrast_end,
        )

        # Saturation
        self.saturation = float(CONSTANTS.RECADRAGE_DEFAULT_SATURATION)
        self.saturation_slider = ft.Slider(
            value=CONSTANTS.RECADRAGE_DEFAULT_SATURATION, min=-100, max=100, divisions=20, label=str(CONSTANTS.RECADRAGE_DEFAULT_SATURATION),
            active_color=VIOLET,
            on_change=self.on_saturation_label,
            on_change_end=self.on_saturation_end,
        )

        # Exposition (Exposure — similaire à Camera Raw, +20 = doublement de la luminosité)
        self.exposure = float(CONSTANTS.RECADRAGE_DEFAULT_EXPOSURE)
        self.exposure_slider = ft.Slider(
            value=CONSTANTS.RECADRAGE_DEFAULT_EXPOSURE, min=-100, max=100, divisions=20, label=str(CONSTANTS.RECADRAGE_DEFAULT_EXPOSURE),
            active_color=YELLOW,
            on_change=self.on_exposure_label,
            on_change_end=self.on_exposure_end,
        )

        # Teinte (Hue)
        self.hue = float(CONSTANTS.RECADRAGE_DEFAULT_HUE)
        self.hue_slider = ft.Slider(
            value=CONSTANTS.RECADRAGE_DEFAULT_HUE, min=-180, max=180, divisions=36, label=str(CONSTANTS.RECADRAGE_DEFAULT_HUE),
            active_color=VIOLET,
            on_change=self.on_hue_label,
            on_change_end=self.on_hue_end,
        )

        # Balance des blancs (temperature : - = froid/bleu, + = chaud/jaune)
        self.white_balance = float(CONSTANTS.RECADRAGE_DEFAULT_WHITE_BALANCE)
        self.white_balance_slider = ft.Slider(
            value=CONSTANTS.RECADRAGE_DEFAULT_WHITE_BALANCE, min=-100, max=100, divisions=20, label=str(CONSTANTS.RECADRAGE_DEFAULT_WHITE_BALANCE),
            active_color=VIOLET,
            on_change=self.on_wb_label,
            on_change_end=self.on_wb_end,
        )



        # Histogramme miniature
        self.show_histogram = CONSTANTS.RECADRAGE_SHOW_HISTOGRAM
        self.histogram_image = ft.Image(
            src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
            width=RIGHT_COL_WIDTH,
            height=HISTOGRAM_HEIGHT,
            fit=ft.BoxFit.FILL,
            gapless_playback=True,
            visible=self.show_histogram,
        )



        # Container principal du canevas de recadrage (Stack + GestureDetector)
        self.canvas_container = ft.Container(
            content=self.gesture_detector,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            width=self.canvas_w,
            height=self.canvas_h,
            bgcolor=WHITE,
            border=ft.Border.all(1, WHITE),
        )



# ===================== Statut inline ===================== #
    def _set_status(self, message, processing=False):
        """Affiche un message dans la barre de statut inline (remplace les toasters).

        - processing=True  : spinner visible + message persistent jusqu'à nouvel appel.
        - processing=False : message seul, disparaît après 3 secondes.
        """
        if "[ERREUR]" in message or "[ERROR]" in message:
            color = RED
        elif "[OK]" in message:
            color = GREEN
        else:
            color = LIGHT_GREY

        self._status_text.value = message
        self._status_text.color = color
        self._status_ring.visible = processing
        try:
            self._status_text.update()
            self._status_ring.update()
        except Exception:
            pass
        if not processing:
            self.page.run_task(self._auto_clear_status)

    async def _auto_clear_status(self):
        """Efface automatiquement la barre de statut après 3 secondes."""
        import asyncio
        await asyncio.sleep(3)
        self._status_text.value = ""
        self._status_ring.visible = False
        try:
            self._status_text.update()
            self._status_ring.update()
        except Exception:
            pass



    # ================================================================ #
    #                    CANVAS & TRANSFORMATIONS                      #
    # ================================================================ #
    def update_canvas_size(self):
        """
        Recalcule et applique les dimensions optimales du canevas.

        Le canevas doit à la fois :
          - S'inscrire dans l'espace disponible (fenêtre − panneaux latéraux).
          - Respecter le ratio du format d'impression sélectionné et
            l'orientation courante (portrait / paysage).
          - Ne pas dépasser MAX_CANVAS_SIZE dans l'une ou l'autre dimension.

        Après le calcul, les attributs `canvas_w`, `canvas_h` sont mis à
        jour ainsi que les propriétés `width` / `height` des widgets
        `canvas_container` et `image_stack`.
        """

        if self.page.window.width:
            right_panel_width = RIGHT_COL_WIDTH + 24  # colonne droite + séparateur/marges
            usable_width = self.page.window.width - right_panel_width - CANVAS_CHROME_WIDTH - LEFT_COL_WIDTH - 40
            available_width = min(max(usable_width, 320), MAX_CANVAS_SIZE)
        else:
            available_width = 800
        available_height = min(self.page.window.height - 380, MAX_CANVAS_SIZE) if self.page.window.height else 600



        # Calculer le ratio cible
        if (
            getattr(self, 'crop_mode', 'resolution') == 'none'
            and getattr(self, 'original_width', 0) > 0
            and getattr(self, 'original_height', 0) > 0
        ):
            target_aspect_ratio = self.original_width / self.original_height
        else:
            format_width, format_height = self.current_format
            if self.canvas_is_portrait:
                target_aspect_ratio = format_width / format_height
            else:
                target_aspect_ratio = format_height / format_width

        self.canvas_w = available_width
        self.canvas_h = self.canvas_w / target_aspect_ratio
        if self.canvas_h > available_height:
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h * target_aspect_ratio

        self.canvas_container.width = self.canvas_w
        self.canvas_container.height = self.canvas_h
        self.image_stack.width = self.canvas_w
        self.image_stack.height = self.canvas_h

        # Redimensionner les sliders verticaux
        self.rotation_slider.resize(int(self.canvas_h))
        self.zoom_slider.resize(int(self.canvas_h))



        # Repositionner les lignes de grille
        if hasattr(self, '_grid_lines'):
            self._grid_lines[0].left   = self.canvas_w / 3
            self._grid_lines[1].left   = 2 * self.canvas_w / 3
            self._grid_lines[0].height = self.canvas_h
            self._grid_lines[1].height = self.canvas_h
            self._grid_lines[2].top    = self.canvas_h / 3
            self._grid_lines[2].width  = self.canvas_w
            self._grid_lines[3].top    = 2 * self.canvas_h / 3
            self._grid_lines[3].width  = self.canvas_w
        self.page.update()



    def _update_transform(self):
        """
        Applique pan, zoom et rotation via les propriétés LayoutControl.

        - `image_display.width/height` : zoom (redimensionnement layout, pas de re-rendu PIL).
        - `image_container.left/top`   : pan (décalage du coin sup. gauche dans le Stack).
        - `image_container.rotate`     : rotation autour du centre du container.
        """
        scaled_w = self.display_w * self.scale
        scaled_h = self.display_h * self.scale
        # Évite un relayout Flutter coûteux si le scale n'a pas changé (pan pur)
        if self.image_display.width != scaled_w or self.image_display.height != scaled_h:
            self.image_display.width  = scaled_w
            self.image_display.height = scaled_h
        self.image_container.left  = (self.canvas_w - scaled_w) / 2 + self.offset_x
        self.image_container.top   = (self.canvas_h - scaled_h) / 2 + self.offset_y
        self.image_container.rotate = math.radians(self.rotation)
        self.image_container.update()



    def _crop_view(self):
        """Construit un `image_ops.CropView` depuis l'état courant."""
        return image_ops.CropView(
            canvas_w=self.canvas_w, canvas_h=self.canvas_h,
            base_scale=self.base_scale, offset_x=self.offset_x,
            offset_y=self.offset_y, scale=self.scale, rotation=self.rotation,
            original_width=self.original_width,
            original_height=self.original_height,
            display_w=self.display_w, display_h=self.display_h,
        )



    def _get_transformed_bounds(self):
        """Boîte englobante de l'image après scale + rotation courante.
        Délègue à `image_ops.get_transformed_bounds`."""

        return image_ops.get_transformed_bounds(self._crop_view())



    def _clamp_offsets(self):
        """
        Contraint scale/offset_x/offset_y pour qu'aucune bordure de l'image
        n'apparaisse à l'intérieur du canevas. Délègue à
        `image_ops.clamp_offsets`, qui retourne une nouvelle vue géométrique
        appliquée ici sur `self`.
        """

        clamped = image_ops.clamp_offsets(
            self._crop_view(), is_fit_in=getattr(self, "is_fit_in", False))
        self.scale = clamped.scale
        self.offset_x = clamped.offset_x
        self.offset_y = clamped.offset_y



    # ================================================================ #
    #                     CHARGEMENT DES IMAGES                        #
    # ================================================================ #
    def _decode_for_load(self, path):
        """Décodage complet d'une image pour l'édition : profil ICC, EXIF
        (orientation appliquée, tag retiré), conversion RGBA. Pur calcul
        PIL — appelable depuis le thread de préchargement comme depuis
        load_image. Lève en cas de fichier illisible."""
        source_image = Image.open(path)
        icc_profile = source_image.info.get('icc_profile', None)
        # Appliquer la rotation EXIF AVANT toute manipulation de l'objet
        # EXIF (getexif() retourne un objet mis en cache : pop(274) avant
        # exif_transpose supprimerait le tag Orientation avant que
        # exif_transpose puisse le lire)
        source_image = ImageOps.exif_transpose(source_image)
        try:
            raw_exif = source_image.getexif()
            # Tag Orientation (274) retiré : l'image est déjà corrigée
            raw_exif.pop(274, None)
            exif_bytes = raw_exif.tobytes()
        except Exception:
            exif_bytes = None
        return {"img": source_image.convert("RGBA"),
                "icc": icc_profile, "exif": exif_bytes}

    def _preload_next_async(self):
        """Décode image_paths[current_index + 1] dans un thread pendant
        que l'opérateur travaille sur l'image courante : le passage à la
        photo suivante (Entrée/Espace) devient quasi instantané (retour
        user : enchaînement des photos avec un client en attente)."""
        next_index = self.current_index + 1
        if next_index >= len(self.image_paths):
            return
        path = self.image_paths[next_index]
        if path in self._preload_cache:
            return

        def _work():
            try:
                data = self._decode_for_load(path)
            except Exception:
                return   # load_image affichera l'erreur réelle le moment venu
            self._preload_cache[path] = data
            # Au plus 2 entrées (l'actuelle en cours de consommation + la
            # suivante) — jamais tout le dossier en mémoire.
            for stale_key in list(self._preload_cache)[:-2]:
                self._preload_cache.pop(stale_key, None)

        threading.Thread(target=_work, daemon=True).start()

    def _refit_canvas(self):
        """Recale la géométrie (canvas, base_scale, dimensions affichées)
        après un changement de taille de fenêtre — sans redécoder ni
        re-rendre l'image (cf. delayed_start : l'ancien recalage passait
        par un load_image complet, double chargement à chaque démarrage).
        """
        if getattr(self, 'current_pil_image', None) is None:
            return
        self.update_canvas_size()
        scale_factor_width = self.canvas_w / self.original_width
        scale_factor_height = self.canvas_h / self.original_height
        if self.is_fit_in:
            self.base_scale = min(scale_factor_width, scale_factor_height)
        else:
            self.base_scale = max(scale_factor_width, scale_factor_height)
        self.display_w = int(round(self.original_width * self.base_scale))
        self.display_h = int(round(self.original_height * self.base_scale))
        if not self.is_fit_in:
            self.display_w = max(self.display_w, math.ceil(self.canvas_w) + 4)
            self.display_h = max(self.display_h, math.ceil(self.canvas_h) + 4)
        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        self._clamp_offsets()
        self._update_transform()
        self.page.update()

    def load_image(self, preserve_orientation=True):
        """
        Charge l'image courante (image_paths[current_index]) et prépare
        l'affichage.

        Étapes réalisées
        ------------------
        1. Réinitialisation des transformations (scale, offset).
        2. Vérification de l'accessibilité du fichier (existence + droits).
        3. Ouverture PIL : extraction du profil ICC, correction de
           l'orientation EXIF (`ImageOps.exif_transpose`), conversion RGBA.
        4. Détection automatique de l'orientation portrait / paysage
           (sauf si `preserve_orientation=True`).
        5. Calcul du `base_scale` pour que l'image « couvre » le canevas
           (mode crop) ou « tienne » dedans (mode fit-in).
        6. Génération de la prévisualisation via `_render_preview`.
        7. Mise à jour de la visibilité des switches (border, ID, etc.)
           selon le format actif.
        8. Mise à jour du titre de la fenêtre.

        En cas d'erreur (fichier invalide, exception PIL), le message est
        affiché dans un snackbar et l'application passe automatiquement
        à l'image suivante.

        Parameters
        ----------
        preserve_orientation : bool, optional
            Si True, l'orientation portrait/paysage du canevas n'est pas
            recalculée depuis les dimensions de l'image (utile lors d'un
            changement de format ou d'une bascule manuelle). Défaut : False.
        """

        if not self.image_paths:
            return
        if self.current_index >= len(self.image_paths):
            return
        


        # Réinitialiser les valeurs de transformation (zoom + rotation + offsets)
        self.scale = 1.0
        self.rotation = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        if hasattr(self, 'zoom_slider'):
            self.zoom_slider.value = 1.0
            self.zoom_slider.label = "1.00×"
            self.zoom_slider.update()
        if hasattr(self, 'rotation_slider'):
            self.rotation_slider.value = 0.0
            self.rotation_slider.label = "0.00°"
            self.rotation_slider.update()

        path = self.image_paths[self.current_index]



        # Pré-remplir copies_count et format depuis le préfixe NX_{format}_ du nom de fichier
        filename_prefix_match = re.match(r'^(\d+)X_([^_]+)_', os.path.basename(path))
        copies_only_match     = re.match(r'^(\d+)X_', os.path.basename(path))
        if filename_prefix_match:
            self.copies_count = int(filename_prefix_match.group(1))
            format_from_filename = filename_prefix_match.group(2)
            if not preserve_orientation and format_from_filename in FORMATS:
                self.current_format       = FORMATS[format_from_filename]
                self.current_format_label = format_from_filename
                if hasattr(self, 'format_radio_group'):
                    self.format_radio_group.value = format_from_filename
        elif copies_only_match:
            self.copies_count = int(copies_only_match.group(1))
        else:
            self.copies_count = 1
        if hasattr(self, 'copies_text'):
            self.copies_text.value = str(self.copies_count)



        # Vérifier que le fichier existe et est accessible
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            self._set_status(f"Fichier inaccessible: {os.path.basename(path)}")
            self.page.update()

            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return
        
        try:
            # Décodage : consomme le préchargement si disponible (préparé
            # par _preload_next_async pendant l'image précédente), sinon
            # décode inline comme avant.
            decoded = self._preload_cache.pop(path, None)
            if decoded is None:
                decoded = self._decode_for_load(path)
            self.icc_profile = decoded["icc"]
            self.source_exif = decoded["exif"]
            source_image = decoded["img"]
            self.current_pil_image = source_image
            self._rembg_original = None
            self.rembg_btn.selected = False
            self._pipette_cancel()
            self._pipette.reset()
            self._sync_pipette_sign_btn()
            self.original_width, self.original_height = source_image.size
        except Exception as e:
            self._set_status(f"Erreur lors du chargement: {os.path.basename(path)} - {str(e)}")
            self.page.update()

            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.original_height >= self.original_width else False

        self.update_canvas_size()



        # Calculer la taille de base : COVER en mode normal, CONTAIN en mode Fit-in
        scale_factor_width = self.canvas_w / self.original_width
        scale_factor_height = self.canvas_h / self.original_height
        if self.is_fit_in:
            self.base_scale = min(scale_factor_width, scale_factor_height)
        else:
            self.base_scale = max(scale_factor_width, scale_factor_height)
        
        self.display_w = int(round(self.original_width * self.base_scale))
        self.display_h = int(round(self.original_height * self.base_scale))
        if not self.is_fit_in:
            # +4 px garantit un débordement minimum même quand le ratio de l'image
            # correspond exactement à celui du format d'impression (ex. photo 2:3 en 10×15).
            # Sans ce surplus, overflow = 0 → _clamp_offsets bloque le pan à scale = 1.0.
            self.display_w = max(self.display_w, math.ceil(self.canvas_w) + 4)
            self.display_h = max(self.display_h, math.ceil(self.canvas_h) + 4)

        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        self._render_preview()

        # Appliquer la rotation et réinitialiser le transform
        self._clamp_offsets()
        self._update_transform()

        if "10x10" in self.current_format_label:
            self.border_switch_polaroid.visible = True
            self.border_switch_polaroid.value = self.border_polaroid
        else:
            self.border_switch_polaroid.visible = False

        if "ID" in self.current_format_label:
            self.border_switch_ID2.visible = True
            self.border_switch_ID2.value = self.border_id2
            self.border_switch_ID4.visible = True
            self.border_switch_ID4.value = self.border_id4
            self.id4_10x20_switch.visible = self.border_id4
            self.network_switch.visible = True
            self.network_switch.value = self.save_to_network
            self.sharpen_switch.value = True
        else:
            self.border_switch_ID2.visible = False
            self.border_switch_ID4.visible = False
            self.id4_10x20_switch.visible = False
            self.network_switch.visible = False
            self.sharpen_switch.value = self.sharpen_switch.value

        self.page.title = f"Crop: {os.path.basename(path)} ({self.current_index + 1}/{len(self.image_paths)})"
        if hasattr(self, 'previous_button'):
            self.previous_button.disabled = self.current_index <= 0
        self.page.update()

        # Warmup GPU : micro-décalage 100 ms après le chargement pour forcer la
        # rasterisation de la texture Flutter avant le premier geste utilisateur.
        async def _warmup_transform():
            await asyncio.sleep(0.1)
            self.offset_x = 0.5
            self._update_transform()
            await asyncio.sleep(0.05)
            self.offset_x = 0.0
            self._update_transform()
        self.page.run_task(_warmup_transform)

        # L'image suivante se décode en arrière-plan pendant le recadrage
        # de celle-ci (cf. _preload_next_async).
        self._preload_next_async()

    # ================================================================ #
    #                    TRAITEMENT PAR LOT                           #
    # ================================================================ #
    def batch_process_interactive(self, e):
        """
        Initialise le batch interactif en listant les images du dossier source.

        Vérifications successives
        --------------------------
        1. Attente de 0,3 s pour s'assurer que les fichiers sont bien écrits
           sur le disque avant d'être lus.
        2. Lecture de FOLDER_PATH (dossier source) et optionnellement de
           SELECTED_FILES (liste de fichiers à prioriser).
        3. Filtrage des fichiers par extension image valide ; exclusion de
           `watermark.png`.
        4. Vérification d'intégrité de chaque image via `Image.verify()`.
        5. Si des images valides sont trouvées, `image_paths` et
           `current_index` sont initialisés et la première image est
           chargée.

        Ce flux est déclenché automatiquement 0,3 s après l'ouverture de
        la fenêtre (via `delayed_start` dans `main`) et peut aussi être
        appelé manuellement depuis un bouton.

        Parameters
        ----------
        e : ft.ControlEvent or None
            Événement Flet (non utilisé directement). Peut être None lors
            de l'appel programmatique depuis `delayed_start`.
        """

        # Pas de time.sleep ici : l'attente de stabilisation des fichiers
        # est déjà couverte par le délai de delayed_start, et un sleep
        # synchrone bloquait la boucle d'événements Flet au démarrage.
        source_folder_path = self.source_folder

        selected_files_env_value = os.environ.get("SELECTED_FILES", "")
        selected_files_filter = set(selected_files_env_value.split("|")) if selected_files_env_value else None

        try:
            all_folder_files = os.listdir(source_folder_path)
        except Exception as e:
            self._set_status(f"Erreur lors de la lecture du dossier: {e}")
            return

        image_filenames = [f for f in all_folder_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.jpe', '.tif', '.tiff', '.bmp', '.dib', '.gif', '.webp', '.ico', '.pcx', '.tga', '.ppm', '.pgm', '.pbm', '.pnm')) and not f == "watermark.png"]
        total_image_count = len(image_filenames)

        if selected_files_filter:
            image_filenames = [f for f in image_filenames if f in selected_files_filter]
            if not image_filenames and total_image_count > 0:
                self._set_status(f"{total_image_count} image(s) trouvée(s) mais aucune ne correspond aux fichiers sélectionnés")
                self.page.update()
                return

        if not image_filenames:
            if len(all_folder_files) == 0:
                self._set_status("Le dossier est vide")
            else:
                self._set_status(f"Aucun fichier image valide trouvé dans le dossier (total : {len(all_folder_files)})")
            self.page.update()
            return

        valid_image_paths = [
            os.path.join(source_folder_path, f)
            for f in image_filenames
            if os.path.isfile(os.path.join(source_folder_path, f))
            and os.access(os.path.join(source_folder_path, f), os.R_OK)
        ]

        if not valid_image_paths:
            self._set_status(f"{len(image_filenames)} image(s) trouvée(s) mais aucune n'est accessible ou valide")
            self.page.update()
            return

        self.image_paths = valid_image_paths
        self.current_index = 0
        self.batch_mode = True
        self._id4_10x20_pending = None
        self._id4_pair_waiting = False
        self._id4_10x20_seq = 0
        self.load_image(preserve_orientation=False)



    # ================================================================ #
    #                      CALCUL DU RECADRAGE                         #
    # ================================================================ #
    def _compute_crop(self, target_w_px, target_h_px):
        """
        Calcule le recadrage de l'image courante pour le canevas principal.

        Raccourci vers `_compute_crop_with_canvas` en utilisant les
        paramètres du canevas principal (canvas_w, canvas_h, base_scale,
        offset_x, offset_y, scale).

        Parameters
        ----------
        target_w_px : int
            Largeur de l'image de sortie en pixels (résolution DPI).
        target_h_px : int
            Hauteur de l'image de sortie en pixels (résolution DPI).

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions demandées.
        """

        return self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            self.canvas_w, self.canvas_h,
            self.base_scale, self.offset_x, self.offset_y,
        )



    def _compute_crop_for_format(self, fmt_w_mm, fmt_h_mm, is_portrait):
        """
        Calcule le recadrage pour un format donné avec son propre ratio.

        Construit un canevas **virtuel** qui respecte le ratio du format
        cible tout en étant centré sur le même point de l'image que le
        canevas principal. Les offsets sont recalculés proportionnellement.

        Utilisé par la fonctionnalité « Formats multiples » pour exporter
        simultanément plusieurs formats différents depuis un seul point de
        vue « métier » (le centre de l'image vu à l'écran).

        Parameters
        ----------
        fmt_w_mm : float
            Largeur du format cible en mm.
        fmt_h_mm : float
            Hauteur du format cible en mm.
        is_portrait : bool
            True si l'export doit être en orientation portrait.

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions du format cible (DPI).
        """

        if is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        target_aspect_ratio = target_w_px / target_h_px
        available_width  = self.canvas_w
        available_height = self.canvas_h
        if available_width / available_height > target_aspect_ratio:
            virtual_canvas_height = available_height
            virtual_canvas_width  = available_height * target_aspect_ratio
        else:
            virtual_canvas_width  = available_width
            virtual_canvas_height = available_width / target_aspect_ratio

        virtual_base_scale = max(virtual_canvas_width / self.original_width, virtual_canvas_height / self.original_height)

        if self.base_scale > 0:
            image_space_offset_x = self.offset_x / (self.base_scale * self.scale)
            image_space_offset_y = self.offset_y / (self.base_scale * self.scale)
        else:
            image_space_offset_x = image_space_offset_y = 0.0
        virtual_offset_x = image_space_offset_x * virtual_base_scale * self.scale
        virtual_offset_y = image_space_offset_y * virtual_base_scale * self.scale

        return self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            virtual_canvas_width, virtual_canvas_height,
            virtual_base_scale, virtual_offset_x, virtual_offset_y,
        )



    def _compute_crop_from_snapshot(self, snapshot):
        """
        Calcule le recadrage à partir d'un snapshot complet de l'état de la vue.

        Un snapshot est un dictionnaire sauvegardé par `add_extra_format`.
        Il contient toutes les informations nécessaires pour reproduire le
        cadrage exact tel qu'il était au moment de l'ajout :
        dimensions du canevas virtuel, base_scale, scale, offsets, rotation,
        format (dims), orientation, réglages actifs (is_bw, shadows, etc.).

        La méthode écrase temporairement `self.rotation` et `self.is_bw`
        avec les valeurs du snapshot puis les restaure après le calcul.

        Parameters
        ----------
        snapshot : dict
            Dictionnaire produit par `add_extra_format`. Clés utilisées :
            ``dims``, ``is_portrait``, ``rotation``, ``is_bw``,
            ``canvas_w``, ``canvas_h``, ``base_scale``, ``scale``,
            ``offset_x``, ``offset_y``.

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions du format du snapshot.
        """

        format_dimensions = snapshot["dims"]
        is_portrait = snapshot["is_portrait"]
        fmt_w_mm, fmt_h_mm = format_dimensions
        if snapshot.get("crop_mode", "resolution") == "ratio":
            _fw = fmt_w_mm if is_portrait else fmt_h_mm
            _fh = fmt_h_mm if is_portrait else fmt_w_mm
            _k = min(self.original_width / _fw, self.original_height / _fh)
            target_w_px = max(1, math.floor(_fw * _k))
            target_h_px = max(1, math.floor(_fh * _k))
        elif is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        saved_rotation_angle = self.rotation
        saved_black_and_white = self.is_bw
        self.rotation = snapshot["rotation"]
        self.is_bw = snapshot.get("is_bw", False)



        # Si rembg n'était pas actif lors du snapshot mais l'est maintenant,
        # utiliser l'image originale (avant suppression du fond) pour ce format.
        saved_image_before_snapshot = None
        if not snapshot.get("rembg_active", False) and self.current_pil_image.mode == "RGBA" and self._rembg_original is not None:
            saved_image_before_snapshot = self.current_pil_image
            self.current_pil_image = self._rembg_original

        cropped_image = self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            snapshot["canvas_w"], snapshot["canvas_h"],
            snapshot["base_scale"], snapshot["offset_x"], snapshot["offset_y"],
            scale_override=snapshot["scale"],
        )

        if saved_image_before_snapshot is not None:
            self.current_pil_image = saved_image_before_snapshot

        self.rotation = saved_rotation_angle
        self.is_bw = saved_black_and_white
        return cropped_image



    def _compute_crop_with_canvas(self, target_w_px, target_h_px,
                                   canvas_w, canvas_h, base_scale, offset_x, offset_y,
                                   scale_override=None):
        """
        Noyau du recadrage : calcule la transformation affine et l'applique.

        Algorithme
        ----------
        1. Calcule la transformation affine inverse (canvas → image source)
           en tenant compte du scale total, de la rotation et des offsets.
           La matrice affine 2×3 (à 6 paramètres) est passée directement à
           `Image.transform(..., Image.Transform.AFFINE, ...)` avec
           rééchantillonnage BICUBIC.
        2. Sur le résultat, applique la conversion N&B (`is_bw`).
        3. Aplatit le canal alpha sur fond blanc et retourne une image RGB.

        Note : les zones en dehors de l'image source apparaissent en blanc
        (fillcolor=(255,255,255,0) puis alpha composite à blanc).

        Parameters
        ----------
        target_w_px, target_h_px : int
            Dimensions de l'image de sortie en pixels.
        canvas_w, canvas_h : float
            Dimensions du canevas de référence en pixels écran.
        base_scale : float
            Scale de base calculé au chargement pour couvrir ce canevas.
        offset_x, offset_y : float
            Décalage de pan utilisateur en pixels écran.
        scale_override : float or None, optional
            Si fourni, écrase `self.scale` (utile pour les snapshots).

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB.
        """

        active_zoom_scale = scale_override if scale_override is not None else self.scale
        view = image_ops.CropView(
            canvas_w=canvas_w, canvas_h=canvas_h, base_scale=base_scale,
            offset_x=offset_x, offset_y=offset_y, scale=active_zoom_scale,
            rotation=self.rotation, original_width=self.original_width,
            original_height=self.original_height,
            display_w=self.display_w, display_h=self.display_h,
        )
        return image_ops.compute_crop_with_canvas(
            self.current_pil_image, target_w_px, target_h_px, view,
            is_bw=self.is_bw,
            rembg_erosion_pct=getattr(self, 'rembg_erosion_pct', 0.0),
            rembg_feather_pct=getattr(self, 'rembg_feather_pct', 0.0),
            rembg_bg_mode=getattr(self, 'rembg_bg_mode', 0),
            rembg_original=self._rembg_original,
        )

    # ================================================================ #
    #                       MODE FIT-IN                               #
    # ================================================================ #
    def _compute_fit_in(self, target_w_px, target_h_px):
        """
        Calcule l'image entière redimensionnée pour tenir dans le format
        cible, avec des bords blancs sur les 2 côtés les plus courts.

        Contrairement à `_compute_crop` (mode crop / remplissage), cette
        méthode utilise un scale ``min`` pour que l'image entière soit
        visible. La rotation est toujours 0 (ignorée). Délègue à
        `image_ops.compute_fit_in`.
        """

        return image_ops.compute_fit_in(
            self.current_pil_image, target_w_px, target_h_px,
            self.original_width, self.original_height, is_bw=self.is_bw,
            rembg_erosion_pct=getattr(self, 'rembg_erosion_pct', 0.0),
            rembg_feather_pct=getattr(self, 'rembg_feather_pct', 0.0),
            rembg_bg_mode=getattr(self, 'rembg_bg_mode', 0),
            rembg_original=self._rembg_original,
        )



    # ================================================================ #
    #              AMÉLIORATION & AJUSTEMENTS                         #
    # ================================================================ #
    def _adaptive_enhance(self, input_image):
        """
        Améliore automatiquement les images sous-exposées ou ternes.

        Stratégie
        ---------
        1. Conversion en YCbCr pour travailler uniquement sur la luminance Y.
        2. Calcul de la luminance moyenne (`mean_y`).
        3. **Si l'image est déjà bien exposée** (mean_y ≥ 148) : seule la
           saturation est boostée de +32 % (ImageEnhance.Color × 1.32).
        4. **Sinon** :
           a. Correction gamma : exposant calculé pour ramener mean_y vers
              148 sans jamais dépasser +42 niveaux (limité à 0.60–0.95).
           b. Léger étirement des contrastes (percentiles 0.5 % / 99.5 %).
           c. Saturation boostée de +42 % (ImageEnhance.Color × 1.42).

        Note : cette méthode n'est plus exposée directement dans l'UI mais
        reste accessible pour compatibilité avec d'anciens snapshots.

        Parameters
        ----------
        input_image : PIL.Image.Image
            Image RGB à améliorer.

        Returns
        -------
        PIL.Image.Image
            Image RGB améliorée.
        """

        ycbcr_image = input_image.convert("YCbCr")
        y, cb, cr = ycbcr_image.split()
        luminance_array = np.array(y, dtype=np.float32)
        mean_luminance = luminance_array.mean()



        # Saturation toujours boostée, correction luminosité uniquement si image sombre
        if mean_luminance >= 148:
            return ImageEnhance.Color(input_image).enhance(1.32)



        # Correction gamma : ramène la moyenne vers 148 sans dépasser +42 unités
        target_luminance = min(148.0, mean_luminance + 42.0)
        gamma = math.log(target_luminance / 255.0) / math.log(max(mean_luminance, 1.0) / 255.0)
        gamma = max(0.60, min(0.95, gamma))  # Bornes de sécurité

        adjusted_luminance = np.power(luminance_array / 255.0, gamma) * 255.0



        # Léger étirement des contrastes (coupe 0.5 % à chaque extrémité)
        low_percentile  = np.percentile(adjusted_luminance, 0.5)
        high_percentile = np.percentile(adjusted_luminance, 99.5)
        if high_percentile > low_percentile:
            adjusted_luminance = (adjusted_luminance - low_percentile) * 255.0 / (high_percentile - low_percentile)
        adjusted_luminance = np.clip(adjusted_luminance, 0, 255).astype(np.uint8)

        adjusted_y_channel = Image.fromarray(adjusted_luminance, "L")
        enhanced_image = Image.merge("YCbCr", (adjusted_y_channel, cb, cr)).convert("RGB")
        return ImageEnhance.Color(enhanced_image).enhance(1.42)



    def _apply_adjustments(self, input_image):
        """
        Applique les réglages d'exposition, contraste et saturation.

        Les trois curseurs sont appliqués successivement dans l'ordre
        exposition → contraste → saturation.

        Exposition
            Implémentée via une LUT gamma-like (table de correspondance 256
            valeurs) : factor = 2^(exposure/100). +100 ≙ ×2 lumière,
            -100 ≙ ÷2 lumière. Application via numpy pour la performance.
        Contraste
            `ImageEnhance.Contrast(img).enhance(1.0 + contrast/100)` :
            0 = neutre, +20 = 1.2×, -20 = 0.8×.
        Saturation
            `ImageEnhance.Color(img).enhance(max(0, 1.0 + saturation/100))` :
            0 = image désaturée (gris), 100 = saturation doublée.

        Parameters
        ----------
        img : PIL.Image.Image
            Image en mode RGB ou convertible en RGB.

        Returns
        -------
        PIL.Image.Image
            Image RGB ajustée.
        """

        return image_ops.apply_adjustments(
            input_image, exposure=self.exposure, contrast=self.contrast,
            saturation=self.saturation, hue=self.hue,
            white_balance=self.white_balance,
        )



    def _apply_shadows(self, input_image, value):
        """Ombres : délègue à `image_ops.apply_shadows`."""

        return image_ops.apply_shadows(input_image, value)



    def _apply_highlights(self, input_image, value):
        """Hautes lumières : délègue à `image_ops.apply_highlights`."""

        return image_ops.apply_highlights(input_image, value)



    def _apply_hue(self, input_image, value):
        """Teinte : délègue à `image_ops.apply_hue`."""

        return image_ops.apply_hue(input_image, value)



    def _apply_white_balance(self, input_image, value):
        """Balance des blancs : délègue à `image_ops.apply_white_balance`."""

        return image_ops.apply_white_balance(input_image, value)

    # ================================================================ #
    #              RENDU (HISTOGRAMME & APERÇU)                       #
    # ================================================================ #
    def _render_histogram(self, preview_img):
        """Génère un histogramme de luminance (N&B) lisible pour l'exposition."""

        if not self.show_histogram:
            return

        histogram_width, histogram_height = RIGHT_COL_WIDTH, HISTOGRAM_HEIGHT
        luminance_array = np.asarray(preview_img.convert("L"), dtype=np.uint8)

        # Histogramme réel 256 bins (0..255) sur l'image affichée.
        counts_256 = np.bincount(luminance_array.ravel(), minlength=256)[:256].astype(np.float32)

        # Remap 256 bins -> largeur du widget sans interpolation continue,
        # pour ne pas inventer de valeurs dans des zones vides.
        if histogram_width < 256:
            counts = np.zeros(histogram_width, dtype=np.float32)
            mapped_x = (np.arange(256, dtype=np.int32) * histogram_width) // 256
            mapped_x = np.clip(mapped_x, 0, histogram_width - 1)
            np.add.at(counts, mapped_x, counts_256)
        elif histogram_width > 256:
            mapped_x = np.round(np.linspace(0, 255, histogram_width)).astype(np.int32)
            counts = counts_256[mapped_x]
        else:
            counts = counts_256.copy()

        # Échelle robuste : limite l'impact d'un pic extrême pour mieux lire
        # les valeurs intermédiaires, tout en gardant un histogramme intuitif.
        peak_reference = max(float(np.percentile(counts, 99.9)), 1.0)
        heights = np.clip((counts / peak_reference) * (histogram_height - 1), 0, histogram_height - 1)

        histogram_image = Image.new("RGBA", (histogram_width, histogram_height), (20, 20, 26, 255))
        draw = ImageDraw.Draw(histogram_image, "RGBA")
        baseline_y = histogram_height - 1
        # Tronque le bruit visuel de fond: les barres trop faibles sont ignorées.
        min_visible_height_px = 2.0
        for x in range(histogram_width):
            if counts[x] <= 0:
                continue
            if float(heights[x]) < min_visible_height_px:
                continue
            top_y = baseline_y - int(round(float(heights[x])))
            top_y = max(0, min(baseline_y, top_y))
            draw.line([(x, baseline_y), (x, top_y)], fill=(235, 235, 235, 220), width=1)
            draw.point((x, top_y), fill=(248, 248, 248, 245))

        histogram_pil_image = histogram_image.convert("RGB")
        png_buffer = io.BytesIO()
        histogram_pil_image.save(png_buffer, format="PNG")
        self.histogram_image.src = "data:image/png;base64," + base64.b64encode(png_buffer.getvalue()).decode()
        try:
            self.histogram_image.update()
        except Exception:
            pass



    def _render_preview(self, *, update_histogram: bool = True):
        """
        Génère et affiche la prévisualisation dans le canvas Flet.

        Pipeline de rendu
        -----------------
        1. Copie et aplatissement de l'alpha de `current_pil_image`.
        2. Redimensionnement rapide (BILINEAR) à `display_w` × `display_h`
           pour limiter la charge CPU lors des interactions.
        3. Conversion N&B si `is_bw` est actif.
        4. Application de `_apply_adjustments` (expo, contraste, saturation).
        5. Application des courbes ombres et hautes lumières si non nulles.
        6. Netteté via deux passes d'UnsharpMask si `is_sharpen` est actif.
        7. Conversion sRGB via `convert_to_srgb` (alignement colorimétrique
           avec l'export final).
        8. Sauvegarde JPEG qualité 88 dans un fichier temporaire nommé
           `_rc_<compteur>.jpg` dans `_preview_tmp_dir`.
           Un nom unique est nécessaire pour invalider le cache image de
           Flutter/Flet (le chemin doit changer à chaque mise à jour).
        9. Suppression du fichier précédent pour ne garder qu'un seul
           fichier sur disque à tout instant.

        Cette méthode est appelée à chaque modification d'un filtre ou
        lors du chargement d'une nouvelle image. Elle NE rafraîchit PAS
        `self.page` ; l'appelant le fait si nécessaire.
        """

        payload = self._compute_preview_payload()
        if payload is None:
            return
        preview_src, preview_image = payload
        self.image_display.src = preview_src
        self.image_display.update()
        if update_histogram and self.show_histogram:
            self._render_histogram(preview_image)

    def _compute_preview_payload(self):
        """Pipeline de rendu de l'aperçu -> (data URI JPEG, image sRGB
        pour l'histogramme), ou None si rien à rendre. Pur calcul PIL,
        aucun contrôle Flet touché : appelable depuis le thread d'aperçu
        live (_live_preview_loop) comme depuis le thread UI
        (_render_preview)."""
        if getattr(self, 'current_pil_image', None) is None:
            return None
        if not hasattr(self, 'display_w'):
            return None

        # Cacher l'image de base réduite pour la preview afin d'éviter de redimensionner
        # une image géante (plusieurs mégapixels) à chaque petit mouvement de curseur.
        # Comparaison par identité (is) et non par id() : un id est
        # réutilisable après garbage collection (préchargement d'images).
        base_cache = getattr(self, '_preview_base_cache', None)
        if (isinstance(base_cache, dict)
                and base_cache.get("src") is self.current_pil_image):
            preview_image = base_cache["base"].copy()
            preview_width, preview_height = preview_image.size
        else:
            ratio = min(PREVIEW_MAX_PIXELS / self.original_width, PREVIEW_MAX_PIXELS / self.original_height, 1.0)
            preview_width  = max(1, int(self.original_width  * ratio))
            preview_height = max(1, int(self.original_height * ratio))
            preview_image = self.current_pil_image.resize((preview_width, preview_height), Image.Resampling.BILINEAR)
            self._preview_base_cache = {"src": self.current_pil_image,
                                        "base": preview_image.copy()}
        
        if preview_image.mode == "RGBA":
            # Clé de cache : image source + taille d'affichage + format + paramètres de composition
            composite_cache_key = (
                id(self.current_pil_image), preview_width, preview_height,
                round(self.canvas_w), self.canvas_is_portrait,
                getattr(self, 'rembg_erosion_pct', 0.0),
                getattr(self, 'rembg_feather_pct', 0.0),
                getattr(self, 'rembg_bg_mode', 0),
            )
            if self._rembg_composite_cache is not None and self._rembg_composite_cache[0] == composite_cache_key:
                # Cache valide : réutiliser le composite sans recalculer
                preview_image = self._rembg_composite_cache[1].copy()
            else:
                # Érosion/adoucissement au format réduit — beaucoup plus rapide qu'à
                # pleine résolution. Le rayon est mis à l'échelle pour que la preview
                # corresponde au résultat final. L'échelle correcte est
                # canvas_w / target_w_px (affichage → export), et non
                # display_w / orig_w (qui sous-estime fortement pour les petits formats).
                if getattr(self, 'rembg_erosion_pct', 0.0) > 0:
                    erosion_radius_scaled = max(1, round(min(preview_image.size) * self.rembg_erosion_pct / 100))
                    preview_image = _erode_alpha(preview_image, erosion_radius_scaled)
                if getattr(self, 'rembg_feather_pct', 0.0) > 0:
                    feather_radius_scaled = max(1, round(min(preview_image.size) * self.rembg_feather_pct / 100))
                    preview_image = _feather_alpha(preview_image, feather_radius_scaled)
                _bg_mode = getattr(self, 'rembg_bg_mode', 0)
                if _bg_mode == 0:
                    background_layer = Image.new("RGBA", preview_image.size, (255, 255, 255, 255))
                elif _bg_mode == 1:
                    background_layer = Image.new("RGBA", preview_image.size, (230, 230, 230, 255))
                else:
                    # Utiliser l'image originale (opaque) comme source du flou pour éviter
                    # les débordements noirs des pixels transparents (alpha=0 → noir en RGBA→RGB)
                    blur_source_image = self._rembg_original if self._rembg_original is not None else None
                    if blur_source_image is not None:
                        blurred_background = blur_source_image.convert("RGB").resize((preview_width, preview_height), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(radius=30))
                    else:
                        white_background = Image.new("RGBA", preview_image.size, (255, 255, 255, 255))
                        blurred_background = Image.alpha_composite(white_background, preview_image).convert("RGB").filter(ImageFilter.GaussianBlur(radius=30))
                    background_layer = blurred_background.convert("RGBA")
                preview_image = Image.alpha_composite(background_layer, preview_image).convert("RGB")
                self._rembg_composite_cache = (composite_cache_key, preview_image.copy())
        else:
            preview_image = preview_image.convert("RGB")

        # Noir et blanc
        if self.is_bw:
            preview_image = ImageOps.grayscale(preview_image).convert("RGB")

        # Contraste, saturation, exposition
        preview_image = self._apply_adjustments(preview_image)

        # Ombres
        if self.shadows != 0:
            preview_image = self._apply_shadows(preview_image, self.shadows)

        # Hautes lumières
        if self.highlights != 0:
            preview_image = self._apply_highlights(preview_image, self.highlights)

        # Blancs / Noirs (points extrêmes)
        if getattr(self, 'whites', 0) != 0:
            preview_image = image_ops.apply_whites(preview_image, self.whites)
        if getattr(self, 'blacks', 0) != 0:
            preview_image = image_ops.apply_blacks(preview_image, self.blacks)

        # Netteté
        if self.is_sharpen:
            preview_image = preview_image.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            preview_image = preview_image.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))
        
        # Conversion sRGB : aligner le preview sur l'image enregistrée
        preview_image = convert_to_srgb(preview_image, getattr(self, 'icc_profile', None))

        # Compensation écran (sRGB -> profil du moniteur) : APPLIQUÉE À
        # L'AFFICHAGE SEULEMENT — l'histogramme reçoit l'image sRGB non
        # compensée, et l'export n'est jamais touché. Sur un écran large
        # gamut (EIZO, dalles P3), Flutter affiche les pixels bruts : sans
        # cette étape, l'aperçu était nettement plus saturé qu'Aperçu/
        # Photos (retour user).
        display_image = image_ops.compensate_for_display(preview_image)

        # Encoder en mémoire — élimine l'I/O disque, invalide le cache Flutter via données uniques
        jpeg_buffer = io.BytesIO()
        display_image.save(jpeg_buffer, format="JPEG", quality=70)
        preview_src = ("data:image/jpeg;base64,"
                       + base64.b64encode(jpeg_buffer.getvalue()).decode())
        return preview_src, preview_image

    # ================================================================ #
    #        APERÇU LIVE PENDANT LE DRAG DES SLIDERS                   #
    # ================================================================ #
    def _live_preview_tick(self):
        """À appeler depuis les handlers on_change des sliders : rend
        l'aperçu en continu pendant le glissement, sur un thread dédié.
        « La dernière valeur gagne » : si les ticks arrivent plus vite que
        les rendus, les valeurs intermédiaires sont simplement sautées —
        jamais de file d'attente qui traîne derrière le curseur. Le rendu
        complet (avec histogramme) reste fait au relâchement par les
        handlers on_change_end existants."""
        with self._live_lock:
            self._live_req += 1
            if self._live_running:
                return
            self._live_running = True
        threading.Thread(target=self._live_preview_loop, daemon=True).start()

    def _live_preview_loop(self):
        while True:
            request_seen = self._live_req
            try:
                payload = self._compute_preview_payload()
            except Exception:
                payload = None
            if payload is not None:
                preview_src = payload[0]

                async def _apply(src=preview_src):
                    self.image_display.src = src
                    try:
                        self.image_display.update()
                    except Exception:
                        pass

                try:
                    self.page.run_task(_apply)
                except Exception:
                    pass
            with self._live_lock:
                if self._live_req == request_seen:
                    self._live_running = False
                    return
            time.sleep(0.03)   # ~30 fps max, laisse respirer le thread UI



    # ================================================================ #
    #                  NAVIGATION (PAN, ZOOM, ROTATION)                #
    # ================================================================ #


    # ================================================================ #
    #              GESTIONNAIRES DE GESTES                            #
    # ================================================================ #
    def on_pan_down(self, e):
        """Contact initial du clic — n'agit que si la pipette (mode
        Instantané) attend un clic, sinon laisse `on_pan_update` gérer le
        pan normal. Utilise `on_pan_down` (déclenché instantanément) et
        non `on_pan_start` : ce dernier n'est reconnu par Flutter qu'après
        un léger mouvement, donc sa position n'est déjà plus le point
        cliqué (retour user : la sélection tombait sur le sujet au lieu
        du fond cliqué).

        Ajoute ou retire de la sélection selon `self._pipette.sign`,
        piloté par le bouton bascule `pipette_sign_btn` (cf.
        `on_pipette_sign_toggle`) — PAS par le bouton de la souris : les
        événements clic droit (`on_secondary_tap_down`/`on_right_pan_*`)
        ne se déclenchent pas du tout dans cette version de Flet/Flutter
        combinés aux gestionnaires de pan existants (retour user, testé)."""

        if not self._pipette.armed:
            return
        self._pipette_start = (e.local_position.x, e.local_position.y)
        self._pipette.start_drag()

    def _pipette_drag_tick(self, tol: int) -> None:
        """Commun aux glissés gauche/droit : affiche la tolérance live et
        déclenche un aperçu throttlé (cf. `_pipette_live_preview`)."""

        self._rembg_tolerance_label.value = f"Tol. {tol}"
        self._rembg_tolerance_label.update()
        if self._pipette.try_start_live():
            px, py = self._pipette_start
            ix, iy = self._canvas_point_to_image(px, py)
            self.page.run_task(self._pipette_live_preview, ix, iy, tol)

    def on_pan_update(self, e):
        """Déplace l'image par glisser-déposer à la souris — ou, pipette
        armée, accumule la distance du glissé (= sensibilité du flood
        fill) et relance un aperçu en direct (throttlé : un seul recalcul
        à la fois, cf. `_pipette_live_preview`)."""
        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        if self._pipette.armed:
            if self._pipette_start is not None:
                self._pipette_drag_tick(self._pipette.drag(e.local_delta.x))
            return
        self.offset_x += e.local_delta.x
        self.offset_y += e.local_delta.y
        self._clamp_offsets()
        self._update_transform()

    def on_pan_end(self, e):
        """Relâchement du clic-glissé pipette : fixe la graine (point de
        clic) et la tolérance (distance du glissé, +/- 50 % par 100 px),
        applique le résultat définitivement (ajoute ou retire selon
        `self._pipette.sign`) — la pipette reste armée pour enchaîner un
        nouveau clic-glissé (utile si le fond n'est pas d'un seul tenant,
        ex. de part et d'autre d'un bras)."""

        if not self._pipette.armed or self._pipette_start is None:
            return
        px, py = self._pipette_start
        ix, iy = self._canvas_point_to_image(px, py)
        self._pipette_start = None
        tol = self._pipette.end_drag()
        self.page.run_task(self._apply_pipette_pick, ix, iy, tol)

    def on_gesture_scroll(self, e):
        """
        Défilement molette / trackpad deux doigts :
          - mode normal (badge absent) → scroll vertical → zoom.
          - mode Tab    (badge visible) → scroll vertical → rotation.
        """

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        dy = e.scroll_delta.y
        if self._scroll_rotates:
            # Mode Tab : molette → rotation (±15°)
            rotation_delta = dy * 0.005
            self.rotation = max(-15.0, min(15.0, self.rotation + rotation_delta))
            self.rotation_slider.value = self.rotation
            self.rotation_slider.label = f"{self.rotation:.2f}°"
            self.rotation_slider.update()
        else:
            # Mode normal : molette → zoom
            if dy != 0:
                zoom_delta = -dy * 0.0002
                self.scale = max(1.0, min(10.0, self.scale * (1.0 + zoom_delta)))
                zoom_slider_val = min(self.scale, self.zoom_slider.max)
                self.zoom_slider.value = zoom_slider_val
                self.zoom_slider.label = f"{self.scale:.2f}×"
                self.zoom_slider.update()
        self._clamp_offsets()
        self.zoom_slider.value = min(self.scale, self.zoom_slider.max)
        self.zoom_slider.label = f"{self.scale:.2f}×"
        self.zoom_slider.update()
        self._update_transform()



    def _update_shift_badge(self):
        """Affiche un SnackBar indiquant le mode de défilement actif."""

        if self._scroll_rotates:
            msg = "Molette → Rotation activée"
        else:
            msg = "Molette → Zoom activé"
        self._set_status(msg)
        self.page.update()



    def on_rotation_update(self, e):
        """
        Gestionnaire du slider de rotation (pendant le glissement).

        Met à jour `self.rotation` et le label du slider immédiatement
        (opération légère, synchrone). Le rendu affine (`_clamp_offsets`
        + `_update_transform`) est limité à 60 fps via `_last_rotation_render`
        pour éviter de saturer la file de messages Flet sur les machines
        lentes. La prévisualisation PIL n'est pas re-générée ici.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider ; `e.control.value` contient la
            valeur numérique courante en degrés.
        """

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        self.rotation = e.control.value
        e.control.label = f"{self.rotation:.2f}°"
        e.control.update()
        now = time.monotonic()
        if now - self._last_rotation_render < 1 / 30:
            return
        self._last_rotation_render = now
        self._clamp_offsets()
        self.zoom_slider.value = min(self.scale, self.zoom_slider.max)
        self.zoom_slider.label = f"{self.scale:.2f}×"
        self.zoom_slider.update()
        self._update_transform()



    def on_rotation_end(self, e):
        """Rafraîchit la prévisualisation et l'histogramme après la fin de la rotation."""

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        # Rotation = transform géométrique uniquement : ne pas relancer le rendu PIL.
        self._clamp_offsets()
        self._update_transform()



    def on_zoom_update(self, e):
        """
        Gestionnaire du slider de zoom (pendant le glissement).

        Met à jour `self.scale`, corrige les offsets proportionnellement
        et applique la transformation via les propriétés LayoutControl.
        """

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        target_scale = e.control.value
        previous_scale = self.scale
        self.scale = target_scale
        ratio = self.scale / previous_scale if previous_scale > 0 else 1.0
        if previous_scale != self.scale and abs(ratio - 1.0) > 1e-6:
            self.offset_x *= ratio
            self.offset_y *= ratio
        e.control.label = f"{self.scale:.2f}×"
        e.control.update()
        now = time.monotonic()
        if now - self._last_zoom_render < 1 / 30:
            return
        self._last_zoom_render = now
        self._clamp_offsets()
        e.control.value = min(self.scale, e.control.max)
        e.control.label = f"{self.scale:.2f}×"
        e.control.update()
        self._update_transform()



    def on_zoom_end(self, e):
        """Rafraîchit la prévisualisation et l'histogramme après la fin du zoom."""

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        # Zoom = transform géométrique uniquement : ne pas relancer le rendu PIL.
        self._clamp_offsets()
        self._update_transform()

    # ================================================================ #
    #              RÉINITIALISATIONS & SLIDERS                        #
    # ================================================================ #
    def reset_rotation(self, e):
        """
        Remet la rotation à zéro (0°).

        Remet à jour le slider, l'état interne, la transformation affine
        et rafraîchit la page.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du bouton « 0° » (non utilisé directement).
        """

        self.rotation = 0.0
        self.rotation_slider.value = self.rotation
        self.rotation_slider.label = f"{self.rotation:.2f}°"
        self.rotation_slider.update()
        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        self._clamp_offsets()
        self._update_transform()
        self._set_status("Rotation réinitialisée à 0°")



    def reset_zoom(self, e):
        """Remet le zoom à 1× et réinitialise le pan (double-clic sur le slider)."""

        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom_slider.value = 1.0
        self.zoom_slider.label = "1.00×"
        self.zoom_slider.update()
        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        self._update_transform()
        self._set_status("Zoom réinitialisé à 1× et pan réinitialisé")



    def _reset_slider(self, slider, attr, default_val, label_str):
        """Remet un slider de réglage à sa valeur par défaut et redéclenche le rendu."""

        setattr(self, attr, default_val)
        slider.value = default_val
        slider.label = label_str
        slider.update()
        self._render_preview()
        self.page.update()
        self._set_status("Slider réinitialisé")


    # ================================================================ #
    #                        TOGGLES & SWITCHES                        #
    # ================================================================ #
    def on_grid_toggle(self, e):
        """Active ou désactive la grille des tiers fixée au canevas."""

        self.show_grid = bool(e.control.value)
        for line in self._grid_lines:
            line.visible = self.show_grid
        self.page.update()



    def on_bw_toggle(self, e):
        """
        Active ou désactive le mode noir et blanc.

        Met à jour `is_bw` puis regénère la prévisualisation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Noir et blanc » ; `e.control.value` = bool.
        """

        self.is_bw = e.control.value
        self._render_preview()
        self.page.update()



    def on_fit_in_toggle(self, e):
        """
        Active ou désactive le mode Fit-in.

        En mode Fit-in, l'image entière tient dans le format choisi avec
        des bords blancs sur 2 côtés. La rotation est forcée à 0.
        Le pan et le zoom sont désactivés (l'image est trop petite pour
        déborder du canevas).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Fit-in » ; `e.control.value` = bool.
        """

        self.is_fit_in = bool(e.control.value)
        if self.is_fit_in:
            self.rotation = 0.0
            self.rotation_slider.value = 0.0
            self.rotation_slider.label = "0.00°"
            self.rotation_slider.update()
        if self.image_paths:
            self.load_image(preserve_orientation=True)
        self.page.update()



    def on_white_border_toggle(self, e):
        self.white_border = bool(e.control.value)
        self.page.update()



    def on_crop_mode_change(self, e):
        """Bascule entre Résolution / Ratio / Aucun recadrage."""
        idx = int(e.control.selected_index)
        self.crop_mode = ("resolution", "ratio", "none")[max(0, min(2, idx))]
        if self.image_paths:
            self.load_image(preserve_orientation=True)
        else:
            self.page.update()



    def on_sharpen_toggle(self, e):
        """
        Active ou désactive le filtre de netteté (UnsharpMask).

        Le filtre est appliqué en deux passes (radius 4 puis radius 2) à
        la fois sur la prévisualisation et lors de l'export final.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Netteté ».
        """

        self.is_sharpen = bool(e.control.value)
        self._render_preview()
        self.page.update()



    def on_rembg_model_toggle(self, e):
        """Bascule entre portrait et général."""

        self.rembg_human_seg = not self.rembg_human_seg

        # Invalider toutes les sessions pour forcer le rechargement
        self._rembg_session[0] = None
        self._rembg_session_u2net[0] = None
        if self.rembg_human_seg:
            self._rembg_model_label.value = "Humain"
            self.rembg_model_btn.bgcolor = VIOLET
        else:
            self._rembg_model_label.value = "Général"
            self.rembg_model_btn.bgcolor = BLUE
        self.rembg_model_btn.update()



    def on_rembg_precise_toggle(self, e):
        """Cycle rapide (u2net) -> précis (birefnet) -> instantané (flood)."""

        self._pipette_cancel()
        self.rembg_mode = (self.rembg_mode + 1) % 3
        if self.rembg_mode == 0:
            self._rembg_precise_label.value = "Rapide"
            self.rembg_precise_btn.bgcolor = BLUE
        elif self.rembg_mode == 1:
            self._rembg_precise_label.value = "Précis"
            self.rembg_precise_btn.bgcolor = VIOLET
        else:
            self._rembg_precise_label.value = "Instantané"
            self.rembg_precise_btn.bgcolor = GREEN
        self.rembg_precise_btn.update()
        self.pipette_sign_btn.visible = self.rembg_mode == 2
        self.pipette_sign_btn.update()

    def on_canvas_secondary_tap(self, e):
        """Clic droit (simple clic, sans glisser) sur le canevas — bascule
        ajoute/retire. Le clic droit GLISSÉ (`on_right_pan_*`) ne se
        déclenchait pas du tout combiné aux gestionnaires de pan gauche
        existants (retour user), mais un simple clic droit ponctuel
        (`on_secondary_tap`, sans recognizer de glissé concurrent) est un
        geste plus isolé, qui a de bonnes chances de fonctionner — d'où
        ce bouton en secours si jamais ce n'est pas le cas."""

        if self.rembg_mode == 2:
            self.on_pipette_sign_toggle(e)

    def on_pipette_sign_toggle(self, e):
        """Bascule la pipette entre ajoute (+ vert) et retire (− rouge),
        via le bouton `pipette_sign_btn` ou un clic droit sur le canevas
        (cf. `on_canvas_secondary_tap`)."""

        self._pipette.toggle_sign()
        self._sync_pipette_sign_btn()

    def _sync_pipette_sign_btn(self) -> None:
        """Aligne l'icône/couleur/tooltip de `pipette_sign_btn` sur
        `self._pipette.sign` — appelé après bascule ou reset."""

        if self._pipette.sign == 1:
            self.pipette_sign_btn.icon = ft.Icons.ADD_CIRCLE_OUTLINE
            self.pipette_sign_btn.icon_color = GREEN
            self.pipette_sign_btn.tooltip = "Pipette : ajoute à la sélection (cliquer pour passer en retrait)"
        else:
            self.pipette_sign_btn.icon = ft.Icons.REMOVE_CIRCLE_OUTLINE
            self.pipette_sign_btn.icon_color = RED
            self.pipette_sign_btn.tooltip = "Pipette : retire de la sélection (cliquer pour repasser en ajout)"
        self.pipette_sign_btn.update()



    def on_rembg_erosion_change(self, e):
        """Met à jour le % d'érosion pendant le drag (pas de rendu)."""

        self.rembg_erosion_pct = round(e.control.value, 1)



    def on_rembg_erosion_end(self, e):
        """Regénère la preview au relâchement du slider d'érosion."""

        self.rembg_erosion_pct = round(e.control.value, 1)
        self._render_preview()
        self.page.update()

    def on_rembg_feather_change(self, e):
        """Met à jour le % d'adoucissement pendant le drag (pas de rendu)."""

        self.rembg_feather_pct = round(e.control.value, 2)

    def on_rembg_feather_end(self, e):
        """Regénère la preview au relâchement du slider d'adoucissement."""

        self.rembg_feather_pct = round(e.control.value, 2)
        self._render_preview()
        self.page.update()



    def _pipette_cancel(self):
        """Désarme la pipette (mode Instantané) sans rien appliquer —
        appelé si l'utilisateur change de mode ou d'image pendant que la
        pipette attend un clic."""

        if self._pipette.armed:
            self._pipette.disarm()
            self.gesture_detector.mouse_cursor = ft.MouseCursor.MOVE

    def _canvas_point_to_image(self, px: float, py: float) -> tuple[int, int]:
        """Convertit un point du canevas (repère de `gesture_detector`,
        même origine que `image_container.left/top`) en coordonnées pixel
        de l'image ORIGINALE, en inversant pan + zoom + rotation appliqués
        par `_update_transform`."""

        cx = self.canvas_w / 2 + self.offset_x
        cy = self.canvas_h / 2 + self.offset_y
        dx, dy = px - cx, py - cy
        theta = -math.radians(self.rotation)
        rdx = dx * math.cos(theta) - dy * math.sin(theta)
        rdy = dx * math.sin(theta) + dy * math.cos(theta)
        eff_scale = self.base_scale * self.scale
        ix = self.original_width / 2 + rdx / eff_scale
        iy = self.original_height / 2 + rdy / eff_scale
        ix = max(0, min(self.original_width - 1, round(ix)))
        iy = max(0, min(self.original_height - 1, round(iy)))
        return ix, iy

    async def _pipette_live_preview(self, ix: int, iy: int, tolerance: int) -> None:
        """Aperçu en direct pendant le glissé : calcule le flood fill du
        point courant, le combine (cf. `image_ops.FloodPipette.combine`)
        au masque déjà accumulé sans encore le persister — `on_pan_end`/
        `_apply_pipette_pick` fait la version définitive. Throttlé par
        le verrou `live_busy`, déjà posé par `_pipette.try_start_live()`
        (appelant, synchrone — cf. sa docstring pour la raison)."""

        my_gen = self._pipette.live_gen = self._pipette.live_gen + 1
        try:
            source = self._rembg_original or self.current_pil_image
            new_mask = await asyncio.to_thread(
                image_ops.flood_background_mask, source, (ix, iy),
                tolerance=tolerance, max_px=900)  # résolution réduite : priorité à la fluidité
            if my_gen != self._pipette.live_gen:
                return  # un pick s'est terminé / un glissé plus récent a démarré entretemps
            combined = self._pipette.combine(new_mask)
            if combined is not None:
                self.current_pil_image = image_ops.compose_bg_alpha(source, combined)
                self._render_preview()
                self.page.update()
        except Exception:
            pass  # un aperçu raté pendant le glissé n'est pas bloquant, cf. _apply_pipette_pick
        finally:
            self._pipette.live_busy = False

    async def _apply_pipette_pick(self, ix: int, iy: int, tolerance: int) -> None:
        """Version définitive du flood fill pipette : persiste le masque
        combiné (cf. `image_ops.FloodPipette.commit`) et laisse la
        pipette armée pour enchaîner un autre clic-glissé."""

        source = self._rembg_original or self.current_pil_image
        self._set_status("Détourage instantané…", processing=True)
        self.page.update()
        try:
            new_mask = await asyncio.to_thread(
                image_ops.flood_background_mask, source, (ix, iy),
                tolerance=tolerance, max_px=1500)
            bg_mask = self._pipette.commit(new_mask)
            self._rembg_original = source
            if bg_mask is not None:
                self.current_pil_image = image_ops.compose_bg_alpha(source, bg_mask)
                self.rembg_btn.selected = True
                self._set_status(
                    "[OK] Fond supprimé — glissez pour ajouter/retirer, recliquer pour restaurer")
            else:
                self.current_pil_image = source
                self.rembg_btn.selected = False
                self._set_status("Rien à retirer — glissez d'abord pour ajouter une sélection")
            self._rembg_tolerance_label.value = f"Tol. {tolerance}"
        except Exception as ex:
            self._set_status(f"[ERREUR] détourage : {ex}")
        finally:
            self._render_preview()
            self.page.update()



    def on_rembg_bg_toggle(self, e):
        """Cycle blanc → gris clair → flou → blanc (3 états)."""

        self.rembg_bg_mode = (self.rembg_bg_mode + 1) % 3
        if self.rembg_bg_mode == 0:
            self._rembg_bg_label.value = "Fond blanc"
            self._rembg_bg_label.color = DARK
            self.rembg_bg_btn.bgcolor = ft.Colors.GREY_200
            self.rembg_bg_btn.tooltip = "Fond blanc / Fond gris / Fond flou"
        elif self.rembg_bg_mode == 1:
            self._rembg_bg_label.value = "Fond gris"
            self._rembg_bg_label.color = DARK
            self.rembg_bg_btn.bgcolor = ft.Colors.GREY_400
            self.rembg_bg_btn.tooltip = "Fond blanc / Fond gris / Fond flou"
        else:
            self._rembg_bg_label.value = "Fond flou"
            self._rembg_bg_label.color = DARK
            self.rembg_bg_btn.bgcolor = BLUE
            self.rembg_bg_btn.tooltip = "Fond blanc / Fond gris / Fond flou"
        self.rembg_bg_btn.update()
        self._render_preview()
        self.page.update()



    async def on_rembg(self, e):
        """
        Bouton toggle de suppression du fond (``self.rembg_mode`` :
        0 = rapide/u2net, 1 = précis/birefnet, 2 = instantané/flood fill
        sans IA — pour fond studio quasi uniforme, cf. ``on_rembg_precise_toggle``).

        Comportement toggle
        -------------------
        * **Premier clic** (icône grise → violette) :
            Sauvegarde ``current_pil_image`` dans ``_rembg_original``, lance
            le traitement IA et remplace ``current_pil_image`` par le résultat
            RGBA. Le statut affiche ``[OK] Fond supprimé — recliquer pour
            restaurer``.
        * **Deuxième clic** (icône violette → grise) :
            Restaure ``_rembg_original`` dans ``current_pil_image`` sans
            relancer rembg. Rapide et réversible à tout moment.
        * Au chargement d'une nouvelle image, ``_rembg_original`` est remis
          à ``None`` et le bouton repasse en gris.

        Pipeline asynchrone
        -------------------
        Le calcul rembg (bloquant) est délégué à un thread pool via
        ``asyncio.to_thread(_do_rembg)``. Les mises à jour UI (``_render_preview``,
        ``page.update``) s'exécutent ensuite sur la boucle asyncio principale
        de Flet, garantissant un rafraîchissement immédiat sans avoir à
        utiliser des threads secondaires ou des callbacks explicites.

        Modèle IA
        ---------
        ``birefnet-portrait`` — modèle spécialisé sujets humains, téléchargé
        automatiquement dans ``~/.u2net/`` (~450 Mo) à la première utilisation.
        La session est mise en cache dans ``self._rembg_session[0]`` pour
        éviter de recharger le modèle à chaque clic.

        Mode précis / instantané
        ------------------------
        Voir ``on_rembg_precise_toggle`` pour le détail des 3 modes
        (``self.rembg_mode``).

        Fond de remplacement
        --------------------
        ``current_pil_image`` reste en mode RGBA après traitement. L'aplatissement
        sur fond blanc (255,255,255) ou gris clair (220,220,220) est
        effectué à la volée dans ``_render_preview`` et à l'export, selon
        ``self.rembg_bg_mode`` (0=blanc, 1=gris clair, 2=flou).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton icône (``on_click``).
        """

        if self.rembg_mode != 2 and not REMBG_AVAILABLE:
            self._set_status("[ERREUR] rembg non installé — pip install rembg onnxruntime")
            return
        if self.current_pil_image is None:
            self._set_status("[ERREUR] aucune image chargée")
            return



        # Pipette armée mais aucun pick encore appliqué : rien à
        # restaurer, ce clic annule juste l'armement.
        if self._pipette.armed and not self.rembg_btn.selected:
            self._pipette_cancel()
            self._set_status("Pipette désarmée")
            self.page.update()
            return

        # Deuxième clic : restaurer TOUT le masque accumulé (pas juste le
        # dernier pick ajouté/retiré) — retour user : un clic doit tout
        # annuler d'un coup, pas se figer d'abord en un état intermédiaire.
        if self.rembg_btn.selected and self._rembg_original is not None:
            self._pipette_cancel()
            self.current_pil_image = self._rembg_original
            self._rembg_original = None
            self._pipette.reset()
            self._sync_pipette_sign_btn()
            self.rembg_btn.selected = False
            self._set_status("Fond restauré")
            self._render_preview()
            self.page.update()
            return

        if self.rembg_mode == 2:
            # Mode instantané : arme la pipette, le flood fill part du
            # prochain clic-glissé sur l'image (cf. on_pan_down/_end).
            self._pipette.arm()
            self.gesture_detector.mouse_cursor = ft.MouseCursor.PRECISE
            self._set_status("Cliquez sur le fond et glissez pour ajuster la sensibilité…")
            self.page.update()
            return

        self.rembg_btn.disabled = True
        self._set_status("Suppression du fond en cours…", processing=True)
        self.page.update()



        def _do_rembg():
            from rembg import remove as _rembg_remove, new_session as _rembg_new_session
            if self.rembg_mode == 1:
                # Mode précis : birefnet
                if self._rembg_session[0] is None:
                    model_name = "birefnet-portrait" if self.rembg_human_seg else "birefnet-general"
                    self._rembg_session[0] = _rembg_new_session(model_name)
                sess = self._rembg_session[0]
            else:
                # Mode rapide : u2net
                if self._rembg_session_u2net[0] is None:
                    model_name = "u2net_human_seg" if self.rembg_human_seg else "u2net"
                    self._rembg_session_u2net[0] = _rembg_new_session(model_name)
                sess = self._rembg_session_u2net[0]
            with contextlib.redirect_stderr(io.StringIO()):
                result = _rembg_remove(self.current_pil_image.convert("RGB"), session=sess)
            return result.convert("RGBA")

        try:
            result = await asyncio.to_thread(_do_rembg)
            self._rembg_original = self.current_pil_image
            self.current_pil_image = result
            self.rembg_btn.selected = True
            self._set_status("[OK] Fond supprimé — recliquer pour restaurer")
        except Exception as ex:
            self._set_status(f"[ERREUR] rembg : {ex}")
        finally:
            self.rembg_btn.disabled = False
            self._render_preview()
            self.page.update()



    def on_network_toggle(self, e):
        """
        Active ou désactive la sauvegarde des planches ID ×4 sur le réseau.

        Quand activé, les planches ID ×4 sont sauvegardées dans le dossier
        réseau `z2026` (NAS DiskStation) plutôt que dans le dossier source.
        Le chemin réseau est adapté automatiquement selon le système
        d'exploitation (Windows : UNC, macOS/Linux : point de montage).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Sauver sur réseau ».
        """

        self.save_to_network = bool(e.control.value)



    def on_border_toggle_polaroid(self, e):
        """
        Active / désactive le cadre Polaroid.

        Place la photo 10x10 centrée avec des marges blanches égales
        sur un fond 127×152 mm (format Polaroid classique).
        Mutuellement exclusif avec le mode 13x10.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Polaroid ».
        """

        self.border_polaroid = bool(e.control.value)
        self.page.update()



    def on_border_toggle_id2(self, e):
        """
        Active / désactive la planche ID ×2 (deux photos d'identité
        sur un tirage 10x10).

        Mutuellement exclusif avec la planche ID ×4 : activer ID X2
        désactive automatiquement ID X4.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « ID X2 ».
        """

        self.border_id2 = bool(e.control.value)
        if self.border_id2:
            self.border_id4 = False
            self.border_switch_ID4.value = False
            self.page.update()



    def on_border_toggle_id4(self, e):
        """
        Active / désactive la planche ID ×4 (quatre photos d'identité
        sur un tirage 10x13, espacées de 5 mm).

        Mutuellement exclusif avec la planche ID ×2 : activer ID X4
        désactive automatiquement ID X2.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « ID X4 ».
        """

        self.border_id4 = bool(e.control.value)
        if self.border_id4:
            self.border_id2 = False
            self.border_switch_ID2.value = False
        self.id4_10x20_switch.visible = self.border_id4
        self.page.update()



    def on_id4_10x20_toggle(self, e):
        """Active / désactive le format 10x20 pour la planche ID ×4."""
        self.id4_10x20 = bool(e.control.value)



    # Label uniquement (pendant le glissement)
    def on_shadows_label(self, e):
        """
        Mise à jour du label du slider Ombres pendant le glissement.

        Met à jour `self.shadows` et le label affiché sur le slider
        sans regénérer la prévisualisation (pour la fluidité du drag).
        Le rendu n'est déclenché qu'au relâchement via `on_shadows_end`.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """

        self.shadows = e.control.value
        e.control.label = str(int(self.shadows))
        e.control.update()
        self._live_preview_tick()



    # Rendu au relâchement
    def on_shadows_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Ombres.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement (`on_change_end`).
        """

        self.shadows = e.control.value
        self._render_preview()
        self.page.update()



    def on_highlights_label(self, e):
        """
        Mise à jour du label du slider Hautes Lumières pendant le glissement.

        Même logique que `on_shadows_label` : mise à jour visuelle seule,
        pas de rendu.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """

        self.highlights = e.control.value
        e.control.label = str(int(self.highlights))
        e.control.update()
        self._live_preview_tick()



    def on_highlights_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider
        Hautes Lumières.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement (`on_change_end`).
        """

        self.highlights = e.control.value
        self._render_preview()
        self.page.update()



    def on_whites_label(self, e):
        """Mise à jour du label du slider Blancs pendant le glissement
        (aperçu live, rendu complet au relâchement)."""
        self.whites = e.control.value
        e.control.label = str(int(self.whites))
        e.control.update()
        self._live_preview_tick()

    def on_whites_end(self, e):
        """Rendu complet au relâchement du slider Blancs."""
        self.whites = e.control.value
        self._render_preview()
        self.page.update()

    def on_blacks_label(self, e):
        """Mise à jour du label du slider Noirs pendant le glissement
        (aperçu live, rendu complet au relâchement)."""
        self.blacks = e.control.value
        e.control.label = str(int(self.blacks))
        e.control.update()
        self._live_preview_tick()

    def on_blacks_end(self, e):
        """Rendu complet au relâchement du slider Noirs."""
        self.blacks = e.control.value
        self._render_preview()
        self.page.update()

    def on_contrast_label(self, e):
        """
        Mise à jour du label du slider Contraste pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """

        self.contrast = e.control.value
        e.control.label = str(int(self.contrast))
        e.control.update()
        self._live_preview_tick()



    def on_contrast_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Contraste.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """

        self.contrast = e.control.value
        self._render_preview()
        self.page.update()



    def on_saturation_label(self, e):
        """
        Mise à jour du label du slider Saturation pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """

        self.saturation = e.control.value
        e.control.label = str(int(self.saturation))
        e.control.update()
        self._live_preview_tick()



    def on_saturation_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Saturation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """

        self.saturation = e.control.value
        self._render_preview()
        self.page.update()



    def on_exposure_label(self, e):
        """
        Mise à jour du label du slider Exposition pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """

        self.exposure = e.control.value
        e.control.label = str(int(self.exposure))
        e.control.update()
        self._live_preview_tick()



    def on_exposure_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Exposition.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """

        self.exposure = e.control.value
        self._render_preview()
        self.page.update()



    def on_hue_label(self, e):
        """Mise à jour du label du slider Teinte pendant le glissement."""
        self.hue = e.control.value
        e.control.label = str(int(self.hue))
        e.control.update()
        self._live_preview_tick()



    def on_hue_end(self, e):
        """Rendu complet au relâchement du slider Teinte."""
        self.hue = e.control.value
        self._render_preview()
        self.page.update()



    def on_wb_label(self, e):
        """Mise à jour du label du slider Balance des blancs pendant le glissement."""
        self.white_balance = e.control.value
        e.control.label = str(int(self.white_balance))
        e.control.update()
        self._live_preview_tick()



    def on_wb_end(self, e):
        """Rendu complet au relâchement du slider Balance des blancs."""
        self.white_balance = e.control.value
        self._render_preview()
        self.page.update()



    def reset_shadows(self, e):
        """
        Réinitialise simultanément les sliders Ombres et Hautes Lumières à 0.

        Remet à jour les valeurs internes, les labels affichés et les
        valeurs des widgets Flet, puis regénère la prévisualisation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton de réinitialisation (non utilisé directement).
        """

        self.shadows = 0.0
        self.shadows_slider.value = 0.0
        self.shadows_slider.label = "0"
        self.shadows_slider.update()
        self.highlights = 0.0
        self.highlights_slider.value = 0.0
        self.highlights_slider.label = "0"
        self.highlights_slider.update()
        self._render_preview()
        self.page.update()
        self._set_status("Ombres et Hautes Lumières remises à 0")



    def reset_adjustments(self, e):
        """Remet tous les réglages à zéro (bouton « Tout à 0 »)."""

        self.contrast = 0.0
        self.contrast_slider.value = 0.0
        self.contrast_slider.label = "0"
        self.contrast_slider.update()
        self.saturation = 0.0
        self.saturation_slider.value = 0.0
        self.saturation_slider.label = "0"
        self.saturation_slider.update()
        self.exposure = 0.0
        self.exposure_slider.value = 0.0
        self.exposure_slider.label = "0"
        self.exposure_slider.update()
        self.shadows = 0.0
        self.shadows_slider.value = 0.0
        self.shadows_slider.label = "0"
        self.shadows_slider.update()
        self.highlights = 0.0
        self.highlights_slider.value = 0.0
        self.highlights_slider.label = "0"
        self.highlights_slider.update()
        self.whites = 0.0
        self.whites_slider.value = 0.0
        self.whites_slider.label = "0"
        self.whites_slider.update()
        self.blacks = 0.0
        self.blacks_slider.value = 0.0
        self.blacks_slider.label = "0"
        self.blacks_slider.update()
        self.hue = 0.0
        self.hue_slider.value = 0.0
        self.hue_slider.label = "0"
        self.hue_slider.update()
        self.white_balance = 0.0
        self.white_balance_slider.value = 0.0
        self.white_balance_slider.label = "0"
        self.white_balance_slider.update()
        self._render_preview()
        self.page.update()
        self._set_status("Tous les réglages remis à 0")



    def reset_to_defaults(self, e):
        """Restaure les réglages à leurs valeurs par défaut (tels qu'au démarrage)."""

        self.contrast = float(CONSTANTS.RECADRAGE_DEFAULT_CONTRAST)
        self.contrast_slider.value = self.contrast
        self.contrast_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_CONTRAST)
        self.contrast_slider.update()
        self.saturation = float(CONSTANTS.RECADRAGE_DEFAULT_SATURATION)
        self.saturation_slider.value = self.saturation
        self.saturation_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_SATURATION)
        self.saturation_slider.update()
        self.exposure = float(CONSTANTS.RECADRAGE_DEFAULT_EXPOSURE)
        self.exposure_slider.value = self.exposure
        self.exposure_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_EXPOSURE)
        self.exposure_slider.update()
        self.shadows = float(CONSTANTS.RECADRAGE_DEFAULT_SHADOWS)
        self.shadows_slider.value = self.shadows
        self.shadows_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_SHADOWS)
        self.shadows_slider.update()
        self.highlights = float(CONSTANTS.RECADRAGE_DEFAULT_HIGHLIGHTS)
        self.highlights_slider.value = self.highlights
        self.highlights_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_HIGHLIGHTS)
        self.highlights_slider.update()
        # Blancs/Noirs : pas de valeur par défaut CONSTANTS, neutre = 0
        self.whites = 0.0
        self.whites_slider.value = 0.0
        self.whites_slider.label = "0"
        self.whites_slider.update()
        self.blacks = 0.0
        self.blacks_slider.value = 0.0
        self.blacks_slider.label = "0"
        self.blacks_slider.update()
        self.hue = float(CONSTANTS.RECADRAGE_DEFAULT_HUE)
        self.hue_slider.value = self.hue
        self.hue_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_HUE)
        self.hue_slider.update()
        self.white_balance = float(CONSTANTS.RECADRAGE_DEFAULT_WHITE_BALANCE)
        self.white_balance_slider.value = self.white_balance
        self.white_balance_slider.label = str(CONSTANTS.RECADRAGE_DEFAULT_WHITE_BALANCE)
        self.white_balance_slider.update()
        self._render_preview()
        self.page.update()
        self._set_status("Réglages par défaut restaurés")

    # ================================================================ #
    #                  FORMAT & ORIENTATION                           #
    # ================================================================ #
    def change_ratio(self, e=None):
        """
        Change le format d'impression actif et met à jour l'interface.

        Déclenché par le RadioGroup de sélection du format. Cette méthode :
          1. Met à jour `current_format` et `current_format_label`.
          2. Affiche / masque les switches de bordure et planches spéciales
             (13x15, 20x24, 13x10, Polaroid, ID X2, ID X4, réseau) selon
             le format choisi.
          3. Recalcule la taille du canevas.
          4. Recharge l'image courante en préservant l'orientation.

        Parameters
        ----------
        e : ft.ControlEvent or None
            Événement du RadioGroup ; `e.control.value` = clé du dict FORMATS.
        """

        if e.control.value == _CUSTOM_KEY:
            self.current_format_label = _CUSTOM_KEY
            # Lire les champs si déjà initialisés
            try:
                w = float((self.custom_w_field.value or "").strip())
                h = float((self.custom_h_field.value or "").strip())
                if w > 0 and h > 0:
                    if getattr(self, 'custom_unit', 'mm') == 'px':
                        w = w * 25.4 / DPI
                        h = h * 25.4 / DPI
                    self.current_format = (w, h)
            except (ValueError, AttributeError):
                self.current_format = self.custom_format
            # Masquer tous les switches spéciaux
            for sw in [
                self.border_switch_polaroid, self.border_switch_ID2,
                self.border_switch_ID4, self.id4_10x20_switch,
                self.network_switch,
            ]:
                sw.visible = False
            if self.custom_panel is not None:
                self.custom_panel.visible = True
            self.update_canvas_size()
            if self.image_paths:
                self.load_image(preserve_orientation=True)
            return

        if self.custom_panel is not None:
            self.custom_panel.visible = True
        self.current_format = FORMATS[e.control.value]
        self.custom_format = self.current_format
        try:
            self.current_format_label = e.control.value
        except Exception:
            pass
        if "10x10" in self.current_format_label:
            self.border_switch_polaroid.visible = True
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
            self.id4_10x20_switch.visible = False
        elif "ID" in self.current_format_label:
            self.border_switch_ID2.visible = True
            self.border_switch_ID4.visible = True
            self.id4_10x20_switch.visible = self.border_id4
            self.network_switch.visible = True
            self.sharpen_switch.value = True
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        else:
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
            self.id4_10x20_switch.visible = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)



    def toggle_orientation(self, e):
        """
        Bascule l'orientation du canevas entre portrait et paysage.

        Inverse `canvas_is_portrait`, recalcule les dimensions du canevas
        et recharge l'image courante. Met à jour la visibilité des switches
        selon le format actif.

        Raccourci clavier : Cmd+Backspace (macOS) / Suppr (Windows, Linux).

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton ou clavier).
        """

        self.canvas_is_portrait = not self.canvas_is_portrait
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

        self.border_switch_polaroid.visible = True if "10x10" in self.current_format_label else False
        self.border_switch_ID2.visible = True if "ID" in self.current_format_label else False
        self.border_switch_ID4.visible = True if "ID" in self.current_format_label else False
        self.id4_10x20_switch.visible = True if "ID" in self.current_format_label and self.border_id4 else False
        self.network_switch.visible = True if "ID" in self.current_format_label else False



    # ================================================================ #
    #                  FORMATS MULTIPLES & EXEMPLAIRES                 #
    # ================================================================ #
    def increment_copies(self, e):
        """
        Incrémente le compteur d'exemplaires (à l'infini).

        Chaque exemplaire produit un fichier supplémentaire lors de
        l'export (préfixe ``NX_`` dans le nom du fichier où N est le
        nombre d'exemplaires).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « + ».
        """

        self.copies_count += 1
        self.copies_text.value = str(self.copies_count)
        self.page.update()



    def decrement_copies(self, e):
        """
        Décrémente le compteur d'exemplaires (minimum 1).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « − ».
        """

        if self.copies_count > 1:
            self.copies_count -= 1
        self.copies_text.value = str(self.copies_count)
        self.page.update()



    def add_extra_format(self, e):
        """
        Enregistre un snapshot du cadrage courant dans la liste des formats
        multiples (`extra_formats`).

        Un snapshot est un dictionnaire qui capture l'état complet de la
        vue à cet instant : format, orientation, dimensions du canevas,
        base_scale, scale, offsets, rotation, réglages actifs (N&B, netteté,
        ombres, hautes lumières, contraste, saturation, exposition, etc.).

        Après l'ajout :
          - L'affichage de la liste des formats est mis à jour.
          - Le compteur d'exemplaires est remis à 1.
          - Tous les filtres (N&B, ombres, hautes lumières, contraste,
            saturation, exposition) sont remis à zéro pour préparer le
            prochain cadrage.

        À la validation (`validate_and_next`), tous les snapshots de
        `extra_formats` seront exportés en plus du cadrage principal.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Ajouter le format courant ».
        """

        label = self.current_format_label
        dims = self.current_format
        is_portrait = self.canvas_is_portrait
        snapshot = {
            "label": label,
            "dims": dims,
            "is_portrait": is_portrait,
            "canvas_w": self.canvas_w,
            "canvas_h": self.canvas_h,
            "base_scale": self.base_scale,
            "scale": self.scale,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "rotation": self.rotation,
            "copies": self.copies_count,
            "is_bw": self.is_bw,
            "is_sharpen": self.is_sharpen,
            "enhance_toggle": False,
            "fit_in": self.is_fit_in,
            "shadows": self.shadows,
            "highlights": self.highlights,
            "whites": getattr(self, 'whites', 0.0),
            "blacks": getattr(self, 'blacks', 0.0),
            "contrast": self.contrast,
            "saturation": self.saturation,
            "exposure": self.exposure,
            "hue": self.hue,
            "white_balance": self.white_balance,
            "rembg_active": self.rembg_btn.selected,
            "crop_mode": getattr(self, 'crop_mode', 'resolution'),
        }
        self.extra_formats.append(snapshot)
        self._update_extra_formats_display()
        # Remettre uniquement le compteur d'exemplaires à 1 pour le prochain format
        self.copies_count = 1
        self.copies_text.value = "1"
        self.page.update()



    def clear_extra_formats(self, e):
        """
        Vide la liste des formats multiples (extra_formats).

        Met à jour l'affichage de la liste et rafraîchit la page.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Vider la liste ».
        """

        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.page.update()



    def _update_extra_formats_display(self):
        """
        Met à jour le texte récapitulatif des formats multiples.

        Pour chaque snapshot de `extra_formats`, génère une chaîne courte
        du type ``2X 10x15 P 2en1 N&B S+20 HL-10 C+5 Sat+30 E+15``
        indiquant le nombre d'exemplaires, le format, l'orientation, et les
        réglages non nuls actifs. Les snapshots sont joints par « + ».

        Met à jour `extra_formats_display.value` (affiché dans l'UI).
        Si la liste est vide, affiche « — ».
        """

        if self.extra_formats:
            parts = []
            for s in self.extra_formats:
                lbl = s["label"].split()[0]
                copies = s.get("copies", 1)
                parts.append(f"{copies}X {lbl}")
            self.extra_formats_display.value = " + ".join(parts)
        else:
            self.extra_formats_display.value = "—"



    # ================================================================ #
    #                            ACTIONS                               #
    # ================================================================ #
    # ================================================================ #
    #            EXPORT EN ARRIÈRE-PLAN (file FIFO, 1 thread)          #
    # ================================================================ #
    def _ensure_export_worker(self):
        if self._export_thread is not None:
            return
        self._export_queue = queue.Queue()
        self._export_thread = threading.Thread(
            target=self._export_worker_loop, daemon=True)
        self._export_thread.start()

    def _export_worker_loop(self):
        while True:
            job = self._export_queue.get()
            try:
                self._export_job_run(job)
            except Exception as exc:
                self._status_from_thread(f"[ERREUR] Export : {exc}")
            finally:
                job["done"].set()
                self._export_queue.task_done()

    def _status_from_thread(self, message):
        """_set_status depuis le thread d'export : les contrôles Flet se
        mettent à jour via la boucle d'événements (page.run_task)."""
        async def _apply():
            self._set_status(message)
        try:
            self.page.run_task(_apply)
        except Exception:
            pass

    def _snapshot_export_state(self):
        """Copie de tout l'état nécessaire à l'export : le worker ne lit
        JAMAIS self.* pendant son calcul (l'UI est déjà passée à l'image
        suivante). `image` est partagée SANS copie : elle n'est jamais
        mutée en place (load_image / rembg en créent une nouvelle)."""
        return {
            "image": self.current_pil_image,
            "rembg_original": self._rembg_original,
            "icc_profile": getattr(self, 'icc_profile', None),
            "source_exif": getattr(self, 'source_exif', None),
            "source_path": self.image_paths[self.current_index],
            "index": self.current_index,
            "source_folder": self.source_folder,
            "crop_mode": getattr(self, 'crop_mode', 'resolution'),
            "is_portrait": self.canvas_is_portrait,
            "format_dims": self.current_format,
            "format_label": self.current_format_label,
            "canvas_w": self.canvas_w, "canvas_h": self.canvas_h,
            "base_scale": self.base_scale, "scale": self.scale,
            "offset_x": self.offset_x, "offset_y": self.offset_y,
            "rotation": self.rotation,
            "display_w": self.display_w, "display_h": self.display_h,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "is_bw": self.is_bw, "is_fit_in": self.is_fit_in,
            "is_sharpen": self.is_sharpen,
            "white_border": self.white_border,
            "contrast": self.contrast, "saturation": self.saturation,
            "exposure": self.exposure, "hue": self.hue,
            "white_balance": self.white_balance,
            "shadows": self.shadows, "highlights": self.highlights,
            "whites": getattr(self, 'whites', 0.0),
            "blacks": getattr(self, 'blacks', 0.0),
            "rembg_erosion_pct": getattr(self, 'rembg_erosion_pct', 0.0),
            "rembg_feather_pct": getattr(self, 'rembg_feather_pct', 0.0),
            "rembg_bg_mode": getattr(self, 'rembg_bg_mode', 0),
            "border_polaroid": self.border_polaroid,
            "border_id2": self.border_id2,
            "border_id4": self.border_id4,
            "id4_10x20": self.id4_10x20,
            "save_to_network": self.save_to_network,
            "copies_count": self.copies_count,
            "extra_formats": [dict(s) for s in self.extra_formats],
        }

    @staticmethod
    def _job_crop(job, target_w_px, target_h_px, *, canvas_w, canvas_h,
                  base_scale, offset_x, offset_y, scale, rotation,
                  is_bw, source_image=None):
        """Recadrage depuis les valeurs du job (équivalent de
        _compute_crop_with_canvas, sans lire ni muter self)."""
        view = image_ops.CropView(
            canvas_w=canvas_w, canvas_h=canvas_h, base_scale=base_scale,
            offset_x=offset_x, offset_y=offset_y, scale=scale,
            rotation=rotation,
            original_width=job["original_width"],
            original_height=job["original_height"],
            display_w=job["display_w"], display_h=job["display_h"],
        )
        return image_ops.compute_crop_with_canvas(
            source_image if source_image is not None else job["image"],
            target_w_px, target_h_px, view, is_bw=is_bw,
            rembg_erosion_pct=job["rembg_erosion_pct"],
            rembg_feather_pct=job["rembg_feather_pct"],
            rembg_bg_mode=job["rembg_bg_mode"],
            rembg_original=job["rembg_original"],
        )

    @staticmethod
    def _job_fit_in(job, target_w_px, target_h_px, *, is_bw,
                    source_image=None):
        """Fit-in depuis les valeurs du job (équivalent de
        _compute_fit_in, sans lire ni muter self)."""
        return image_ops.compute_fit_in(
            source_image if source_image is not None else job["image"],
            target_w_px, target_h_px,
            job["original_width"], job["original_height"], is_bw=is_bw,
            rembg_erosion_pct=job["rembg_erosion_pct"],
            rembg_feather_pct=job["rembg_feather_pct"],
            rembg_bg_mode=job["rembg_bg_mode"],
            rembg_original=job["rembg_original"],
        )

    def _export_job_run(self, job):
        """Calcule et enregistre tous les exports d'un job (cadrage
        principal + formats multiples) — corps de l'ancien
        validate_and_next, exécuté sur le thread d'export dans l'ordre
        des validations. Ne lit self.* que pour l'état PROPRE au worker
        (_id4_10x20_pending / _id4_10x20_seq)."""
        used_paths = set()

        def unique_path(path):
            """Chemin unique dans la session d'export de CE job (suffixe
            _2, _3… si déjà attribué)."""
            if path not in used_paths:
                used_paths.add(path)
                return path
            file_base, file_extension = os.path.splitext(path)
            suffix_number = 2
            while True:
                candidate_path = f"{file_base}_{suffix_number}{file_extension}"
                if candidate_path not in used_paths:
                    used_paths.add(candidate_path)
                    return candidate_path
                suffix_number += 1

        _crop_mode = job["crop_mode"]
        output_is_portrait = job["is_portrait"]
        format_width_mm, format_height_mm = job["format_dims"]

        # Dimensions de sortie selon le mode
        if _crop_mode == 'ratio':
            _fw = format_width_mm if output_is_portrait else format_height_mm
            _fh = format_height_mm if output_is_portrait else format_width_mm
            _k = min(job["original_width"] / _fw,
                     job["original_height"] / _fh)
            output_width_px = max(1, math.floor(_fw * _k))
            output_height_px = max(1, math.floor(_fh * _k))
        elif _crop_mode == 'none':
            output_width_px = job["original_width"]
            output_height_px = job["original_height"]
        elif output_is_portrait:
            output_width_px = mm_to_pixels(format_width_mm)
            output_height_px = mm_to_pixels(format_height_mm)
        else:
            output_width_px = mm_to_pixels(format_height_mm)
            output_height_px = mm_to_pixels(format_width_mm)

        # Image de sortie selon le mode
        if _crop_mode == 'none':
            _src = job["image"]
            if _src.mode == 'RGBA':
                if job["rembg_erosion_pct"] > 0:
                    _r = max(1, round(min(_src.size)
                                      * job["rembg_erosion_pct"] / 100))
                    _src = _erode_alpha(_src.copy(), _r)
                if job["rembg_feather_pct"] > 0:
                    _f = max(1, round(min(_src.size)
                                      * job["rembg_feather_pct"] / 100))
                    _src = _feather_alpha(_src.copy(), _f)
                _bg_m = job["rembg_bg_mode"]
                if _bg_m == 2 and job["rembg_original"] is not None:
                    _bg = job["rembg_original"].convert('RGB').filter(
                        ImageFilter.GaussianBlur(radius=64)).convert('RGBA')
                else:
                    _c = ((230, 230, 230, 255) if _bg_m == 1
                          else (255, 255, 255, 255))
                    _bg = Image.new('RGBA', _src.size, _c)
                output_image = Image.alpha_composite(_bg, _src).convert('RGB')
            else:
                output_image = _src.convert('RGB')
            if job["is_bw"]:
                output_image = output_image.convert('L').convert('RGB')
        elif job["is_fit_in"]:
            output_image = self._job_fit_in(
                job, output_width_px, output_height_px, is_bw=job["is_bw"])
        else:
            output_image = self._job_crop(
                job, output_width_px, output_height_px,
                canvas_w=job["canvas_w"], canvas_h=job["canvas_h"],
                base_scale=job["base_scale"], offset_x=job["offset_x"],
                offset_y=job["offset_y"], scale=job["scale"],
                rotation=job["rotation"], is_bw=job["is_bw"])

        source_filename = os.path.basename(job["source_path"])
        base_filename, _ = os.path.splitext(source_filename)
        base_filename = re.sub(r'^\d+X_', '', base_filename)
        if _crop_mode == 'none':
            format_short_name = 'Retouche'
        elif _crop_mode == 'ratio':
            format_short_name = 'Ratio'
        else:
            format_short_name = job["format_label"].split()[0]
        copies_count_prefix = f"{job['copies_count']}X_"
        output_filename = copies_count_prefix + base_filename + ".jpg"

        # Appliquer les réglages couleur sur la photo AVANT l'ajout des
        # bordures/marges, pour que les zones blanches (13x15, Polaroid,
        # ID grille…) restent blanc pur.
        output_image = image_ops.apply_adjustments(
            output_image, exposure=job["exposure"],
            contrast=job["contrast"], saturation=job["saturation"],
            hue=job["hue"], white_balance=job["white_balance"])
        if job["shadows"] != 0:
            output_image = image_ops.apply_shadows(output_image,
                                                    job["shadows"])
        if job["highlights"] != 0:
            output_image = image_ops.apply_highlights(output_image,
                                                       job["highlights"])
        if job["whites"] != 0:
            output_image = image_ops.apply_whites(output_image,
                                                   job["whites"])
        if job["blacks"] != 0:
            output_image = image_ops.apply_blacks(output_image,
                                                   job["blacks"])

        if _crop_mode != 'none' and job["white_border"]:
            border_px = mm_to_pixels(5)
            inner_w = output_width_px - 2 * border_px
            inner_h = output_height_px - 2 * border_px
            ratio = min(inner_w / output_image.width,
                        inner_h / output_image.height)
            new_w = round(output_image.width * ratio)
            new_h = round(output_image.height * ratio)
            fitted = output_image.resize((new_w, new_h),
                                         Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (output_width_px, output_height_px),
                               "white")
            canvas.paste(fitted, ((output_width_px - new_w) // 2,
                                  (output_height_px - new_h) // 2))
            output_image = canvas

        if job["border_polaroid"] and "10x10" in format_short_name:
            POLAROID_WIDTH_PX = mm_to_pixels(127)
            POLAROID_HEIGHT_PX = mm_to_pixels(152)
            framed_image = Image.new(
                "RGB", (POLAROID_WIDTH_PX, POLAROID_HEIGHT_PX), "white")
            paste_offset_x = (POLAROID_WIDTH_PX - output_image.width) // 2
            paste_offset_y = paste_offset_x
            framed_image.paste(output_image, (paste_offset_x, paste_offset_y))
            output_image = framed_image
            format_short_name = "Polaroid"

        if (_crop_mode != 'none' and job["border_id4"]
                and "ID" in job["format_label"]):
            SPACING_PX = mm_to_pixels(5)
            id_photo = output_image
            if id_photo.height > id_photo.width:
                id_photo = id_photo.rotate(90, expand=True)
            id4_10x20_seq_filename = None
            if job["id4_10x20"]:
                if job.get("id4_hold"):
                    # 1ère identité de la paire : mise en attente, la 2e
                    # ira à droite du même feuillet. Décision prise côté
                    # UI (validate_and_next) — rien n'est écrit ici.
                    self._id4_10x20_pending = id_photo
                    self._status_from_thread(
                        "Identité mise en attente, recadrez la suivante...")
                    return

                # Format 10x20 : une identité par moitié (grille 2x2 = 4
                # copies chacune). S'il n'y a qu'une identité isolée en
                # fin de batch, l'autre moitié reste blanche (comme avant).
                SHEET_WIDTH_PX = mm_to_pixels(102)
                SHEET_HEIGHT_PX = mm_to_pixels(203)
                sheet_image = Image.new(
                    "RGB", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), "white")
                half_height = SHEET_HEIGHT_PX // 2
                total_width = id_photo.width * 2 + SPACING_PX
                total_height = id_photo.height * 2 + SPACING_PX
                start_x = (SHEET_WIDTH_PX - total_width) // 2
                bottom_y = half_height + (half_height - total_height) // 2
                top_y = (half_height - total_height) // 2

                def _paste_id4_block(photo, y_offset):
                    for row in range(2):
                        for col in range(2):
                            paste_x = start_x + col * (photo.width
                                                       + SPACING_PX)
                            paste_y = y_offset + row * (photo.height
                                                        + SPACING_PX)
                            sheet_image.paste(photo, (paste_x, paste_y))

                first_half_y = (bottom_y if ID_X4_10x20_PHOTOS_BOTTOM
                                else top_y)
                second_half_y = (top_y if ID_X4_10x20_PHOTOS_BOTTOM
                                 else bottom_y)
                if self._id4_10x20_pending is not None:
                    first_photo = self._id4_10x20_pending
                    self._id4_10x20_pending = None
                    _paste_id4_block(first_photo, first_half_y)
                    _paste_id4_block(id_photo, second_half_y)
                else:
                    # dernière identité isolée du batch : une seule
                    # moitié, 4 copies comme avant
                    _paste_id4_block(id_photo, first_half_y)
                # Numérotation séquentielle des feuillets sauvegardés
                # (ID_01, ID_02, ...), indépendante de l'index des photos
                # sources consommées par paire.
                self._id4_10x20_seq += 1
                id4_10x20_seq_filename = (
                    f"{copies_count_prefix}ID {self._id4_10x20_seq:02}.jpg")
                format_short_name = "ID_X4_10x20"
            else:
                SHEET_WIDTH_PX = mm_to_pixels(127)
                SHEET_HEIGHT_PX = mm_to_pixels(102)
                sheet_image = Image.new(
                    "RGB", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), "white")
                total_width = id_photo.width * 2 + SPACING_PX
                total_height = id_photo.height * 2 + SPACING_PX
                start_x = (SHEET_WIDTH_PX - total_width) // 2
                start_y = (SHEET_HEIGHT_PX - total_height) // 2
                for row in range(2):
                    for col in range(2):
                        paste_x = start_x + col * (id_photo.width
                                                   + SPACING_PX)
                        paste_y = start_y + row * (id_photo.height
                                                   + SPACING_PX)
                        sheet_image.paste(id_photo, (paste_x, paste_y))
                format_short_name = "ID_X4"
            output_image = sheet_image
            output_filename = (id4_10x20_seq_filename
                               or f"{copies_count_prefix}ID "
                                  f"{job['index'] + 1:02}.jpg")

        elif (_crop_mode != 'none' and job["border_id2"]
                and "ID" in job["format_label"]):
            SHEET_WIDTH_PX = mm_to_pixels(102)
            SHEET_HEIGHT_PX = mm_to_pixels(102)
            SPACING_PX = mm_to_pixels(5)
            sheet_image = Image.new(
                "RGB", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), "white")
            id_photo = output_image
            if id_photo.width > id_photo.height:
                id_photo = id_photo.rotate(90, expand=True)
            paste_offset_x = (SHEET_WIDTH_PX - id_photo.width) // 2
            first_paste_y = SPACING_PX
            sheet_image.paste(id_photo, (paste_offset_x, first_paste_y))
            second_paste_y = SHEET_HEIGHT_PX - id_photo.height - SPACING_PX
            sheet_image.paste(id_photo, (paste_offset_x, second_paste_y))
            output_image = sheet_image
            format_short_name = "ID_X2"
            output_filename = (f"{copies_count_prefix}ID "
                               f"{job['index'] + 1:02}.jpg")

        if (format_short_name in ("ID_X4", "ID_X4_10x20")
                and job["save_to_network"]):
            if platform.system() == "Windows":
                output_directory = "\\\\Diskstation\\travaux en cours\\z2026"
            else:
                _travaux_primary = "/Volumes/TRAVAUX EN COURS/Z2026"
                _travaux_secondary = "/Volumes/TRAVAUX EN COURS-1/Z2026"
                if os.path.isdir(_travaux_primary):
                    output_directory = _travaux_primary
                elif os.path.isdir(_travaux_secondary):
                    output_directory = _travaux_secondary
                else:
                    output_directory = _travaux_primary  # sera créé par makedirs ou plantera explicitement
        else:
            output_directory = os.path.join(job["source_folder"],
                                            format_short_name)

        if job["is_sharpen"]:
            output_image = output_image.filter(
                ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            output_image = output_image.filter(
                ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))

        # Conversion vers sRGB (correction colorimétrique)
        output_image = convert_to_srgb(output_image, job["icc_profile"])

        _exif_bytes = job["source_exif"]
        jpeg_save_options = {"quality": 100, "format": "JPEG",
                             "dpi": (DPI, DPI), "icc_profile": _SRGB_ICC}
        if _exif_bytes:
            jpeg_save_options["exif"] = _exif_bytes

        saved_file_path = None
        if not job["extra_formats"]:
            os.makedirs(output_directory, exist_ok=True)
            saved_file_path = unique_path(
                os.path.join(output_directory, output_filename))
            output_image.save(saved_file_path, **jpeg_save_options)
            job["saved"].append(saved_file_path)

        # Exports formats supplémentaires (ou tous les exports si
        # extra_formats non vide)
        for snapshot_index, snapshot in enumerate(job["extra_formats"],
                                                  start=1):
            snapshot_format_label = snapshot["label"]
            snapshot_format_short_name = snapshot_format_label.split()[0]
            snapshot_is_portrait = snapshot["is_portrait"]

            snapshot_width_mm, snapshot_height_mm = snapshot["dims"]
            _snap_mode = snapshot.get("crop_mode", "resolution")
            if _snap_mode == "ratio":
                _fw = (snapshot_width_mm if snapshot_is_portrait
                       else snapshot_height_mm)
                _fh = (snapshot_height_mm if snapshot_is_portrait
                       else snapshot_width_mm)
                _k = min(job["original_width"] / _fw,
                         job["original_height"] / _fh)
                snapshot_output_width_px = max(1, math.floor(_fw * _k))
                snapshot_output_height_px = max(1, math.floor(_fh * _k))
                snapshot_format_short_name = "Ratio"
            elif _snap_mode == "none":
                snapshot_output_width_px = job["original_width"]
                snapshot_output_height_px = job["original_height"]
                snapshot_format_short_name = "Retouche"
            elif snapshot_is_portrait:
                snapshot_output_width_px = mm_to_pixels(snapshot_width_mm)
                snapshot_output_height_px = mm_to_pixels(snapshot_height_mm)
            else:
                snapshot_output_width_px = mm_to_pixels(snapshot_height_mm)
                snapshot_output_height_px = mm_to_pixels(snapshot_width_mm)

            # Si rembg n'était pas actif lors du snapshot mais l'est
            # maintenant, utiliser l'image originale pour ce format.
            snapshot_source = None
            if (not snapshot.get("rembg_active", False)
                    and job["image"].mode == "RGBA"
                    and job["rembg_original"] is not None):
                snapshot_source = job["rembg_original"]

            if _snap_mode == "none":
                _ss = job["image"]
                if _ss.mode == 'RGBA':
                    _sb = Image.new('RGBA', _ss.size, (255, 255, 255, 255))
                    snapshot_output_image = Image.alpha_composite(
                        _sb, _ss).convert('RGB')
                else:
                    snapshot_output_image = _ss.convert('RGB')
                if snapshot.get("is_bw", False):
                    snapshot_output_image = snapshot_output_image.convert(
                        'L').convert('RGB')
            elif snapshot.get("fit_in", False):
                snapshot_output_image = self._job_fit_in(
                    job, snapshot_output_width_px,
                    snapshot_output_height_px,
                    is_bw=snapshot.get("is_bw", False),
                    source_image=snapshot_source)
            else:
                snapshot_output_image = self._job_crop(
                    job, snapshot_output_width_px,
                    snapshot_output_height_px,
                    canvas_w=snapshot["canvas_w"],
                    canvas_h=snapshot["canvas_h"],
                    base_scale=snapshot["base_scale"],
                    offset_x=snapshot["offset_x"],
                    offset_y=snapshot["offset_y"],
                    scale=snapshot["scale"],
                    rotation=snapshot["rotation"],
                    is_bw=snapshot.get("is_bw", False),
                    source_image=snapshot_source)

            # Réglages couleur du snapshot AVANT les bordures, via
            # image_ops directement (aucune mutation temporaire de self :
            # l'UI travaille déjà sur l'image suivante).
            snapshot_output_image = image_ops.apply_adjustments(
                snapshot_output_image,
                exposure=snapshot.get("exposure", 0),
                contrast=snapshot.get("contrast", 0),
                saturation=snapshot.get("saturation", 0),
                hue=snapshot.get("hue", 0),
                white_balance=snapshot.get("white_balance", 0))
            if snapshot.get("shadows", 0) != 0:
                snapshot_output_image = image_ops.apply_shadows(
                    snapshot_output_image, snapshot["shadows"])
            if snapshot.get("highlights", 0) != 0:
                snapshot_output_image = image_ops.apply_highlights(
                    snapshot_output_image, snapshot["highlights"])
            if snapshot.get("whites", 0) != 0:
                snapshot_output_image = image_ops.apply_whites(
                    snapshot_output_image, snapshot["whites"])
            if snapshot.get("blacks", 0) != 0:
                snapshot_output_image = image_ops.apply_blacks(
                    snapshot_output_image, snapshot["blacks"])

            snapshot_copies_count = snapshot.get("copies", 1)
            snapshot_copies_prefix = f"{snapshot_copies_count}X_"
            snapshot_output_filename = (snapshot_copies_prefix
                                        + base_filename
                                        + f"_{snapshot_index}.jpg")
            snapshot_output_directory = os.path.join(
                job["source_folder"], snapshot_format_short_name)
            os.makedirs(snapshot_output_directory, exist_ok=True)
            snapshot_saved_path = unique_path(os.path.join(
                snapshot_output_directory, snapshot_output_filename))

            if snapshot.get("is_sharpen", job["is_sharpen"]):
                snapshot_output_image = snapshot_output_image.filter(
                    ImageFilter.UnsharpMask(radius=4, percent=13,
                                            threshold=0))
                snapshot_output_image = snapshot_output_image.filter(
                    ImageFilter.UnsharpMask(radius=2, percent=21,
                                            threshold=0))

            # Conversion vers sRGB (correction colorimétrique)
            snapshot_output_image = convert_to_srgb(snapshot_output_image,
                                                    job["icc_profile"])

            snapshot_output_image.save(snapshot_saved_path,
                                       **jpeg_save_options)
            job["saved"].append(snapshot_saved_path)
            saved_file_path = snapshot_saved_path

        if saved_file_path:
            self._status_from_thread(
                f"[OK] {os.path.basename(saved_file_path)} enregistré !")

    def validate_and_next(self, e):
        """
        Fige l'état courant dans un job d'export et passe immédiatement à
        l'image suivante.

        Le calcul pleine résolution (recadrage 300 dpi, réglages, netteté,
        sRGB, JPEG qualité 100, formats multiples — cf. _export_job_run)
        s'exécute sur le thread d'export, dans l'ordre des validations :
        appuyer sur Entrée n'attend plus la fin de l'enregistrement
        (retour user : latence à chaque photo avec un client). go_previous
        attend/supprime le dernier job ; close_window attend la fin de la
        file avant de fermer.

        Raccourci clavier : Entrée.

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton « Valider & Suivant » ou clavier).
        """

        if not self.image_paths or self.current_index >= len(self.image_paths):
            self._set_status("Toutes les images ont été traitées.")
            return

        self._ensure_export_worker()
        job = self._snapshot_export_state()
        job["done"] = threading.Event()
        job["saved"] = []
        job["id4_hold"] = False
        # Décision d'appairage ID X4 10x20 prise ICI, en synchrone (le
        # worker n'a peut-être pas encore traité les jobs précédents) :
        # _id4_pair_waiting est le miroir UI de _id4_10x20_pending côté
        # worker — même parité, tenue au moment de la validation.
        if (job["crop_mode"] != 'none' and job["border_id4"]
                and "ID" in job["format_label"] and job["id4_10x20"]):
            has_next_image = self.current_index + 1 < len(self.image_paths)
            if not self._id4_pair_waiting and has_next_image:
                job["id4_hold"] = True
                self._id4_pair_waiting = True
            else:
                self._id4_pair_waiting = False
        self._export_jobs.append(job)
        self._export_queue.put(job)
        if not job["id4_hold"]:
            self._set_status("Enregistrement en arrière-plan…")

        if self.batch_mode:
            self.current_index += 1
            self.extra_formats.clear()
            self._update_extra_formats_display()
            self.copies_count = 1
            self.copies_text.value = "1"
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation=False)
                return
            self.batch_mode = False
            self.canvas_container.visible = False
            self.validate_button.visible = False
            self.previous_button.visible = False

            self._set_status("[OK] Toutes les images sont traitées !")
            self.page.update()
            asyncio.create_task(self.close_window())
            return
        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.copies_count = 1
        self.copies_text.value = "1"
        self.page.update()

    # ================================================================ #
    #                   IGNORER UNE IMAGE                             #
    # ================================================================ #
    def ignore_image(self, e):
        """
        Ignore l'image courante sans l'exporter et passe à la suivante.

        Réinitialise les formats multiples et le compteur d'exemplaires,
        puis charge l'image suivante. Si toutes les images ont été ignorées
        ou traitées, ferme la fenêtre.

        Raccourci clavier : Espace.

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton « Ignorer Image » ou espace clavier).
        """

        if not self.image_paths or self.current_index >= len(self.image_paths):
            self._set_status("Toutes les images ont été traitées.")
            asyncio.create_task(self.close_window())
            return

        self.current_index += 1
        self._last_saved_paths = []

        if self.current_index >= len(self.image_paths):
            self._set_status("Toutes les images ont été traitées.")
            asyncio.create_task(self.close_window())
            return

        self._set_status("Image ignorée.")
        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.copies_count = 1
        self.copies_text.value = "1"
        self.load_image(preserve_orientation=False)
        self.page.update()



    def go_previous(self, e):
        """Revient à l'image précédente et supprime les fichiers exportés
        lors du dernier validate — en attendant d'abord la fin de son job
        d'export s'il tourne encore (export en arrière-plan)."""
        if not self.image_paths or self.current_index <= 0:
            return
        last_job = self._export_jobs.pop() if self._export_jobs else None
        if last_job is not None and not last_job["done"].is_set():
            self._set_status("Annulation de l'export précédent…",
                             processing=True)
            last_job["done"].wait(timeout=60)
        dirs_to_check = set()
        for path in (last_job["saved"] if last_job else []):
            with contextlib.suppress(OSError):
                os.remove(path)
                dirs_to_check.add(os.path.dirname(path))
        for d in dirs_to_check:
            with contextlib.suppress(OSError):
                if not os.listdir(d):
                    os.rmdir(d)
        self._last_saved_paths = []
        self.current_index -= 1
        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.copies_count = 1
        self.copies_text.value = "1"
        self.load_image(preserve_orientation=False)



    async def close_window(self, e=None):
        """
        Ferme la fenêtre de l'application en toute sécurité.

        Utilise un verrou interne (`_closing`) pour éviter les appels
        multiples simultanés (double-validation rapide, fermeture système).

        Tente d'abord de masquer la fenêtre visuellement (`window.visible =
        False`) avant d'appeler `window.destroy()`, ce qui produit une
        fermeture plus fluide sur macOS et Windows.

        Parameters
        ----------
        e : optional
            Événement déclencheur (non utilisé). Peut être None.
        """

        if getattr(self, '_closing', False):
            return
        self._closing = True

        # Fenêtre masquée EN PREMIER : l'interface vide restait affichée
        # plusieurs secondes pendant la finalisation des exports (retour
        # user) — le process, lui, reste vivant jusqu'à la fin des
        # écritures ci-dessous.
        try:
            self.page.window.visible = False
            self.page.update()
        except Exception:
            pass

        # Attendre la fin des exports en cours : la file tourne sur un
        # thread daemon — détruire tout de suite tronquerait les derniers
        # fichiers en cours d'écriture.
        pending_jobs = [j for j in self._export_jobs
                        if not j["done"].is_set()]
        for pending_job in pending_jobs:
            try:
                await asyncio.to_thread(pending_job["done"].wait, 120)
            except Exception:
                pass

        # Nettoyer le dossier de cache de prévisualisation
        try:
            if os.path.isdir(self._preview_tmp_dir):
                shutil.rmtree(self._preview_tmp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            await self.page.window.destroy()
        except Exception:
            pass



#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    """
    Point d'entrée de l'application Flet.

    Cette fonction est passée à `ft.run(main)` et reçoit en paramètre
    la page Flet créée par le runtime.

    Elle réalise :
      1. Configuration de la fenêtre (titre, thème sombre, maximisée,
         couleur de fond).
      2. Instanciation de `PhotoCropper`.
      3. Attachement du gestionnaire de clavier (`on_keyboard_event`) :
           - Entrée    → validate_and_next
           - Cmd+Backspace (macOS) / Suppr → toggle_orientation
           - Espace    → ignore_image
      4. Construction de la mise en page complète :
           - Panneau gauche  : sliders de réglages (rotation, exposition,
             hautes lumières, ombres, contraste, saturation, netteté).
           - Zone centrale   : barre d'opérations (exemplaires, formats
             multiples, N&B, Fit-in, orientation) + canvas interactif.
           - Panneau droit   : sélecteur de format et boutons d'action.
           - Overlay bas-droit : texte de statut.
      5. Gestionnaire de redimensionnement de la fenêtre.
      6. Lancement différé du batch (0,3 s) via `asyncio.create_task`
         pour laisser le temps à la fenêtre de s'initialiser complètement.

    Parameters
    ----------
    page : ft.Page
        Page Flet fournie par le runtime.
    """

    page.title = "Recadrage Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True
    page.bgcolor = GREY
    page.run_task(page.window.to_front)

    app = PhotoCropper(page)



    def on_key(event: ft.KeyboardEvent):
        """
        Gestionnaire global des raccourcis clavier de la page.

        Raccourcis pris en charge :
          - ``Entrée``    → :meth:`validate_and_next`  – valider et passer
            à l'image suivante.
          - ``Cmd+Backspace`` (macOS) / ``Suppr`` → :meth:`toggle_orientation` – basculer
            portrait / paysage.
          - ``Espace``    → :meth:`ignore_image`       – ignorer l'image
            courante sans l'exporter.

        Parameters
        ----------
        event : ft.KeyboardEvent
            Événement clavier Flet exposant ``event.key`` (nom textuel
            de la touche, p. ex. ``"Enter"``, ``"Backspace"``, ``" "``).
        """

        if event.key == "Tab":
            app._scroll_rotates = not app._scroll_rotates
            app._update_shift_badge()
        elif event.key == "Enter":
            app.validate_and_next(event)
        elif event.key in ("Backspace", "Delete"):
            app.toggle_orientation(event)
        elif event.key == "Escape":
            app.ignore_image(event)
        elif event.key in ("+", "=", "Add") and not event.meta and not event.ctrl:
            if app.image_paths and hasattr(app, 'original_width'):
                app.scale = min(10.0, app.scale * 1.05)
                app.zoom_slider.value = min(app.scale, app.zoom_slider.max)
                app.zoom_slider.label = f"{app.scale:.2f}×"
                app.zoom_slider.update()
                app._clamp_offsets()
                app._update_transform()
        elif event.key in ("-", "Subtract") and not event.meta and not event.ctrl:
            if app.image_paths and hasattr(app, 'original_width'):
                app.scale = max(1.0, app.scale / 1.05)
                app.zoom_slider.value = min(app.scale, app.zoom_slider.max)
                app.zoom_slider.label = f"{app.scale:.2f}×"
                app.zoom_slider.update()
                app._clamp_offsets()
                app._update_transform()
        elif event.key == "0" and not event.meta and not event.ctrl:
            app.reset_zoom(event)
    page.on_keyboard_event = on_key

    # ── Champs de format personnalisé ────────────────────────────────
    def _on_custom_dim_change(e):
        """Met à jour current_format quand l'utilisateur modifie les champs personnalisés."""
        if app.current_format_label != _CUSTOM_KEY:
            return
        try:
            w = float((app.custom_w_field.value or "").strip())
            h = float((app.custom_h_field.value or "").strip())
            if w > 0 and h > 0:
                if getattr(app, 'custom_unit', 'mm') == 'px':
                    w = w * 25.4 / DPI
                    h = h * 25.4 / DPI
                app.current_format = (w, h)
                app.update_canvas_size()
                if app.image_paths:
                    app.load_image(preserve_orientation=True)
        except ValueError:
            pass

    app.custom_w_field = ft.TextField(
        label="Largeur (mm)", value="100", expand=True,
        text_size=12, keyboard_type=ft.KeyboardType.NUMBER,
        border=ft.InputBorder.OUTLINE, border_color=BLUE, focused_border_color=BLUE, bgcolor=BG,
        disabled=True,
        on_submit=_on_custom_dim_change, on_blur=_on_custom_dim_change,
    )
    app.custom_h_field = ft.TextField(
        label="Hauteur (mm)", value="100", expand=True,
        text_size=12, keyboard_type=ft.KeyboardType.NUMBER,
        border=ft.InputBorder.OUTLINE, border_color=BLUE, focused_border_color=BLUE, bgcolor=BG,
        disabled=True,
        on_submit=_on_custom_dim_change, on_blur=_on_custom_dim_change,
    )
    app.custom_fields_row = ft.Row(
        [app.custom_w_field, app.custom_h_field],
        spacing=6,
        alignment=ft.MainAxisAlignment.CENTER,
    )

    app.custom_unit = "mm"

    def _on_unit_change(e):
        new_unit = e.control.value
        try:
            w = float((app.custom_w_field.value or "").strip())
            h = float((app.custom_h_field.value or "").strip())
            if w > 0 and h > 0:
                if app.custom_unit == "mm" and new_unit == "px":
                    w = round(w / 25.4 * DPI)
                    h = round(h / 25.4 * DPI)
                elif app.custom_unit == "px" and new_unit == "mm":
                    w = round(w * 25.4 / DPI, 1)
                    h = round(h * 25.4 / DPI, 1)
                app.custom_w_field.value = str(w)
                app.custom_h_field.value = str(h)
        except ValueError:
            pass
        app.custom_unit = new_unit
        app.custom_w_field.label = f"Largeur ({new_unit})"
        app.custom_h_field.label = f"Hauteur ({new_unit})"
        page.update()

    app.unit_dropdown = ft.Dropdown(
        value="mm",
        options=[ft.dropdown.Option("mm"), ft.dropdown.Option("px")],
        width=90,
        text_size=12,
        bgcolor=BG,
        border_color=BLUE,
        focused_border_color=BLUE,
        on_select=_on_unit_change,
        content_padding=ft.Padding.symmetric(horizontal=8, vertical=0),
        disabled=True,
    )

    app.custom_mode_switch = ft.Switch(
        label="Taille manuelle",
        value=False,
        active_color=BLUE,
    )

    def _apply_custom_mode(enabled: bool):
        app.custom_w_field.disabled = not enabled
        app.custom_h_field.disabled = not enabled
        app.unit_dropdown.disabled = not enabled
        app.format_radio_group.disabled = enabled
        if enabled:
            # Appliquer immédiatement les dimensions saisies en mode personnalisé
            app.change_ratio(type("Evt", (), {"control": type("Ctl", (), {"value": _CUSTOM_KEY})()})())
        else:
            # Retour au format standard actuellement sélectionné
            app.change_ratio(type("Evt", (), {"control": type("Ctl", (), {"value": app.format_radio_group.value})()})())
        _sync_custom_unit_for_crop_mode()
        page.update()

    def _on_custom_mode_toggle(e):
        _apply_custom_mode(bool(e.control.value))

    app.custom_mode_switch.on_change = _on_custom_mode_toggle

    # En mode Ratio, seule la PROPORTION largeur/hauteur compte (cf.
    # update_canvas_size : le format n'est jamais converti en pixels
    # imprimés) — proposer mm/px y suggère à tort une taille physique
    # réelle (retour user). On verrouille alors l'unité sur "%" ; le
    # mm/px choisi avant d'entrer en mode Ratio est restauré en sortie.
    def _sync_custom_unit_for_crop_mode():
        is_ratio = getattr(app, "crop_mode", "resolution") == "ratio"
        if is_ratio:
            if app.custom_unit != "%":
                app._unit_before_ratio = app.custom_unit
            app.custom_unit = "%"
            app.unit_dropdown.options = [ft.dropdown.Option("%")]
            app.unit_dropdown.value = "%"
            app.unit_dropdown.disabled = True
            app.custom_w_field.label = "Largeur (%)"
            app.custom_h_field.label = "Hauteur (%)"
        else:
            if app.custom_unit == "%":
                app.custom_unit = getattr(app, "_unit_before_ratio", "mm")
            app.unit_dropdown.options = [ft.dropdown.Option("mm"), ft.dropdown.Option("px")]
            app.unit_dropdown.value = app.custom_unit
            app.unit_dropdown.disabled = not app.custom_mode_switch.value
            app.custom_w_field.label = f"Largeur ({app.custom_unit})"
            app.custom_h_field.label = f"Hauteur ({app.custom_unit})"

    def _on_crop_mode_change_and_sync(e):
        app.on_crop_mode_change(e)
        _sync_custom_unit_for_crop_mode()
        page.update()

    app.format_radio_group = ft.RadioGroup(
        content=ft.Column(
            [ft.Radio(value=fmt, label=fmt, fill_color=BLUE) for fmt in FORMATS.keys()],
            scroll=ft.ScrollMode.AUTO,
        ),
        value="ID",
        on_change=app.change_ratio,
    )

    app.custom_panel = ft.Container(
        content=ft.Column([
            app.custom_mode_switch,
            ft.Container(content=app.custom_fields_row, margin=ft.Margin.only(top=8)),
            ft.Row(
                [ft.Text("Unité :", size=12, color=LIGHT_GREY), app.unit_dropdown],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
        ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        visible=True,
        border=ft.Border.all(1, BLUE),
        bgcolor=DARK,
        border_radius=8,
        padding=ft.Padding.symmetric(horizontal=10, vertical=10),
    )

    controls = ft.Column([
        ft.CupertinoSlidingSegmentedButton(
            selected_index=0,
            controls=[
                ft.Text("Résolution", size=12),
                ft.Text("Ratio", size=12),
                ft.Text("Aucun", size=12),
            ],
            on_change=_on_crop_mode_change_and_sync,
            padding=ft.Padding.symmetric(horizontal=4, vertical=4),
        ),
        ft.Container(
            # ── Panneau droite : Choix des dimensions des photos ──────────────────────
            content=ft.Column([
                ft.Text("Formats Photos", size=16, weight=ft.FontWeight.BOLD, color=WHITE),
                ft.Divider(height=4),
                app.format_radio_group,
            ], scroll=ft.ScrollMode.AUTO),
            height=CONSTANTS.RECADRAGE_FORMAT_LIST_HEIGHT,
            border=ft.Border.all(1, GREY),
            bgcolor=DARK,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=12),
        ),
        app.custom_panel,
        ft.Container(
            content=ft.Column([
                app.border_switch_polaroid,
                app.border_switch_ID2,
                app.border_switch_ID4,
                app.id4_10x20_switch,
                app.network_switch,
            ], spacing=0),
            padding=ft.Padding.only(bottom=8),
        ),
        ft.Divider(height=8, visible=app.show_histogram),
        ft.Text("Histogramme", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER, visible=app.show_histogram),
        app.histogram_image,
        ft.Divider(height=4, visible=app.show_histogram),
        app.validate_button,
        app.previous_button,
        app.ignore_button
    ], width=RIGHT_COL_WIDTH)

    page.add(
        ft.Stack([
            ft.Row([


                # ── Panneau gauche : réglages sliders ──────────────────────
                ft.Container(
                    content=ft.Column([
                        ft.Text("Réglages", size=16, weight=ft.FontWeight.BOLD, color=WHITE),
                        ft.Divider(height=4),


                        # ── Luminosité ────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("LUMINOSITÉ", size=10, color=YELLOW, weight=ft.FontWeight.BOLD),
                                ft.Text("Exposition", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.exposure_slider, on_double_tap=lambda e: app._reset_slider(app.exposure_slider, 'exposure', 0.0, '0')),
                                ft.Text("Hautes lumières", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.highlights_slider, on_double_tap=lambda e: app._reset_slider(app.highlights_slider, 'highlights', 0.0, '0')),
                                ft.Text("Ombres", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.shadows_slider, on_double_tap=lambda e: app._reset_slider(app.shadows_slider, 'shadows', 0.0, '0')),
                                ft.Text("Blancs  (point blanc)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.whites_slider, on_double_tap=lambda e: app._reset_slider(app.whites_slider, 'whites', 0.0, '0')),
                                ft.Text("Noirs  (point noir)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.blacks_slider, on_double_tap=lambda e: app._reset_slider(app.blacks_slider, 'blacks', 0.0, '0')),
                                ft.Text("Contraste", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.contrast_slider, on_double_tap=lambda e: app._reset_slider(app.contrast_slider, 'contrast', 0.0, '0')),
                            ], spacing=4),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                            border=ft.Border.all(1, YELLOW),
                        ),
                        ft.Divider(height=6),


                        # ── Couleur ───────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("COULEUR", size=10, color=VIOLET, weight=ft.FontWeight.BOLD),
                                ft.Text("Saturation", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.saturation_slider, on_double_tap=lambda e: app._reset_slider(app.saturation_slider, 'saturation', 0.0, '0')),
                                ft.Text("Teinte  (−vert / +magenta)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.hue_slider, on_double_tap=lambda e: app._reset_slider(app.hue_slider, 'hue', 0.0, '0')),
                                ft.Text("Balance des blancs  (−froid / +chaud)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.white_balance_slider, on_double_tap=lambda e: app._reset_slider(app.white_balance_slider, 'white_balance', 0.0, '0')),
                            ], spacing=4),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
                            border=ft.Border.all(1, VIOLET),
                        ),
                        ft.Divider(height=6),


                        # ── Netteté ───────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("NETTETÉ", size=10, color=GREEN, weight=ft.FontWeight.BOLD),
                                app.sharpen_switch,
                            ], spacing=2),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, GREEN),
                            width=LEFT_COL_WIDTH - 20,
                        ),
                        ft.Divider(height=6),
                        ft.Button("Tout à 0", on_click=app.reset_adjustments, bgcolor=BG, color=WHITE, width=LEFT_COL_WIDTH - 20),
                        ft.Button("Réglages par défaut", on_click=app.reset_to_defaults, bgcolor=DARK, color=LIGHT_GREY, width=LEFT_COL_WIDTH - 20),
                    ], spacing=4, scroll=ft.ScrollMode.AUTO),
                    width=LEFT_COL_WIDTH,
                    bgcolor=DARK,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=12),
                    border=ft.Border.all(1, GREY),
                    border_radius=8,
                ),
                ft.Container(


                # ── Panneau du dessus : Opérations ──────────────────────
                    content=ft.Column(
                        [
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Opérations", size=16, weight=ft.FontWeight.BOLD, color=WHITE, text_align=ft.TextAlign.CENTER),
                                    ft.Divider(height=4),
                                    ft.Row([
                                        ft.Column([
                                            ft.Text("Exemplaires", size=14, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                                            ft.Row([
                                                app.copies_minus_btn,
                                                app.copies_text,
                                                app.copies_plus_btn,
                                            ], alignment=ft.MainAxisAlignment.CENTER, spacing=0),
                                        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, width=200),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            ft.Text("Formats multiples", size=14, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                                            ft.Row([
                                                ft.IconButton(
                                                    icon=ft.Icons.CLEAR,
                                                    icon_color=RED,
                                                    tooltip="Vider la liste",
                                                    on_click=app.clear_extra_formats,
                                                    icon_size=24,
                                                ),
                                                ft.IconButton(
                                                    icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                                    icon_color=BLUE,
                                                    tooltip="Ajouter le format courant à la liste",
                                                    on_click=app.add_extra_format,
                                                    icon_size=24,
                                                ),
                                                ft.Row([
                                                    app.extra_formats_display,
                                                ], scroll=ft.ScrollMode.AUTO, width=100, height=32, alignment=ft.MainAxisAlignment.START),
                                            ], width=210, alignment=ft.MainAxisAlignment.START, spacing=8),
                                        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, width=210),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            app.bw_switch,
                                            app.fit_in_switch,
                                            app.white_border_switch,
                                        ], horizontal_alignment=ft.CrossAxisAlignment.START, spacing=4),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),                                            
                                        ft.Column([
                                            ft.Text("Fond IA", size=12, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                                            app.rembg_btn,
                                            ft.Row([
                                                app.rembg_bg_btn, app.rembg_model_btn,
                                                app.rembg_precise_btn, app.pipette_sign_btn,
                                                app._rembg_tolerance_label,
                                            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                            ft.Row([
                                                ft.Text("Ér.", size=11, color=LIGHT_GREY),
                                                app.rembg_erosion_slider,
                                                ft.Text("Ad.", size=11, color=LIGHT_GREY),
                                                app.rembg_feather_slider,
                                            ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=2),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            ft.Button(
                                                content=ft.Row([
                                                    ft.Icon(ft.Icons.SWAP_HORIZ, size=16, color=BLUE),
                                                    ft.Text("Orientation", size=14, color=BLUE),
                                                ], spacing=4, tight=True),
                                                bgcolor=BG,
                                                on_click=app.toggle_orientation,
                                                style=ft.ButtonStyle(
                                                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                                    shape=ft.RoundedRectangleBorder(radius=6),
                                                ),
                                                height=30,
                                            ),
                                            app.grid_switch,
                                        ], horizontal_alignment=ft.CrossAxisAlignment.START, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=16, alignment=ft.MainAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO, height=130),
                                    ft.Divider(height=1, color=GREY),
                                    app._status_row,
                                ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=ft.Padding.only(top=6, bottom=6, left=12, right=12),
                                alignment=ft.Alignment(0, -1),
                                bgcolor=DARK,
                                border_radius=8,
                                width=1200,
                                border=ft.Border.all(1, GREY),
                            ),


                            # ── Zone centrale : Canevas de l'image ──────────────────────
                            ft.Container(
                                content=ft.Row([
                                    app.rotation_slider_col,
                                    app.canvas_container,
                                    app.zoom_slider_col,
                                ], alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=30),
                                expand=True,
                                alignment=ft.Alignment(0, 0),
                            ),
                        ],
                        spacing=0,
                        expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                ),
                ft.VerticalDivider(width=1),
                controls
            ], expand=True),
        ], expand=True)
    )



    # Gestionnaire de redimensionnement de la fenêtre
    def on_window_resize(e):
        """
        Gestionnaire de redimensionnement de la fenêtre principale.

        Recalcule les dimensions du canevas puis réapplique la transformation
        affine courante (pan / zoom / rotation).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de redimensionnement émis par Flet.
        """

        app.update_canvas_size()
        if app.image_paths:
            app._update_transform()
    
    page.on_resize = on_window_resize



# Start directly in interactive batch mode on launch (avec délai pour s'assurer que la fenêtre est initialisée)
    async def delayed_start():
        """
        Coroutine de démarrage différé du mode batch interactif.

        Attend 0,3 s après l'ouverture de la fenêtre pour laisser le
        temps à Flet de maximiser la fenêtre et d'initialiser les
        dimensions du canevas, puis démarre
        :meth:`batch_process_interactive`. Un second délai de 0,1 s
        force un recalcul des dimensions après le premier chargement
        d'image.

        Planifiée via ``asyncio.create_task(delayed_start())`` dans
        :func:`main`.

        Notes
        -----
        Les exceptions sont silencieusement ignorées afin d'éviter un
        crash au démarrage si aucun fichier n'est sélectionné.
        """

        await asyncio.sleep(0.3)  # Attendre que la fenêtre soit maximisée
        try:
            app.batch_process_interactive(None)
            # Recalage des dimensions après maximisation : géométrie
            # seulement (_refit_canvas) — l'ancien load_image() complet
            # redécodait et re-rendait la première image une 2e fois à
            # CHAQUE lancement (retour user : démarrage lent depuis Hub).
            await asyncio.sleep(0.1)
            if app.image_paths and app.batch_mode and app.current_index < len(app.image_paths):
                app._refit_canvas()
        except Exception:
            pass
    
    asyncio.create_task(delayed_start())

# Utilisation de la syntaxe recommandée pour éviter le DeprecationWarning
if __name__ == "__main__":
    ft.run(main)
