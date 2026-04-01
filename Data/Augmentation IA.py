# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

  - Suppression automatique du fond par IA (rembg / modèle ``birefnet-portrait``).
  - Restauration du visage par IA (spandrel + 4xFaceUpSharpDAT) :
    amélioration des détails du visage ×4, compatible Python 3.14+.
  - Agrandissement ×2 / ×4 par super-résolution (spandrel + modèles RealESRGAN) :
    upscaling haute qualité sans perte de détails, compatible Python 3.11+.
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
* spandrel     — super-résolution et restauration visage (``pip install spandrel``)
* torch        — moteur d'inférence PyTorch requis par spandrel

Variables d'environnement reconnues
-------------------------------------
FOLDER_PATH    : dossier source des images (défaut : répertoire du script)
SELECTED_FILES : noms de fichiers séparés par « | » à traiter en priorité

Notes
-----
Au premier lancement, rembg télécharge automatiquement le modèle birefnet-portrait
(~450 Mo) dans ``~/.u2net/``. Les modèles spandrel (RealESRGAN, FaceUpSharpDAT)
sont téléchargés dans ``~/.cache/enhance_id/`` au premier usage (~350 Mo au total).

Version : 1.9.4
"""

__version__ = "1.9.4"

###############################################################
#                         IMPORTS                             #
###############################################################
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")
warnings.filterwarnings("ignore", message=".*torch.meshgrid.*indexing.*", category=UserWarning)

import flet as ft
import os
import io
import contextlib
import base64
import asyncio
import math
import json
import urllib.request
import importlib.util
from PIL import Image, ImageFilter
import numpy as np

# Détection de disponibilité sans import lourd (torch ≈ 2-5 s, rembg ≈ 1-2 s)
REMBG_AVAILABLE  = importlib.util.find_spec("rembg")    is not None
ESRGAN_AVAILABLE = (
    importlib.util.find_spec("torch")    is not None
    and importlib.util.find_spec("spandrel") is not None
)


###############################################################
#                       CONFIGURATION                         #
###############################################################

DPI = 300  # Résolution d'export (points par pouce)

# ---- Modèles IA ----
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(_MODELS_DIR, exist_ok=True)


def _list_pth_models() -> list[str]:
    """Retourne les noms de fichiers .pth / .safetensors trouvés dans _MODELS_DIR, triés."""
    if not os.path.isdir(_MODELS_DIR):
        return []
    return sorted(
        e.name for e in os.scandir(_MODELS_DIR)
        if e.name.lower().endswith((".pth", ".safetensors"))
    )


# Couleurs de fond disponibles (nom affiché → valeur RGB)
# "Transparent" est géré séparément (export PNG, damier en prévisualisation).
BG_COLORS: dict[str, tuple[int, int, int]] = {
    "Blanc": (255, 255, 255),
}

# Extensions d'images acceptées
IMAGE_EXTENSIONS: set[str] = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}

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

def _make_checkerboard(size: tuple, square: int = 16) -> Image.Image:
    """Génère un fond damier gris/blanc pour visualiser la transparence."""
    w, h = size
    xs = np.arange(w) // square
    ys = np.arange(h) // square
    grid = (xs[np.newaxis, :] + ys[:, np.newaxis]) % 2
    arr = np.where(
        grid[..., np.newaxis],
        np.array([245, 245, 245, 255], dtype=np.uint8),
        np.array([200, 200, 200, 255], dtype=np.uint8),
    ).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


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
    img.save(buf, format=fmt, quality=100)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def apply_background(
    rgba_img: Image.Image,
    bg_color: tuple[int, int, int] | None,
    orig_img: Image.Image | None = None,
) -> Image.Image:
    """
    Compose une image RGBA sur un fond uni ou flou.

    Si ``bg_color`` est ``None``, le fond est généré en appliquant un flou
    gaussien (rayon 64) sur ``orig_img`` (ou sur l'image elle-même si absent).
    Sinon, un fond uni RGB est utilisé.
    """
    if bg_color is None:  # mode Flou
        src = (orig_img if orig_img is not None else rgba_img).convert("RGB")
        if src.size != rgba_img.size:
            src = src.resize(rgba_img.size, Image.Resampling.BICUBIC)
        blurred = src.filter(ImageFilter.GaussianBlur(radius=64))
        if rgba_img.mode == "RGBA":
            bg = blurred.convert("RGBA")
            return Image.alpha_composite(bg, rgba_img).convert("RGB")
        return blurred
    bg = Image.new("RGB", rgba_img.size, bg_color)
    if rgba_img.mode == "RGBA":
        bg.paste(rgba_img, mask=rgba_img.split()[3])
    else:
        bg.paste(rgba_img.convert("RGB"))
    return bg


def _ensure_model(urls: "str | list[str]", path: str) -> None:
    """
    Télécharge le modèle IA si absent du cache (~/.cache/enhance_id/).
    Accepte une URL unique ou une liste d'URLs de secours.
    En cas d'échec de toutes les URLs, lève une RuntimeError avec les
    instructions de téléchargement manuel.
    """
    if os.path.exists(path):
        return
    url_list = [urls] if isinstance(urls, str) else list(urls)
    last_err = None
    for url in url_list:
        tmp = path + ".part"
        try:
            urllib.request.urlretrieve(url, tmp)
            os.rename(tmp, path)
            return
        except Exception as e:
            last_err = e
            if os.path.exists(tmp):
                os.remove(tmp)
    model_name = os.path.basename(path)
    raise RuntimeError(
        f"Téléchargement échoué pour {model_name} ({last_err}).\n"
        f"Téléchargez-le manuellement depuis https://openmodeldb.info\n"
        f"et placez-le dans : {_MODELS_DIR}"
    )


def _erode_alpha(img: Image.Image, radius: int) -> Image.Image:
    """
    Érode le canal alpha d'une image RGBA d'environ ``radius`` pixels.

    Utilise un filtre morphologique Min (ImageFilter.MinFilter) sur le
    canal alpha pour supprimer les franges résiduelles (halo coloré) en
    bordure de masque, fréquentes après une suppression de fond par IA.

    Parameters
    ----------
    img : PIL.Image.Image
        Image en mode RGBA à traiter.
    radius : int
        Rayon d'érosion en pixels (1–15). 0 ou négatif = pas d'érosion.

    Returns
    -------
    PIL.Image.Image
        Image RGBA avec le canal alpha érodé.
    """
    if img.mode != "RGBA" or radius <= 0:
        return img
    r, g, b, a = img.split()
    # MinFilter(3) appliqué radius fois : coût O(9 × radius × N pixels)
    # bien plus rapide que MinFilter(2*radius+1) en O((2r+1)² × N).
    for _ in range(radius):
        a = a.filter(ImageFilter.MinFilter(3))
    return Image.merge("RGBA", (r, g, b, a))


###############################################################
#                        INTERFACE                            #
###############################################################

async def main(page: ft.Page) -> None:
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
    page.title = f"Augmentation IA  v{__version__}"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_UI
    page.window.width = 1024
    page.window.height = 720

    # ------------------------------------------------------------------ #
    #                            ÉTAT                                     #
    # ------------------------------------------------------------------ #
    source_folder: str = os.environ.get(
        "FOLDER_PATH", os.path.dirname(os.path.abspath(__file__))
    )
    selected_env: str = os.environ.get("SELECTED_FILES", "")

    # Collecte des images du dossier source.
    # Si SELECTED_FILES est fourni (lancement depuis le Dashboard), seuls ces
    # fichiers sont inclus (filtre strict).  Sinon, toutes les images du dossier
    # sont listées par ordre alphabétique.
    all_images: list[str] = []
    if os.path.isdir(source_folder):
        preferred = set(selected_env.split("|")) if selected_env else set()
        all_images = sorted(
            [
                e.path
                for e in os.scandir(source_folder)
                if os.path.splitext(e.name)[1].lower() in IMAGE_EXTENSIONS
                and (not preferred or os.path.basename(e.path) in preferred)
            ],
            key=lambda p: os.path.basename(p).lower(),
        )

    state: dict = {
        "index":           0,      # Indice de l'image affichée dans all_images
        "orig_img":        None,   # PIL.Image chargée depuis le disque
        "processed":       None,   # PIL.Image RGBA retournée par rembg (ou None)
        "bg_color":        "Blanc",
        "bg_blur":         False,  # True = fond flou (remplace la couleur de fond)
        "bg_transparent":  False,  # True = fond transparent (export PNG)
        "rembg_human_seg": True,   # True = portrait, False = général
        "rembg_precise":   False,  # True = birefnet (précis), False = u2net (rapide)
        "working":         False,  # True pendant l'exécution de rembg
        "enhancing":       False,  # True pendant face SR ou ESRGAN
        "rembg_applied":   False,  # True après suppression du fond par rembg
        "history":         [],     # Pile d'annulation (max 5)
        "current_task":    None,   # asyncio.Task en cours (rembg ou modèle)
        "cancel_requested": False, # Annulation demandée (boucle de tuiles)
        "erosion_radius":  0,      # Rayon d'érosion en pixels (0 = désactivé)
    }

    # Sessions rembg (une par modèle pour éviter le rechargement)
    _session: list = [None]               # birefnet-portrait
    _session_general: list = [None]       # birefnet-general
    _session_u2net: list = [None]         # u2net_human_seg
    _session_u2net_gen: list = [None]     # u2net
    # Modèles spandrel : cache par nom de fichier
    _custom_model_cache: dict = {}  # {nom_fichier: desc}

    # ------------------------------------------------------------------ #
    #                        ÉLÉMENTS UI                                  #
    # ------------------------------------------------------------------ #
    status_text      = ft.Text("", size=12, color=LIGHT_GREY)
    image_label      = ft.Text("—", size=13, color=WHITE, text_align=ft.TextAlign.CENTER, expand=True)
    counter_text     = ft.Text("", size=12, color=LIGHT_GREY)
    progress_bar     = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)

    # ---- Zone de prévisualisation ---- #
    preview_img = ft.Image(
        src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
        fit=ft.BoxFit.CONTAIN,
        expand=True,
        gapless_playback=True,
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
        expand=True,
        alignment=ft.Alignment(0, 0),
        border=ft.Border.all(1, GREY),
        border_radius=8,
        bgcolor=DARK,
    )

    bg_radio = ft.RadioGroup(
        content=ft.Column(
            [ft.Radio(value=k, label=k, fill_color=BLUE) for k in BG_COLORS]
            + [
                ft.Radio(value="Transparent", label="Transparent (PNG)", fill_color=BLUE),
                ft.Radio(value="Flou",        label="Flou",             fill_color=BLUE),
            ],
            spacing=4,
        ),
        value="Blanc",
    )

    # Bascule modèle rembg : humain / général
    _model_toggle_label = ft.Text("Humain", size=12, color=DARK)
    model_toggle_btn = ft.Button(
        content=_model_toggle_label,
        bgcolor=VIOLET if REMBG_AVAILABLE else GREY,
        disabled=not REMBG_AVAILABLE,
        tooltip="Basculer entre portrait et généraliste",
    )

    # Bascule qualité rembg : rapide (u2net) / précis (birefnet)
    _precise_toggle_label = ft.Text("Rapide", size=12, color=DARK)
    precise_toggle_btn = ft.Button(
        content=_precise_toggle_label,
        bgcolor=BLUE if REMBG_AVAILABLE else GREY,
        disabled=not REMBG_AVAILABLE,
        tooltip="Rapide : u2net (moins puissant) / Précis : birefnet (meilleure qualité)",
    )

    # Bouton Annuler la dernière modification
    undo_btn = ft.IconButton(
        icon=ft.Icons.UNDO,
        icon_color=WHITE,
        bgcolor=GREY,
        tooltip="Annuler la dernière modification",
        disabled=True,
    )

    # Bouton Ignorer (passer à l'image suivante sans enregistrer)
    ignore_btn = ft.Button(
        "Ignorer",
        icon=ft.Icons.SKIP_NEXT,
        bgcolor=GREY,
        color=ORANGE,
    )

    process_btn = ft.Button(
        "Supprimer le fond (IA)",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=VIOLET if REMBG_AVAILABLE else GREY,
        color=DARK,
        disabled=not REMBG_AVAILABLE,
    )
    save_btn = ft.Button(
        "Valider et enregistrer",
        icon=ft.Icons.SAVE,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT:  GREEN,
                ft.ControlState.DISABLED: GREY,
            },
            color={
                ft.ControlState.DEFAULT:  WHITE,
                ft.ControlState.DISABLED: LIGHT_GREY,
            },
        ),
        disabled=True,
    )

    enhance_progress_bar = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    enhance_status = ft.Text("", size=11, color=LIGHT_GREY)

    cancel_btn = ft.FilledButton(
        "Annuler",
        icon=ft.Icons.CANCEL_OUTLINED,
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.with_opacity(0.15, RED),
            color=RED,
            side=ft.BorderSide(1, RED),
        ),
        visible=False,
        tooltip="Annuler le traitement en cours",
    )

    # ---- Érosion du masque ---- #
    erosion_slider = ft.Slider(
        value=0,
        min=0,
        max=15,
        divisions=15,
        label="{value} px",
        active_color=ORANGE,
        disabled=not REMBG_AVAILABLE,
        expand=True,
    )

    # ---- Sélecteur de modèle personnalisé ---- #
    def _build_model_options() -> list[ft.dropdown.Option]:
        names = _list_pth_models()
        if not names:
            return [ft.dropdown.Option(key="", text="Aucun modèle (.pth / .safetensors) dans models/")]
        return [ft.dropdown.Option(key=n, text=n) for n in names]

    model_dropdown = ft.Dropdown(
        options=_build_model_options(),
        value=(_list_pth_models() or [""])[0],
        bgcolor=GREY,
        color=WHITE,
        border_color=LIGHT_GREY,
        text_size=11,
        dense=True,
        expand=True,
        disabled=not ESRGAN_AVAILABLE,
    )
    run_model_btn = ft.IconButton(
        icon=ft.Icons.PLAY_ARROW,
        icon_color=DARK,
        bgcolor=BLUE if ESRGAN_AVAILABLE else GREY,
        tooltip="Lancer le modèle sélectionné",
        disabled=not ESRGAN_AVAILABLE or not _list_pth_models(),
    )
    refresh_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=WHITE,
        bgcolor=GREY,
        tooltip="Rafraîchir la liste des modèles",
    )
    # ------------------------------------------------------------------ #
    async def _animate_progress(bar: ft.ProgressBar, stop_event: asyncio.Event) -> None:
        """Anime la barre de progression de 0 % jusqu'à ~90 % puis saute à 100 %."""
        elapsed = 0.0
        while not stop_event.is_set():
            await asyncio.sleep(0.15)
            elapsed += 0.15
            bar.value = 0.9 * (1 - math.exp(-elapsed / 8))
            page.update()
        bar.value = 1.0
        page.update()
        await asyncio.sleep(0.25)
        bar.visible = False
        page.update()

    # ------------------------------------------------------------------ #
    def _render_preview() -> None:
        """Render complet : applique le fond + thumbnail."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return
        # Pour l'érosion : réduire à ~1/3 de la résolution (max 2000px) afin que
        # le rayon mis à l'échelle ait assez de granularité pour refléter
        # fidèlement l'effet pleine résolution. On downscale ensuite à 700px.
        erode_size = min(2000, max(700, base.width // 3))
        thumb = base.copy()
        thumb.thumbnail((erode_size, erode_size), Image.Resampling.BILINEAR)
        # Érosion au format d'affichage (ne modifie pas state["processed"])
        if state["erosion_radius"] > 0 and state["processed"] is not None and thumb.mode == "RGBA":
            scale = thumb.width / base.width
            scaled_radius = round(state["erosion_radius"] * scale)
            if scaled_radius > 0:
                thumb = _erode_alpha(thumb, scaled_radius)
        # Downscale final pour l'affichage
        if thumb.width > 700 or thumb.height > 700:
            thumb.thumbnail((700, 700), Image.Resampling.BILINEAR)
        if state["bg_blur"]:
            display = apply_background(thumb, None, state["orig_img"])
        elif state["bg_transparent"]:
            # Damier pour visualiser la transparence
            rgba = thumb.convert("RGBA")
            chk = _make_checkerboard(rgba.size)
            display = Image.alpha_composite(chk, rgba).convert("RGB")
        else:
            display = apply_background(thumb, BG_COLORS[state["bg_color"]], state["orig_img"])
        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(display)}"
        preview_img.visible = True
        preview_placeholder.visible = False
        save_btn.disabled = state["processed"] is None
        page.update()

    # ------------------------------------------------------------------ #
    #                       CHARGEMENT D'IMAGE                            #
    # ------------------------------------------------------------------ #
    async def _load_image(index: int) -> None:
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

            state["orig_img"]       = img
            state["processed"]     = None
            state["index"]         = index
            state["rembg_applied"] = False
            state["history"].clear()

            process_btn.text    = "Supprimer le fond (IA)"
            process_btn.bgcolor = VIOLET if REMBG_AVAILABLE else GREY
            image_label.value   = os.path.basename(path)
            counter_text.value  = f"{index + 1} / {len(all_images)}"
            save_btn.disabled   = True
            undo_btn.disabled   = True
            status_text.value   = ""

            _render_preview()

        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
            page.update()

    # ------------------------------------------------------------------ #
    #                           CALLBACKS                                 #
    # ------------------------------------------------------------------ #
    def on_refresh_models(e) -> None:
        """Rescanne Data/models/ et met à jour le dropdown."""
        opts = _build_model_options()
        model_dropdown.options = opts
        names = _list_pth_models()
        model_dropdown.value = names[0] if names else ""
        run_model_btn.disabled = not ESRGAN_AVAILABLE or not names
        page.update()

    async def on_run_model(e) -> None:
        """Exécute le modèle .pth/.safetensors sélectionné via spandrel sur l'image courante."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        model_name = model_dropdown.value
        if base is None or state["enhancing"] or not model_name:
            return

        def _set_all_ia_btns(disabled: bool) -> None:
            run_model_btn.disabled  = disabled
            refresh_btn.disabled    = disabled

        state["enhancing"]           = True
        state["cancel_requested"]    = False
        _push_history()
        _set_all_ia_btns(True)
        enhance_progress_bar.value   = None  # indéterminé jusqu'au début des tuiles
        enhance_progress_bar.visible = True
        cancel_btn.visible           = True
        enhance_status.value         = f"Chargement de {model_name}…"
        page.update()

        has_alpha = (base.mode == "RGBA")
        alpha     = base.split()[3] if has_alpha else None

        def _progress_cb(value: "float | None", label: str = "") -> None:
            """Met à jour la barre et le label depuis le thread d'inférence."""
            enhance_progress_bar.value = value
            if label:
                enhance_status.value = label
            page.update()

        def _do_run():
            import torch as _torch
            from spandrel import ModelLoader as _ModelLoader
            model_path = os.path.join(_MODELS_DIR, model_name)
            if model_name not in _custom_model_cache:
                if _torch.cuda.is_available():
                    _dev = "cuda"
                elif getattr(_torch.backends, "mps", None) and _torch.backends.mps.is_available():
                    _dev = "mps"
                else:
                    _dev = "cpu"
                # Barre indéterminée pendant le chargement du modèle
                _progress_cb(None, f"Chargement de {model_name}…")
                desc = _ModelLoader().load_from_file(model_path)
                desc.to(_dev)
                desc.model.eval()
                _custom_model_cache[model_name] = desc
            desc = _custom_model_cache[model_name]
            _dev = next(iter(desc.model.parameters())).device
            # FP16 : fiable sur CUDA uniquement (MPS FP16 partiel, CPU sans intérêt)
            use_fp16 = (_dev.type == "cuda")

            rgb = np.array(base.convert("RGB")).astype(np.float32) / 255.0
            h, w = rgb.shape[:2]

            # --- Inférence tuilée ----------------------------------------
            # Taille de tuile adaptée au backend pour maximiser la vitesse :
            #   CUDA  → 512 px (RTX 2080 : 8 Go VRAM, très à l'aise)
            #   MPS   → 384 px (mémoire unifiée partagée avec l'OS)
            #   CPU   → 256 px (évite une empreinte RAM trop lourde)
            if _dev.type == "cuda":
                TILE = 512
            elif _dev.type == "mps":
                TILE = 384
            else:
                TILE = 256
            OVERLAP = TILE // 16
            STEP   = TILE - OVERLAP

            def _scale_factor():
                """Déduit le facteur d'agrandissement d'une inférence rapide."""
                probe = _torch.zeros(1, 3, 4, 4, device=_dev)
                if use_fp16:
                    probe = probe.half()
                with _torch.inference_mode():
                    out_probe = desc(probe)
                return out_probe.shape[-1] // 4  # largeur_sortie / largeur_entrée

            scale = _scale_factor()
            out_h, out_w = h * scale, w * scale
            out_np_full = np.zeros((out_h, out_w, 3), dtype=np.float32)
            weight_map  = np.zeros((out_h, out_w, 1),  dtype=np.float32)

            # Fenêtre de pondération : plein centre, fondu sur l'overlap
            def _make_weight(th, tw):
                wy = np.ones(th, dtype=np.float32)
                wx = np.ones(tw, dtype=np.float32)
                fade = min(OVERLAP, th // 2, tw // 2)
                ramp  = np.linspace(0.0, 1.0, fade, dtype=np.float32)
                wy[:fade]  = ramp;  wy[-fade:] = ramp[::-1]
                wx[:fade]  = ramp;  wx[-fade:] = ramp[::-1]
                return np.outer(wy, wx)[:, :, np.newaxis]

            ys = list(range(0, h - TILE, STEP)) + [max(0, h - TILE)]
            xs = list(range(0, w - TILE, STEP)) + [max(0, w - TILE)]

            # Si l'image est plus petite que TILE on traite d'un seul coup
            if h <= TILE and w <= TILE:
                ys, xs = [0], [0]

            total_tiles = len(ys) * len(xs)
            done_tiles  = 0
            _progress_cb(0.0, f"Traitement avec {model_name} — tuile 0/{total_tiles}")

            with _torch.inference_mode():
                for y0 in ys:
                    y1 = min(y0 + TILE, h)
                    for x0 in xs:
                        x1 = min(x0 + TILE, w)
                        tile_np  = rgb[y0:y1, x0:x1]
                        tile_t   = _torch.from_numpy(tile_np).permute(2, 0, 1).unsqueeze(0).to(_dev)
                        if use_fp16:
                            tile_t = tile_t.half()
                        out_tile = desc(tile_t).squeeze(0).permute(1, 2, 0).clamp(0, 1)
                        if use_fp16:
                            out_tile = out_tile.float()
                        out_tile_np = out_tile.cpu().numpy()
                        oy0, ox0 = y0 * scale, x0 * scale
                        oy1, ox1 = oy0 + out_tile_np.shape[0], ox0 + out_tile_np.shape[1]
                        w_tile = _make_weight(out_tile_np.shape[0], out_tile_np.shape[1])
                        out_np_full[oy0:oy1, ox0:ox1] += out_tile_np * w_tile
                        weight_map  [oy0:oy1, ox0:ox1] += w_tile
                        done_tiles += 1
                        if state.get("cancel_requested"):
                            raise InterruptedError("Annulé par l'utilisateur")
                        _progress_cb(
                            done_tiles / total_tiles,
                            f"Traitement avec {model_name} — tuile {done_tiles}/{total_tiles}",
                        )

            out_np = ((out_np_full / np.maximum(weight_map, 1e-6)).clip(0, 1) * 255).astype(np.uint8)
            out = Image.fromarray(out_np)
            if has_alpha and alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha.resize(out.size, Image.Resampling.LANCZOS))
            return out

        model_task = asyncio.create_task(asyncio.to_thread(_do_run))
        state["current_task"] = model_task
        try:
            result = await model_task
            state["processed"] = result
            enhance_status.value = f"[OK] {model_name} → {result.width}×{result.height} px"
        except asyncio.CancelledError:
            enhance_status.value = "Traitement annulé"
        except InterruptedError:
            enhance_status.value = "Traitement annulé"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] {model_name} : {ex}"
        finally:
            enhance_progress_bar.value   = 1.0
            enhance_progress_bar.visible = False
            state["enhancing"] = False
            state["current_task"]   = None
            cancel_btn.visible      = False
            _set_all_ia_btns(False)
            run_model_btn.disabled  = not _list_pth_models()
            if state["processed"] is not None:
                save_btn.disabled = False
            page.update()
            _render_preview()

    async def on_cancel(e) -> None:
        """Annule le traitement IA en cours (rembg ou modèle)."""
        state["cancel_requested"] = True
        task = state.get("current_task")
        if task and not task.done():
            task.cancel()

    def on_erosion_slider_change(e) -> None:
        """Met à jour le rayon en temps réel (label uniquement pendant le drag)."""
        state["erosion_radius"] = int(e.control.value)

    def on_erosion_slider_end(e) -> None:
        """Regénère la preview au relâchement du slider."""
        state["erosion_radius"] = int(e.control.value)
        if state["processed"] is not None:
            _render_preview()

    def on_bg_change(e) -> None:
        """Met à jour la couleur de fond sélectionnée et rafraîchit la preview."""
        val = e.control.value
        if val == "Flou":
            state["bg_blur"]         = True
            state["bg_transparent"]  = False
        elif val == "Transparent":
            state["bg_blur"]         = False
            state["bg_transparent"]  = True
            state["bg_color"]        = "Blanc"  # fallback interne
        else:
            state["bg_blur"]         = False
            state["bg_transparent"]  = False
            state["bg_color"]        = val
        _render_preview()

    async def on_prev(e) -> None:
        """Charge l'image précédente dans la liste."""
        await _load_image(state["index"] - 1)

    async def on_next(e) -> None:
        """Charge l'image suivante dans la liste."""
        await _load_image(state["index"] + 1)

    async def on_process(e) -> None:
        """
        Lance la suppression du fond par IA (rembg) via asyncio.to_thread.

        Désactive les boutons et affiche l'indicateur de progression pendant
        le traitement. La partie bloquante (rembg + chargement modèle) est
        délégée à un thread pool via ``asyncio.to_thread``. Les mises à jour
        UI s'exécutent ensuite sur la boucle asyncio principale de Flet,
        garantissant un rafraîchissement immédiat sans interaction requise.

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

        # Toggle : recliquer annule le masque et restaure l'original
        if state["rembg_applied"]:
            # Pousser dans l'historique avant d'annuler
            _push_history()
            state["processed"]    = None
            state["rembg_applied"] = False
            process_btn.text      = "Supprimer le fond (IA)"
            process_btn.bgcolor   = VIOLET
            save_btn.disabled     = True
            status_text.value     = "Masque annulé"
            _render_preview()
            return

        state["working"]          = True
        state["cancel_requested"]  = False
        _push_history()
        process_btn.disabled       = True
        save_btn.disabled          = True
        progress_bar.value         = 0.0
        progress_bar.visible       = True
        cancel_btn.visible         = True
        status_text.value          = "Traitement IA en cours…"
        page.update()

        _stop_anim = asyncio.Event()
        anim_task  = asyncio.create_task(_animate_progress(progress_bar, _stop_anim))

        def _do_rembg():
            from rembg import remove as rembg_remove, new_session
            use_human  = state["rembg_human_seg"]
            use_precise = state["rembg_precise"]
            if use_precise:
                # Mode précis : birefnet
                if use_human:
                    if _session[0] is None:
                        _session[0] = new_session("birefnet-portrait")
                    sess = _session[0]
                else:
                    if _session_general[0] is None:
                        _session_general[0] = new_session("birefnet-general")
                    sess = _session_general[0]
            else:
                # Mode rapide : u2net
                if use_human:
                    if _session_u2net[0] is None:
                        _session_u2net[0] = new_session("u2net_human_seg")
                    sess = _session_u2net[0]
                else:
                    if _session_u2net_gen[0] is None:
                        _session_u2net_gen[0] = new_session("u2net")
                    sess = _session_u2net_gen[0]
            buf = io.BytesIO()
            state["orig_img"].save(buf, format="PNG")
            buf.seek(0)
            raw = buf.getvalue()
            with contextlib.redirect_stderr(io.StringIO()):
                result_bytes = rembg_remove(raw, session=sess)
            return Image.open(io.BytesIO(result_bytes)).convert("RGBA")  # type: ignore[arg-type]

        rembg_task = asyncio.create_task(asyncio.to_thread(_do_rembg))
        state["current_task"] = rembg_task
        try:
            result = await rembg_task
            state["processed"]    = result
            state["rembg_applied"] = True
            process_btn.text      = "Annuler le masque"
            process_btn.bgcolor   = ORANGE
            status_text.value     = "[OK] Fond supprimé — recliquer pour annuler"
        except asyncio.CancelledError:
            status_text.value = "Traitement annulé"
        except Exception as ex:
            status_text.value = f"[ERREUR] rembg : {ex}"
        finally:
            _stop_anim.set()
            await anim_task
            state["working"]       = False
            state["current_task"]  = None
            cancel_btn.visible     = False
            process_btn.disabled   = False
            _render_preview()

    async def _close_after_delay() -> None:
        await asyncio.sleep(1.5)
        await page.window.close()

    async def on_save(e) -> None:
        """Exporte l'image traitée dans un sous-dossier OK. PNG si fond transparent, JPEG sinon."""
        if state["processed"] is None:
            status_text.value = "[ATTENTION] Appliquez d'abord une amélioration IA avant d'enregistrer"
            page.update()
            return

        # Désactiver le bouton pendant l'export pour éviter les double-clics
        save_btn.disabled = True
        has_erosion = state["erosion_radius"] > 0 and state["processed"].mode == "RGBA"
        if has_erosion:
            status_text.value = f"Érosion {state['erosion_radius']} px en cours…"
            progress_bar.value = None  # indéterminée
            progress_bar.visible = True
        else:
            status_text.value = "Enregistrement…"
        page.update()

        use_transparent = state["bg_transparent"]
        snap_processed  = state["processed"]
        snap_orig       = state["orig_img"]
        erosion_radius  = state["erosion_radius"]
        bg_blur         = state["bg_blur"]
        bg_color        = BG_COLORS.get(state["bg_color"])

        def _do_export():
            proc = snap_processed
            # Érosion pleine résolution (potentiellement long sur grandes images)
            if erosion_radius > 0 and proc is not None and proc.mode == "RGBA":
                proc = _erode_alpha(proc, erosion_radius)
            if use_transparent:
                return proc.convert("RGBA"), ".png", "PNG", {}
            else:
                bg_rgb = None if bg_blur else bg_color
                img = apply_background(proc, bg_rgb, snap_orig)
                return img, ".jpg", "JPEG", {"dpi": (DPI, DPI), "quality": 100}

        try:
            final_img, ext, fmt, save_kwargs = await asyncio.to_thread(_do_export)

            if has_erosion:
                progress_bar.value   = 1.0
                progress_bar.visible = False
                status_text.value    = "Enregistrement…"
                page.update()

            src_path = all_images[state["index"]]
            stem     = os.path.splitext(os.path.basename(src_path))[0]
            base_dir = os.path.join(os.path.dirname(src_path), "OK")
            filename = f"OK_{stem}{ext}"

            os.makedirs(base_dir, exist_ok=True)
            out_path = os.path.join(base_dir, filename)
            if os.path.exists(out_path):
                name, e2 = os.path.splitext(filename)
                i = 2
                while os.path.exists(os.path.join(base_dir, f"{name}_{i}{e2}")):
                    i += 1
                out_path = os.path.join(base_dir, f"{name}_{i}{e2}")

            await asyncio.to_thread(final_img.save, out_path, format=fmt, **save_kwargs)
            state["history"].clear()
            undo_btn.disabled = True

            next_idx = state["index"] + 1
            if next_idx < len(all_images):
                status_text.value = f"[OK] OK → {os.path.basename(out_path)}"
                await _load_image(next_idx)
            else:
                status_text.value = f"[OK] OK → {os.path.basename(out_path)}  —  Toutes les images traitées !"
                page.update()
                await asyncio.sleep(1.5)
                await page.window.close()

        except Exception as ex:
            progress_bar.visible = False
            status_text.value = f"[ERREUR] {ex}"
            save_btn.disabled = False
            page.update()

    async def on_ignore(e) -> None:
        """Passe à l'image suivante sans enregistrer."""
        next_idx = state["index"] + 1
        if next_idx < len(all_images):
            await _load_image(next_idx)
        else:
            status_text.value = "Toutes les images ont été parcourues."
            page.update()
            asyncio.create_task(_close_after_delay())

    def _push_history() -> None:
        """Empile l'état courant dans l'historique (max 5 crans)."""
        state["history"].append({
            "processed":    state["processed"],
            "rembg_applied": state["rembg_applied"],
        })
        if len(state["history"]) > 5:
            state["history"].pop(0)
        undo_btn.disabled = False

    def on_undo(e) -> None:
        """Annule la dernière modification (rembg, modèle)."""
        if not state["history"]:
            return
        snap = state["history"].pop()
        state["processed"]    = snap["processed"]
        state["rembg_applied"] = snap["rembg_applied"]
        if state["processed"] is None:
            process_btn.text    = "Supprimer le fond (IA)"
            process_btn.bgcolor = VIOLET if REMBG_AVAILABLE else GREY
            save_btn.disabled   = True
        else:
            save_btn.disabled   = False
        undo_btn.disabled = len(state["history"]) == 0
        _render_preview()
        page.update()

    def on_rembg_model_toggle(e) -> None:
        """Bascule entre portrait et général."""
        state["rembg_human_seg"] = not state["rembg_human_seg"]
        # Invalider les sessions pour forcer le rechargement avec le bon modèle
        _session[0] = None
        _session_general[0] = None
        _session_u2net[0] = None
        _session_u2net_gen[0] = None
        if state["rembg_human_seg"]:
            _model_toggle_label.value = "Humain"
            model_toggle_btn.bgcolor  = VIOLET if REMBG_AVAILABLE else GREY
        else:
            _model_toggle_label.value = "Général"
            model_toggle_btn.bgcolor  = BLUE if REMBG_AVAILABLE else GREY
        model_toggle_btn.update()

    def on_rembg_precise_toggle(e) -> None:
        """Bascule entre mode rapide (u2net) et mode précis (birefnet)."""
        state["rembg_precise"] = not state["rembg_precise"]
        if state["rembg_precise"]:
            _precise_toggle_label.value = "Précis"
            precise_toggle_btn.bgcolor  = VIOLET if REMBG_AVAILABLE else GREY
        else:
            _precise_toggle_label.value = "Rapide"
            precise_toggle_btn.bgcolor  = BLUE if REMBG_AVAILABLE else GREY
        precise_toggle_btn.update()

    # Attacher les callbacks
    bg_radio.on_change         = on_bg_change
    model_toggle_btn.on_click   = on_rembg_model_toggle
    precise_toggle_btn.on_click = on_rembg_precise_toggle
    undo_btn.on_click          = on_undo
    ignore_btn.on_click        = on_ignore
    process_btn.on_click       = on_process
    run_model_btn.on_click     = on_run_model
    refresh_btn.on_click       = on_refresh_models
    save_btn.on_click          = on_save
    cancel_btn.on_click          = on_cancel
    erosion_slider.on_change     = on_erosion_slider_change
    erosion_slider.on_change_end = on_erosion_slider_end
    # ------------------------------------------------------------------ #
    #                           MISE EN PAGE                              #
    # ------------------------------------------------------------------ #
    left_panel = ft.Column(
        [
            # Fond
            ft.Text("Couleur de fond", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            bg_radio,
            ft.Divider(color=GREY),
            # Actions rembg
            process_btn,
            ft.Row([model_toggle_btn, precise_toggle_btn], spacing=6),
            # Érosion du masque
            ft.Row(
                [
                    ft.Text("Érosion", size=12, color=LIGHT_GREY),
                    erosion_slider,
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            progress_bar,
            ft.Divider(color=GREY),
            # Amélioration IA
            ft.Text("Amélioration IA", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Text("📂 Data/models/", size=10, color=LIGHT_GREY),
            ft.Row(
                [model_dropdown, refresh_btn, run_model_btn],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            enhance_progress_bar,
            cancel_btn,
            enhance_status,
            undo_btn,
            ft.Divider(color=GREY),
            ft.Row([save_btn, ignore_btn], spacing=8),
            ft.Container(expand=True),
            status_text,
        ],
        width=340,
        spacing=10,
    )

    center_panel = ft.Column(
        [
            ft.Row(
                [image_label, counter_text],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                content=ft.Stack([preview_placeholder, preview_img]),
                expand=True,
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
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
    if not ESRGAN_AVAILABLE:
        enhance_status.value = "spandrel non installé — pip install spandrel"

    if all_images:
        asyncio.create_task(_load_image(0))
    else:
        status_text.value = f"Aucune image trouvée dans : {source_folder}"
        page.update()




###############################################################
#                        POINT D'ENTRÉE                       #
###############################################################

if __name__ == "__main__":
    # Supprime le bruit Windows : ConnectionResetError [WinError 10054]
    # lors de la fermeture de l'app (bug connu du ProactorEventLoop).
    import sys
    if sys.platform == "win32":
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_call_connection_lost = _ProactorBasePipeTransport._call_connection_lost
        def _patched_call_connection_lost(self, exc):
            try:
                _orig_call_connection_lost(self, exc)
            except (ConnectionResetError, OSError):
                pass
        _ProactorBasePipeTransport._call_connection_lost = _patched_call_connection_lost

    ft.run(main)
