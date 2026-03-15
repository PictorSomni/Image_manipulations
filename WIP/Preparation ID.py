# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

  - Suppression automatique du fond par IA (rembg / modèle ``u2net_human_seg``).
  - Remplacement du fond par une couleur unie au choix (blanc, gris clair,
    gris moyen).
  - Affichage de la photo traitée avec grille superposée (règle des tiers ou
    quadrillage) pour faciliter l'alignement et la rotation manuelle.
  - Rotation fine (−15° … +15°) via curseur en temps réel.
  - Mise en page automatique : photo unitaire, planche ID ×2 (102×102 mm,
    2 photos empilées, 5 mm d'espacement) ou planche ID ×4 (127×102 mm,
    grille 2×2, 5 mm d'espacement).
  - Sauvegarde optionnelle des planches ID ×4 directement sur le NAS
    (partage ``TRAVAUX EN COURS/Z2026``) via le switch « Sauver sur réseau ».
  - Export JPEG 300 dpi au format cible défini dans FORMATS.

Ce script traite par défaut le format 35×45 mm (photo d'identité française,
passeport, carte de séjour…). La structure FORMATS est conçue pour accueillir
d'autres normes nationales ultérieurement (visa USA 51×51 mm, China 33×48 mm…)
sans modifier la logique principale.

Dépendances
-----------
* flet         — interface graphique
* Pillow       — traitement d'image (recadrage, composition, filtres)
* rembg        — suppression du fond par IA (``pip install rembg``)
* onnxruntime  — backend d'inférence requis par rembg
* numpy        — manipulations d'images basses couches

Variables d'environnement reconnues
-------------------------------------
FOLDER_PATH    : dossier source des images (défaut : répertoire du script)
SELECTED_FILES : noms de fichiers séparés par « | » à traiter en priorité

Notes
-----
Au premier lancement, rembg télécharge automatiquement le modèle u2net_human_seg
(~175 Mo) dans ``~/.u2net/``. Les téléchargements suivants utilisent le cache.

Version : 1.0.0
"""

__version__ = "1.0.0"

###############################################################
#                         IMPORTS                             #
###############################################################
import flet as ft
import os
import io
import base64
import math
import threading
import platform
from PIL import Image, ImageDraw, ImageOps

try:
    from rembg import remove as rembg_remove, new_session
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False

###############################################################
#                       CONFIGURATION                         #
###############################################################

DPI = 300  # Résolution d'export (points par pouce)

# ---------------------------------------------------------------------------
# Catalogue des formats photo d'identité (largeur_mm, hauteur_mm).
# Clé = libellé affiché dans l'interface.
# Extensible : décommenter ou ajouter une entrée pour activer un nouveau format.
# ---------------------------------------------------------------------------
FORMATS: dict[str, tuple[int, int]] = {
    "France / Standard (35×45 mm)": (35, 45),
    # "USA Visa (51×51 mm)":          (51, 51),
    # "Canada (50×70 mm)":            (50, 70),
    # "Maroc (35×45 mm)":             (35, 45),
    # "Chine (33×48 mm)":             (33, 48),
    # "Allemagne (35×45 mm)":         (35, 45),
}

DEFAULT_FORMAT = "France / Standard (35×45 mm)"

# Couleurs de fond disponibles (nom affiché → valeur RGB)
BG_COLORS: dict[str, tuple[int, int, int]] = {
    "Blanc":      (255, 255, 255),
    "Gris clair": (210, 210, 210),
    "Gris moyen": (170, 170, 170),
}

# Extensions d'images acceptées
IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}

# Hauteur maximale du panneau de prévisualisation (pixels écran)
PREVIEW_MAX_H = 540

# ---- Palette UI (cohérente avec Dashboard.pyw) ---- #
DARK       = "#222429"
BG_UI      = "#373d4a"
GREY       = "#2C3038"
LIGHT_GREY = "#9399A6"
BLUE       = "#45B8F5"
VIOLET     = "#AC92EC"
GREEN      = "#49B76C"
ORANGE     = "#FFA071"
RED        = "#F17171"
WHITE      = "#c7ccd8"

###############################################################
#                       UTILITAIRES                           #
###############################################################

def mm_to_pixels(mm: float, dpi: int = DPI) -> int:
    """
    Convertit une dimension en millimètres en nombre de pixels entiers.

    Parameters
    ----------
    mm : float
        Dimension à convertir en millimètres.
    dpi : int, optional
        Résolution cible en points par pouce (défaut : DPI = 300).

    Returns
    -------
    int
        Nombre de pixels correspondant (arrondi à l'entier inférieur).

    Examples
    --------
    >>> mm_to_pixels(35, 300)
    413
    >>> mm_to_pixels(45, 300)
    531
    """
    return int(mm / 25.4 * dpi)


def image_to_b64(img: Image.Image, fmt: str = "JPEG") -> str:
    """
    Encode une image PIL en chaîne base64 pour l'affichage dans ``ft.Image``.

    Parameters
    ----------
    img : PIL.Image.Image
        Image à encoder. Si ``fmt`` est ``"JPEG"`` et que l'image possède un
        canal alpha, elle est préalablement convertie en RGB.
    fmt : str, optional
        Format d'encodage intermédiaire (défaut : ``"JPEG"``).
        Utiliser ``"PNG"`` pour conserver la transparence.

    Returns
    -------
    str
        Chaîne base64 pure (sans préfixe ``data:image/…``), prête à être
        passée à ``ft.Image(src_base64=...)``.
    """
    buf = io.BytesIO()
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buf, format=fmt, quality=92)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def apply_background(rgba_img: Image.Image, bg_color: tuple[int, int, int]) -> Image.Image:
    """
    Compose une image RGBA sur un fond uni de la couleur spécifiée.

    Le canal alpha de l'image source est utilisé comme masque de composition.
    Si l'image n'est pas en mode RGBA, elle est simplement copiée sur le fond.

    Parameters
    ----------
    rgba_img : PIL.Image.Image
        Image source, typiquement la sortie de rembg (mode RGBA).
    bg_color : tuple[int, int, int]
        Couleur de fond (R, G, B) dans l'espace [0–255].

    Returns
    -------
    PIL.Image.Image
        Image résultante en mode RGB avec fond composité.
    """
    bg = Image.new("RGB", rgba_img.size, bg_color)
    if rgba_img.mode == "RGBA":
        bg.paste(rgba_img, mask=rgba_img.split()[3])
    else:
        bg.paste(rgba_img.convert("RGB"))
    return bg


def rotate_image(
    img: Image.Image,
    angle: float,
    bg_color: tuple[int, int, int],
) -> Image.Image:
    """
    Applique une rotation à une image RGB en remplissant les zones découvertes.

    La rotation est effectuée avec le filtre ``BICUBIC`` pour minimiser les
    artefacts. La taille de sortie est identique à l'image source (pas d'expansion).

    Parameters
    ----------
    img : PIL.Image.Image
        Image source en mode RGB.
    angle : float
        Angle de rotation en degrés, sens trigonométrique positif (anti-horaire).
        Une valeur de 0 retourne une copie sans transformation.
    bg_color : tuple[int, int, int]
        Couleur (R, G, B) de remplissage des coins découverts par la rotation.

    Returns
    -------
    PIL.Image.Image
        Image pivotée en mode RGB, mêmes dimensions que l'originale.
    """
    if angle == 0.0:
        return img.copy()
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=bg_color)


def draw_grid(
    img: Image.Image,
    grid_type: str,
    color: tuple[int, int, int, int] = (80, 80, 80, 180),
) -> Image.Image:
    """
    Superpose une grille semi-transparente sur l'image.

    La grille est rendue sur un calque RGBA transparent puis composité sur
    l'image d'origine afin de préserver les couleurs sans effacement.

    Parameters
    ----------
    img : PIL.Image.Image
        Image source (RGB ou RGBA). N'est pas modifiée en place.
    grid_type : str
        Type de grille :

        ``"tiers"``
            Règle des tiers — 2 lignes verticales + 2 lignes horizontales
            aux positions 1/3 et 2/3 de chaque dimension.

        ``"quadrillage"``
            Grille régulière — lignes tous les 10 % de la largeur et
            de la hauteur (9 lignes V + 9 lignes H).

    color : tuple[int, int, int, int], optional
        Couleur RGBA des lignes (défaut : gris semi-transparent).

    Returns
    -------
    PIL.Image.Image
        Copie de l'image en mode RGBA avec la grille superposée.
    """
    w, h = img.size
    result = img.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if grid_type == "tiers":
        for i in (1, 2):
            x = w * i // 3
            draw.line([(x, 0), (x, h)], fill=color, width=1)
            y = h * i // 3
            draw.line([(0, y), (w, y)], fill=color, width=1)

    elif grid_type == "quadrillage":
        divisions = 10
        for i in range(1, divisions):
            x = w * i // divisions
            draw.line([(x, 0), (x, h)], fill=color, width=1)
            y = h * i // divisions
            draw.line([(0, y), (w, y)], fill=color, width=1)

    return Image.alpha_composite(result, overlay)


###############################################################
#                        INTERFACE                            #
###############################################################

def main(page: ft.Page) -> None:
    """
    Point d'entrée Flet de l'application Preparation ID.

    Configure la fenêtre (titre, thème, dimensions), collecte la liste des
    images dans ``FOLDER_PATH``, et construit l'interface en deux zones :

      - Panneau gauche  : contrôles (format actif, couleur de fond, type de
                          grille, rotation, boutons Supprimer fond /
                          Enregistrer).
      - Zone centrale   : prévisualisation de l'image avec grille superposée
                          et boutons de navigation précédent / suivant.

    Flux de travail typique
    -----------------------
    1. L'image est chargée et affichée avec la grille active.
    2. L'opérateur clique « Supprimer le fond (IA) » → rembg tourne en thread.
    3. L'opérateur ajuste la rotation et la couleur de fond en temps réel.
    4. L'opérateur clique « Enregistrer » → le JPEG est écrit à côté de la
       source avec le suffixe ``_ID.jpg``, puis l'image suivante est chargée.

    Parameters
    ----------
    page : ft.Page
        Objet page Flet injecté automatiquement par ``ft.app(target=main)``.
    """

    # ------------------------------------------------------------------ #
    #                          FENÊTRE                                    #
    # ------------------------------------------------------------------ #
    page.title = f"Préparation photo ID  v{__version__}"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_UI
    page.window.width = 940
    page.window.height = 900
    page.window.min_width = 720
    page.window.min_height = 560

    # ------------------------------------------------------------------ #
    #                            ÉTAT                                     #
    # ------------------------------------------------------------------ #
    source_folder: str = os.environ.get(
        "FOLDER_PATH", os.path.dirname(os.path.abspath(__file__))
    )
    selected_env: str = os.environ.get("SELECTED_FILES", "")

    # Collecte des images du dossier source,
    # en plaçant les fichiers présents dans SELECTED_FILES en tête de liste.
    all_images: list[str] = []
    if os.path.isdir(source_folder):
        preferred = set(selected_env.split("|")) if selected_env else set()
        all_images = sorted(
            [
                e.path
                for e in os.scandir(source_folder)
                if os.path.splitext(e.name)[1].lower() in IMAGE_EXTENSIONS
            ],
            key=lambda p: (
                os.path.basename(p) not in preferred,
                os.path.basename(p).lower(),
            ),
        )

    state: dict = {
        "index":          0,       # Indice de l'image affichée dans all_images
        "orig_img":       None,    # PIL.Image chargée depuis le disque
        "processed":      None,    # PIL.Image RGBA retournée par rembg (ou None)
        "bg_color":       "Blanc",
        "grid":           "tiers",
        "rotation":       0.0,     # Degrés (−15 … +15)
        "format_key":     DEFAULT_FORMAT,
        "working":        False,   # True pendant l'exécution de rembg
        "layout":         "x4",   # "unitaire", "x2", "x4"
        "save_to_network": True,   # Planches ×4 → NAS si True
    }

    # Cache de prévisualisation : même mécanisme que Recadrage.pyw
    _preview_cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preview_cache")
    os.makedirs(_preview_cache_dir, exist_ok=True)
    # Nettoyer les fichiers à chaque démarrage
    for _f in os.listdir(_preview_cache_dir):
        try: os.remove(os.path.join(_preview_cache_dir, _f))
        except OSError: pass
    _preview_counter = {"v": 0}
    _prev_preview_path = {"p": None}

    # Session rembg partagée : évite de recharger le modèle (~175 Mo) à chaque appel.
    _session: list = [None]

    # ------------------------------------------------------------------ #
    #                        ÉLÉMENTS UI                                  #
    # ------------------------------------------------------------------ #
    status_text      = ft.Text("", size=12, color=LIGHT_GREY)
    image_label      = ft.Text("—", size=13, color=WHITE, text_align=ft.TextAlign.CENTER, expand=True)
    counter_text     = ft.Text("", size=12, color=LIGHT_GREY)
    progress_ring    = ft.ProgressRing(width=18, height=18, stroke_width=2, color=BLUE, visible=False)

    preview_image = ft.Image(
        src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
        fit=ft.BoxFit.CONTAIN,
        width=580,
        height=PREVIEW_MAX_H,
        visible=False,
    )
    preview_placeholder = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.PHOTO_CAMERA, size=56, color=LIGHT_GREY),
                ft.Text("Aucune image chargée", color=LIGHT_GREY, size=13),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
        ),
        width=580,
        height=PREVIEW_MAX_H,
        alignment=ft.Alignment(0, 0),
        border=ft.Border.all(1, GREY),
        border_radius=8,
        bgcolor=DARK,
    )

    rotation_slider = ft.Slider(
        min=-15, max=15, value=0,
        divisions=300,
        label="{value}°",
        active_color=BLUE,
        expand=True,
    )
    rotation_value_text = ft.Text("0.0°", size=12, color=BLUE, width=44, text_align=ft.TextAlign.RIGHT)

    bg_radio = ft.RadioGroup(
        content=ft.Column(
            [ft.Radio(value=k, label=k, fill_color=BLUE) for k in BG_COLORS],
            spacing=4,
        ),
        value="Blanc",
    )

    grid_radio = ft.RadioGroup(
        content=ft.Column(
            [
                ft.Radio(value="tiers",       label="Règle des tiers",  fill_color=BLUE),
                ft.Radio(value="quadrillage", label="Quadrillage (10×)", fill_color=BLUE),
                ft.Radio(value="aucune",      label="Aucune",            fill_color=BLUE),
            ],
            spacing=4,
        ),
        value="tiers",
    )

    prev_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT,
        icon_color=DARK, bgcolor=ORANGE,
        tooltip="Image précédente",
        disabled=True,
    )
    next_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT,
        icon_color=DARK, bgcolor=ORANGE,
        tooltip="Image suivante",
        disabled=True,
    )
    switch_x4 = ft.Switch(
        label="ID ×4", active_color=ORANGE, value=True,
        tooltip="Planche 2×2 sur 127×102 mm (5 mm espacement)",
    )
    switch_x2 = ft.Switch(
        label="ID ×2", active_color=ORANGE, value=False,
        tooltip="2 photos empilées sur 102×102 mm (5 mm espacement)",
    )
    network_switch = ft.Switch(
        label="Sauver sur réseau", active_color=GREEN, value=True,
        tooltip="Planches ×4 → NAS (TRAVAUX EN COURS/Z2026)",
    )

    process_btn = ft.Button(
        "Supprimer le fond (IA)",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=VIOLET if REMBG_AVAILABLE else GREY,
        color=WHITE,
        disabled=not REMBG_AVAILABLE,
    )
    save_btn = ft.Button(
        "Enregistrer",
        icon=ft.Icons.SAVE,
        bgcolor=GREEN,
        color=WHITE,
        disabled=True,
    )

    # ------------------------------------------------------------------ #
    #                         RENDU PREVIEW                               #
    # ------------------------------------------------------------------ #
    def _render_preview() -> None:
        """
        Construit et affiche la prévisualisation de l'image courante.

        Sélectionne la source (image traitée si disponible, sinon originale),
        applique dans l'ordre : fond coloré, rotation, grille superposée.
        Redimensionne au format d'écran sans upscaling excessif, encode en
        base64 et injecte dans ``preview_image``.

        Doit être appelée depuis le thread UI (après ``page.update()``).
        """
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return

        bg_rgb = BG_COLORS[state["bg_color"]]

        # 1. Composer avec le fond (pas de rotation : appliquée via Flet rotate)
        rgb = apply_background(base, bg_rgb)

        # 2. Mise à l'échelle pour l'affichage (ne jamais upscaler plus que 2×)
        w, h = rgb.size
        scale = min(580 / w, PREVIEW_MAX_H / h, 2.0)
        dw = max(1, int(w * scale))
        dh = max(1, int(h * scale))
        display = rgb.resize((dw, dh), Image.Resampling.LANCZOS)

        # 3. Grille
        if state["grid"] != "aucune":
            display = draw_grid(display, state["grid"]).convert("RGB")

        # Écrire dans un fichier à nom unique (invalide le cache Flutter)
        _preview_counter["v"] += 1
        tmp_path = os.path.join(_preview_cache_dir, f"_pid_{_preview_counter['v']}.jpg")
        display.save(tmp_path, format="JPEG", quality=88)
        preview_image.src = tmp_path
        # Supprimer l'ancien fichier
        if _prev_preview_path["p"]:
            try: os.remove(_prev_preview_path["p"])
            except OSError: pass
        _prev_preview_path["p"] = tmp_path
        preview_image.rotate = math.radians(state["rotation"])  # appliquer rotation actuelle
        preview_image.visible = True
        preview_placeholder.visible = False
        save_btn.disabled = state["processed"] is None
        page.update()

    # ------------------------------------------------------------------ #
    #                       CHARGEMENT D'IMAGE                            #
    # ------------------------------------------------------------------ #
    def _load_image(index: int) -> None:
        """
        Charge et affiche l'image à la position ``index`` dans ``all_images``.

        Réinitialise l'état (rotation à 0, ``processed`` à ``None``), ouvre
        l'image PIL, met à jour les labels de navigation et déclenche
        ``_render_preview``.

        Parameters
        ----------
        index : int
            Position dans la liste ``all_images``.
            Hors bornes → retour immédiat sans effet.
        """
        if not all_images or not (0 <= index < len(all_images)):
            return

        path = all_images[index]
        try:
            img = Image.open(path)
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            state["orig_img"]  = img
            state["processed"] = None
            state["index"]     = index
            state["rotation"]  = 0.0

            rotation_slider.value      = 0.0
            rotation_value_text.value  = "0.0°"
            preview_image.rotate       = 0.0
            image_label.value          = os.path.basename(path)
            counter_text.value         = f"{index + 1} / {len(all_images)}"
            prev_btn.disabled          = index == 0
            next_btn.disabled          = index == len(all_images) - 1
            save_btn.disabled          = True
            status_text.value          = ""
            process_btn.text           = "Supprimer le fond (IA)"

            _render_preview()

        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
            page.update()

    # ------------------------------------------------------------------ #
    #                           CALLBACKS                                 #
    # ------------------------------------------------------------------ #
    def on_bg_change(e) -> None:
        """Met à jour la couleur de fond sélectionnée et rafraîchit la preview."""
        state["bg_color"] = e.control.value
        _render_preview()

    def on_grid_change(e) -> None:
        """Met à jour le type de grille sélectionné et rafraîchit la preview."""
        state["grid"] = e.control.value
        _render_preview()

    def on_rotation_change(e) -> None:
        """
        Met à jour l'angle de rotation via une transformation Flet sur le widget
        (identique à Recadrage.pyw : fluide, sans re-génération de l'image).

        La valeur PIL en radians est passée à ``preview_image.rotate`` ;
        la rotation PIL réelle n'intervient qu'à l'export.
        """
        state["rotation"] = e.control.value
        e.control.label = f"{state['rotation']:.1f}°"
        rotation_value_text.value = f"{state['rotation']:+.1f}°"
        preview_image.rotate = math.radians(state["rotation"])
        preview_image.update()
        page.update()

    def on_layout_x4(e) -> None:
        """
        Active la mise en page ID ×4 et désactive ID ×2 (mutuellement exclusifs).

        Lorsque ×4 est activé, le switch réseau devient pertinent et est
        rendu visible. Lorsqu'il est désactivé (passage en unitaire),
        le switch réseau est masqué.
        """
        if e.control.value:
            state["layout"] = "x4"
            switch_x2.value = False
            network_switch.disabled = False
        else:
            state["layout"] = "unitaire"
            network_switch.disabled = True
        page.update()

    def on_layout_x2(e) -> None:
        """
        Active la mise en page ID ×2 et désactive ID ×4 (mutuellement exclusifs).

        Le switch réseau n'est pertinent que pour ×4 : il est désactivé
        automatiquement lors du passage en ×2.
        """
        if e.control.value:
            state["layout"] = "x2"
            switch_x4.value = False
            network_switch.disabled = True
        else:
            state["layout"] = "unitaire"
        page.update()

    def on_network_toggle(e) -> None:
        """Active ou désactive la sauvegarde réseau pour les planches ×4."""
        state["save_to_network"] = bool(e.control.value)

    switch_x4.on_change      = on_layout_x4
    switch_x2.on_change      = on_layout_x2
    network_switch.on_change = on_network_toggle

    def on_prev(e) -> None:
        """Charge l'image précédente dans la liste."""
        _load_image(state["index"] - 1)

    def on_next(e) -> None:
        """Charge l'image suivante dans la liste."""
        _load_image(state["index"] + 1)

    def on_process(e) -> None:
        """
        Lance la suppression du fond en arrière-plan (thread daemon).

        Désactive les boutons et affiche l'indicateur de progression pendant
        le traitement. Une fois rembg terminé, ``state["processed"]`` est mis
        à jour et la preview est rafraîchie depuis le thread de fond (via les
        attributs Flet thread-safe). Les boutons sont réactivés dans tous les
        cas (succès ou erreur).

        Le modèle ``u2net_human_seg`` est spécialisé pour la segmentation de
        personnes et donne de meilleurs résultats que le modèle généraliste
        ``u2net`` sur les portraits.
        """
        if not REMBG_AVAILABLE:
            status_text.value = "⚠️ rembg non installé — exécutez : pip install rembg onnxruntime"
            page.update()
            return

        if state["orig_img"] is None or state["working"]:
            return

        state["working"]     = True
        process_btn.disabled = True
        save_btn.disabled    = True
        progress_ring.visible = True
        status_text.value    = "Traitement IA en cours…"
        page.update()

        def _worker() -> None:
            """
            Thread de fond : exécute rembg et met à jour la preview.

            Initialise la session rembg une seule fois par session applicative
            pour éviter de recharger le modèle (~175 Mo) à chaque appel.
            Encode l'image source en PNG en mémoire, passe les octets à rembg,
            décode le résultat RGBA et le stocke dans ``state["processed"]``.
            """
            try:
                if _session[0] is None:
                    _session[0] = new_session("u2net_human_seg")

                buf = io.BytesIO()
                state["orig_img"].save(buf, format="PNG")
                buf.seek(0)

                result_bytes = rembg_remove(buf.getvalue(), session=_session[0])
                state["processed"] = Image.open(io.BytesIO(result_bytes)).convert("RGBA")

                status_text.value = "[OK] Fond supprimé — ajustez la rotation si besoin"
                process_btn.text  = "Recalculer le fond (IA)"

            except Exception as ex:
                status_text.value = f"[ERREUR] rembg : {ex}"

            finally:
                state["working"]      = False
                process_btn.disabled  = False
                progress_ring.visible = False
                _render_preview()

        threading.Thread(target=_worker, daemon=True).start()

    def on_save(e) -> None:
        """
        Exporte l'image traitée au format photo d'identité configuré.

        Pipeline d'export
        -----------------
        1. Application du fond coloré et de la rotation.
        2. Recadrage centré (fit-cover) aux dimensions du format cible (35×45 mm).
        3. Mise en page selon ``state["layout"]`` :

           ``"unitaire"``
               Fichier JPEG individuel, suffixe ``_ID.jpg``, déposé dans un
               sous-dossier ``ID`` du dossier source.

           ``"x2"``
               Double empilement vertical sur 102×102 mm (5 mm d'espacement),
               déposé dans ``<source>/ID_X2/``.

           ``"x4"``
               Planche 2×2 sur 127×102 mm (5 mm d'espacement, photos en mode
               paysage). Si ``state["save_to_network"]`` est ``True``, déposé
               dans ``TRAVAUX EN COURS/Z2026/ID_X4`` sur le NAS ; sinon dans
               ``<source>/ID_X4/``.

        4. Sauvegarde JPEG 300 dpi, qualité 95.
        5. Passage automatique à l'image suivante.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Enregistrer ».
        """
        if state["processed"] is None:
            status_text.value = "[ATTENTION] Supprimez d'abord le fond avant d'enregistrer"
            page.update()
            return

        fmt_w_mm, fmt_h_mm = FORMATS[state["format_key"]]
        out_w = mm_to_pixels(fmt_w_mm)
        out_h = mm_to_pixels(fmt_h_mm)
        bg_rgb = BG_COLORS[state["bg_color"]]

        # 1. Fond + rotation
        rgb = apply_background(state["processed"], bg_rgb)
        if state["rotation"] != 0.0:
            rgb = rotate_image(rgb, state["rotation"], bg_rgb)

        # 2. Recadrage centré (fit-cover) vers le format cible
        src_ratio = rgb.width / rgb.height
        tgt_ratio = out_w / out_h
        if src_ratio > tgt_ratio:
            new_h = out_h
            new_w = int(rgb.width * out_h / rgb.height)
        else:
            new_w = out_w
            new_h = int(rgb.height * out_w / rgb.width)
        rgb = rgb.resize((new_w, new_h), Image.Resampling.LANCZOS)
        left = (new_w - out_w) // 2
        top  = (new_h - out_h) // 2
        unit_img = rgb.crop((left, top, left + out_w, top + out_h))

        src_path = all_images[state["index"]]
        stem     = os.path.splitext(os.path.basename(src_path))[0]
        layout   = state["layout"]

        # 3. Mise en page
        SPACE_PX = mm_to_pixels(5)

        if layout == "x4":
            # Planche 2×2 sur 127×102 mm — photos en paysage
            canvas_w = mm_to_pixels(127)
            canvas_h = mm_to_pixels(102)
            img = unit_img
            if img.height > img.width:          # portrait → tourner en paysage
                img = img.rotate(90, expand=True)
            total_w = img.width  * 2 + SPACE_PX
            total_h = img.height * 2 + SPACE_PX
            start_x = (canvas_w - total_w) // 2
            start_y = (canvas_h - total_h) // 2
            canvas  = Image.new("RGB", (canvas_w, canvas_h), bg_rgb)
            for row in range(2):
                for col in range(2):
                    canvas.paste(
                        img,
                        (start_x + col * (img.width  + SPACE_PX),
                         start_y + row * (img.height + SPACE_PX)),
                    )
            final_img = canvas
            fmt_short = "ID_X4"
            filename  = f"{stem}_ID_X4.jpg"

            # Dossier de destination : réseau ou local
            if state["save_to_network"]:
                if platform.system() == "Windows":
                    base_dir = "\\\\Diskstation\\travaux en cours\\z2026\\ID_X4"
                else:
                    base_dir = "/Volumes/TRAVAUX EN COURS/Z2026/ID_X4"
            else:
                base_dir = os.path.join(os.path.dirname(src_path), fmt_short)

        elif layout == "x2":
            # Double empilement vertical sur 102×102 mm
            canvas_w = mm_to_pixels(102)
            canvas_h = mm_to_pixels(102)
            img = unit_img
            if img.width > img.height:          # paysage → tourner en portrait
                img = img.rotate(90, expand=True)
            x_off = (canvas_w - img.width) // 2
            canvas = Image.new("RGB", (canvas_w, canvas_h), bg_rgb)
            canvas.paste(img, (x_off, SPACE_PX))
            canvas.paste(img, (x_off, canvas_h - img.height - SPACE_PX))
            final_img = canvas
            fmt_short = "ID_X2"
            filename  = f"{stem}_ID_X2.jpg"
            base_dir  = os.path.join(os.path.dirname(src_path), fmt_short)

        else:  # unitaire
            final_img = unit_img
            fmt_short = "ID"
            filename  = f"{stem}_ID.jpg"
            base_dir  = os.path.join(os.path.dirname(src_path), fmt_short)

        try:
            os.makedirs(base_dir, exist_ok=True)
            out_path = os.path.join(base_dir, filename)
            # Éviter l'écrasement : suffixe _2, _3…
            if os.path.exists(out_path):
                name, ext = os.path.splitext(filename)
                i = 2
                while os.path.exists(os.path.join(base_dir, f"{name}_{i}{ext}")):
                    i += 1
                out_path = os.path.join(base_dir, f"{name}_{i}{ext}")

            final_img.save(out_path, format="JPEG", dpi=(DPI, DPI), quality=95)
            status_text.value = f"[OK] {fmt_short} → {os.path.basename(out_path)}"

            if state["index"] + 1 < len(all_images):
                _load_image(state["index"] + 1)
            else:
                page.update()

        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
            page.update()

    # Attacher les callbacks
    bg_radio.on_change        = on_bg_change
    grid_radio.on_change      = on_grid_change
    rotation_slider.on_change = on_rotation_change
    prev_btn.on_click         = on_prev
    next_btn.on_click         = on_next
    process_btn.on_click      = on_process
    save_btn.on_click         = on_save

    # ------------------------------------------------------------------ #
    #                           MISE EN PAGE                              #
    # ------------------------------------------------------------------ #
    fmt_w, fmt_h = FORMATS[DEFAULT_FORMAT]
    format_info_text = ft.Text(
        f"{fmt_w}×{fmt_h} mm  —  {mm_to_pixels(fmt_w)}×{mm_to_pixels(fmt_h)} px  —  {DPI} dpi",
        size=11,
        color=LIGHT_GREY,
    )

    left_panel = ft.Column(
        [
            # Format
            ft.Text("Format", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            format_info_text,
            ft.Divider(color=GREY),
            # Fond
            ft.Text("Couleur de fond", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            bg_radio,
            ft.Divider(color=GREY),
            # Grille
            ft.Text("Grille de cadrage", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            grid_radio,
            ft.Divider(color=GREY),
            # Rotation
            ft.Text("Rotation", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Row([rotation_slider, rotation_value_text], spacing=4),
            ft.Divider(color=GREY),
            # Mise en page
            ft.Text("Mise en page", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Column([
                ft.Row([switch_x4, switch_x2], spacing=16),
                network_switch,
            ], spacing=4),
            ft.Divider(color=GREY),
            # Actions
            ft.Row([process_btn, progress_ring], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            save_btn,
            ft.Container(expand=True),
            status_text,
        ],
        width=240,
        spacing=10,
    )

    center_panel = ft.Column(
        [
            ft.Row(
                [image_label, counter_text],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Stack([preview_placeholder, preview_image]),
            ft.Row(
                [prev_btn, ft.Container(expand=True), next_btn],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
        ],
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=8,
    )

    page.add(
        ft.Row(
            [
                ft.Container(
                    content=left_panel,
                    padding=ft.Padding(12, 14, 12, 14),
                    bgcolor=DARK,
                    border_radius=10,
                    border=ft.Border.all(1, GREY),
                ),
                ft.Container(width=14),
                center_panel,
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
    )

    # ------------------------------------------------------------------ #
    #                         INITIALISATION                              #
    # ------------------------------------------------------------------ #
    if not REMBG_AVAILABLE:
        status_text.value = "⚠️ rembg non installé — exécutez : pip install rembg onnxruntime"
        page.update()

    if all_images:
        _load_image(0)
    else:
        status_text.value = f"Aucune image trouvée dans : {source_folder}"
        page.update()


###############################################################
#                        POINT D'ENTRÉE                       #
###############################################################

if __name__ == "__main__":
    ft.run(main)
