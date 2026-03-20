# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

  - Inpainting par IA (LaMa — Large Mask inpainting) : reconstruction cohérente
    des zones masquées au pinceau directement sur l'image (effacement d'objets,
    nettoyage de fond, suppression de filigranes…).
  - Suppression automatique du fond par IA (rembg / modèle ``u2net_human_seg``).
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
* torch        — moteur d'inférence requis par le LaMa inpainting intégré

Variables d'environnement reconnues
-------------------------------------
FOLDER_PATH    : dossier source des images (défaut : répertoire du script)
SELECTED_FILES : noms de fichiers séparés par « | » à traiter en priorité

Notes
-----
Au premier lancement, rembg télécharge automatiquement le modèle u2net_human_seg
(~175 Mo) dans ``~/.u2net/``. Les modèles spandrel (RealESRGAN, FaceUpSharpDAT)
sont téléchargés dans ``~/.cache/enhance_id/`` au premier usage (~350 Mo au total).

Version : 1.9.0
"""

__version__ = "1.9.0"

###############################################################
#                         IMPORTS                             #
###############################################################
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")
warnings.filterwarnings("ignore", message=".*torch.meshgrid.*indexing.*", category=UserWarning)

import flet as ft
import flet.canvas as _ftcv
import os
import io
import contextlib
import base64
import asyncio
import math
import time
import urllib.request
from PIL import Image, ImageFilter
import numpy as np

try:
    from rembg import remove as rembg_remove, new_session
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False

try:
    import torch as _torch
    from spandrel import ModelLoader as _ModelLoader
    ESRGAN_AVAILABLE = True
except Exception:
    ESRGAN_AVAILABLE = False

# ---- LaMa inpainting (implémentation directe, sans simple_lama_inpainting) ----
# Remplace le package simple_lama_inpainting qui impose numpy<2.0 incompatible
# avec Python 3.14+.  Seul torch (déjà requis par spandrel) est nécessaire.
_LAMA_MODEL_URL = (
    "https://github.com/enesmsahin/simple-lama-inpainting"
    "/releases/download/v0.1.0/big-lama.pt"
)
_LAMA_MODEL_CACHE = os.path.join(
    os.path.expanduser("~"), ".cache", "simple-lama", "big-lama.pt"
)


class _SimpleLama:
    """Wrapper LaMa minimal — remplace simple_lama_inpainting (numpy-version-agnostic)."""

    def __init__(self) -> None:
        import torch as _t
        if not os.path.exists(_LAMA_MODEL_CACHE):
            os.makedirs(os.path.dirname(_LAMA_MODEL_CACHE), exist_ok=True)
            urllib.request.urlretrieve(_LAMA_MODEL_URL, _LAMA_MODEL_CACHE)
        self._model = _t.jit.load(_LAMA_MODEL_CACHE, map_location="cpu")
        self._model.eval()

    @staticmethod
    def _pad(img_t, msk_t, factor: int = 8):
        """Padde H et W au multiple de `factor` le plus proche (requis par LaMa)."""
        import torch as _t
        _, _, h, w = img_t.shape
        ph = (factor - h % factor) % factor
        pw = (factor - w % factor) % factor
        if ph or pw:
            img_t = _t.nn.functional.pad(img_t, (0, pw, 0, ph), mode="reflect")
            msk_t = _t.nn.functional.pad(msk_t, (0, pw, 0, ph), mode="reflect")
        return img_t, msk_t, h, w

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        import torch as _t
        img = np.array(image.convert("RGB")).astype(np.float32) / 255.0
        msk = np.array(mask.convert("L")).astype(np.float32) / 255.0
        img_t = _t.from_numpy(img).permute(2, 0, 1).unsqueeze(0)           # [1,3,H,W]
        msk_t = (_t.from_numpy(msk) > 0).float().unsqueeze(0).unsqueeze(0) # [1,1,H,W]
        img_t, msk_t, orig_h, orig_w = self._pad(img_t, msk_t)
        with _t.no_grad():
            # La signature JIT est forward(Image: Tensor, mask: Tensor) -> Tensor
            out = self._model(img_t, msk_t)
        # Recadrer au format original si un padding a été ajouté
        res = out[0, :, :orig_h, :orig_w].permute(1, 2, 0).cpu().numpy()
        return Image.fromarray(np.clip(res * 255, 0, 255).astype(np.uint8))


try:
    import torch as _torch_lama_check  # noqa: F401
    LAMA_AVAILABLE = True
except ImportError:
    LAMA_AVAILABLE = False

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
BG_COLORS: dict[str, tuple[int, int, int]] = {
    "Blanc": (255, 255, 255),
    "Gris":  (200, 200, 200),
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
    page.window.height = 800

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
        "precise":         False,  # True = alpha matting précis pour rembg
        "working":         False,  # True pendant l'exécution de rembg
        "enhancing":       False,  # True pendant face SR ou ESRGAN
        "lama_running":    False,  # True pendant l'exécution de LaMa
        "rembg_applied":   False,  # True après suppression du fond par rembg
        "current_task":    None,   # asyncio.Task en cours (rembg ou modèle)
        "cancel_requested": False, # Annulation demandée (boucle de tuiles)
        # --- LaMa inpainting ---
        "mask_img":        None,   # PIL.Image "L" du masque courant (blanc = zone à effacer)
        "mask_mode":       False,  # True = mode dessin de masque actif
        "brush_size":      30,     # rayon du pinceau en pixels (espace widget)
        "pen_x":           0.0,    # position X courante du pointeur (espace widget)
        "pen_y":           0.0,    # position Y courante du pointeur (espace widget)
        "_last_stroke_x":  -9999.0, # position X du dernier cercle peint (espacement)
        "_last_stroke_y":  -9999.0, # position Y du dernier cercle peint (espacement)
        "container_w":       0.0,    # largeur réelle du conteneur image (mise à jour par on_size_change)
        "container_h":       0.0,    # hauteur réelle du conteneur image
        "_last_render_t":    0.0,    # horodatage du dernier rendu pinceau (throttle)
        "_preview_base":     None,   # PIL RGB thumbnail (≤700×700) sans masque — cache rapide
    }

    # Session rembg partagée
    _session: list = [None]
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

    # Overlay du masque LaMa : ft.canvas.Canvas — cercles vectoriels dessinés directement,
    # sans aucun encodage PIL/PNG/base64 → fluide même à haute fréquence de pointeur.
    mask_canvas = _ftcv.Canvas(shapes=[], expand=True)

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

    precise_switch = ft.Switch(
        label="Précis",
        active_color=VIOLET,
        value=False,
        tooltip="Alpha matting précis (plus lent, meilleur détourage sur cheveux/bords fins)",
        disabled=not REMBG_AVAILABLE,
    )

    bg_radio = ft.RadioGroup(
        content=ft.Column(
            [ft.Radio(value=k, label=k, fill_color=BLUE) for k in BG_COLORS]
            + [ft.Radio(value="Flou", label="Flou", fill_color=BLUE)],
            spacing=4,
        ),
        value="Blanc",
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

    process_btn = ft.Button(
        "Supprimer le fond (IA)",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=VIOLET if REMBG_AVAILABLE else GREY,
        color=DARK,
        disabled=not REMBG_AVAILABLE,
    )
    save_btn = ft.Button(
        "Enregistrer",
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

    # ---- LaMa inpainting ---- #
    lama_mask_btn = ft.FilledButton(
        "Dessiner le masque",
        icon=ft.Icons.BRUSH,
        style=ft.ButtonStyle(
            bgcolor=ORANGE if LAMA_AVAILABLE else GREY,
            color=DARK,
        ),
        disabled=not LAMA_AVAILABLE,
        tooltip="Activer/désactiver le mode pinceau pour marquer les zones à reconstruire",
    )
    lama_clear_btn = ft.IconButton(
        icon=ft.Icons.LAYERS_CLEAR,
        icon_color=WHITE,
        bgcolor=GREY,
        tooltip="Effacer le masque",
        disabled=True,
    )
    lama_run_btn = ft.FilledButton(
        "Reconstruire (LaMa)",
        icon=ft.Icons.AUTO_FIX_HIGH,
        style=ft.ButtonStyle(
            bgcolor=GREEN if LAMA_AVAILABLE else GREY,
            color=DARK,
        ),
        disabled=True,
        tooltip="Reconstruire les zones masquées avec LaMa",
    )
    brush_slider = ft.Slider(
        min=5, max=120, value=30, divisions=23,
        active_color=ORANGE,
        inactive_color=GREY,
        label="{value}px",
        expand=True,
        disabled=not LAMA_AVAILABLE,
    )
    lama_status = ft.Text("", size=11, color=LIGHT_GREY)
    lama_progress_bar = ft.ProgressBar(color=ORANGE, bgcolor=GREY, visible=False)

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
        """Render complet : applique le fond + thumbnail + cache. Ne bake pas le masque."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return
        bg_rgb = None if state["bg_blur"] else BG_COLORS[state["bg_color"]]
        rgb = apply_background(base, bg_rgb, state["orig_img"])
        display = rgb.copy()
        display.thumbnail((700, 700), Image.Resampling.BILINEAR)
        # Mettre en cache le thumbnail propre pour les renders rapides du masque
        state["_preview_base"] = display.copy()
        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(display)}"
        preview_img.visible = True
        preview_placeholder.visible = False
        save_btn.disabled = state["processed"] is None
        # Mettre à jour l'overlay si un masque existe déjà
        if state.get("mask_img") is None:
            mask_canvas.shapes.clear()
        # (si mask_img existe, mask_canvas a déjà les cercles — rien à faire)
        page.update()

    def _refresh_mask_overlay() -> None:
        """Rafraîchit l'overlay masque. Avec ft.canvas.Canvas, les cercles sont déjà
        présents depuis le dessin — aucune re-encodage nécessaire.
        """
        # No-op : mask_canvas.shapes est la source de vérité, toujours à jour.
        pass

    def _apply_mask_overlay(base_thumb: Image.Image, mask: Image.Image) -> Image.Image:
        """Compose l'overlay rouge du masque sur le thumbnail (utilisé dans les autres contextes)."""
        m = mask.resize(base_thumb.size, Image.Resampling.NEAREST).convert("L")
        m_arr = np.array(m).astype(np.float32) / 255.0
        d_arr = np.array(base_thumb.convert("RGB")).astype(np.float32)
        alpha = m_arr[..., np.newaxis] * 0.55
        d_arr = d_arr * (1.0 - alpha) + np.array([220, 50, 50], dtype=np.float32) * alpha
        return Image.fromarray(d_arr.clip(0, 255).astype(np.uint8), "RGB")

    async def _render_preview_fast() -> None:
        """Render rapide pendant le pinceau : met à jour le canvas vectoriel (aucun encodage image)."""
        mask_canvas.update()

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

            state["orig_img"]       = img
            state["processed"]     = None
            state["index"]         = index
            state["rembg_applied"] = False
            state["mask_img"]      = None
            state["mask_mode"]     = False
            state["_preview_base"] = None  # invalider le cache
            mask_canvas.shapes.clear()

            process_btn.text    = "Supprimer le fond (IA)"
            process_btn.bgcolor = VIOLET if REMBG_AVAILABLE else GREY
            image_label.value   = os.path.basename(path)
            counter_text.value  = f"{index + 1} / {len(all_images)}"
            prev_btn.disabled   = index == 0
            next_btn.disabled   = index == len(all_images) - 1
            save_btn.disabled   = True
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
            state["enhancing"]      = False
            state["current_task"]   = None
            cancel_btn.visible      = False
            _set_all_ia_btns(False)
            run_model_btn.disabled  = not _list_pth_models()
            page.update()
            _render_preview()

    async def on_cancel(e) -> None:
        """Annule le traitement IA en cours (rembg ou modèle)."""
        state["cancel_requested"] = True
        task = state.get("current_task")
        if task and not task.done():
            task.cancel()

    def on_precise_toggle(e) -> None:
        """Active/désactive le mode précis (alpha matting) pour rembg."""
        state["precise"] = bool(e.control.value)

    def on_bg_change(e) -> None:
        """Met à jour la couleur de fond sélectionnée et rafraîchit la preview."""
        val = e.control.value
        if val == "Flou":
            state["bg_blur"] = True
        else:
            state["bg_blur"]  = False
            state["bg_color"] = val
        _render_preview()

    def on_prev(e) -> None:
        """Charge l'image précédente dans la liste."""
        _load_image(state["index"] - 1)

    def on_next(e) -> None:
        """Charge l'image suivante dans la liste."""
        _load_image(state["index"] + 1)

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
            if _session[0] is None:
                _session[0] = new_session("u2net_human_seg")
            buf = io.BytesIO()
            state["orig_img"].save(buf, format="PNG")
            buf.seek(0)
            kwargs = {"session": _session[0]}
            if state["precise"]:
                kwargs.update({
                    "alpha_matting": True,
                    "alpha_matting_foreground_threshold": 240,
                    "alpha_matting_background_threshold": 10,
                    "alpha_matting_erode_size": 10,
                })
            with contextlib.redirect_stderr(io.StringIO()):
                result_bytes = rembg_remove(buf.getvalue(), **kwargs)
            img = Image.open(io.BytesIO(result_bytes)).convert("RGBA")
            if not state["precise"]:
                # Érosion du canal alpha pour supprimer le liseré semi-transparent
                # MinFilter exige une taille impaire
                r, g, b, a = img.split()
                a = a.filter(ImageFilter.MinFilter(13))
                img = Image.merge("RGBA", (r, g, b, a))
            return img

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

    def on_save(e) -> None:
        """Exporte l'image traitée (fond appliqué) dans un sous-dossier OK."""
        if state["processed"] is None:
            status_text.value = "[ATTENTION] Appliquez d'abord une amélioration IA avant d'enregistrer"
            page.update()
            return

        bg_rgb    = None if state["bg_blur"] else BG_COLORS[state["bg_color"]]
        final_img = apply_background(state["processed"], bg_rgb, state["orig_img"])

        src_path = all_images[state["index"]]
        stem     = os.path.splitext(os.path.basename(src_path))[0]
        base_dir = os.path.join(os.path.dirname(src_path), "OK")
        filename = f"OK_{stem}.jpg"

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

            final_img.save(out_path, format="JPEG", dpi=(DPI, DPI), quality=100)
            status_text.value = f"[OK] OK → {os.path.basename(out_path)}"

            if state["index"] + 1 < len(all_images):
                _load_image(state["index"] + 1)
            else:
                page.update()

        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
            page.update()

    # ------------------------------------------------------------------ #
    #                        LAMA INPAINTING                              #
    # ------------------------------------------------------------------ #

    # Cache du modèle LaMa (chargé une seule fois)
    _lama_model: list = [None]

    def _thumb_coords_from_pointer(local_x: float, local_y: float) -> "tuple[int, int] | None":
        """
        Convertit les coordonnées du pointeur en pixels du masque thumbnail.
        Travaille à la résolution du cache _preview_base (≤700px) pour la fluidité.
        """
        cache = state.get("_preview_base")
        if cache is None:
            return None
        pw = state["container_w"]
        ph = state["container_h"]
        if pw < 10 or ph < 10:
            pw = max((page.window.width  or 1024) - 410, 200)
            ph = max((page.window.height or  720) - 100, 200)
        tw, th = cache.size
        ratio  = min(pw / tw, ph / th)
        disp_w = tw * ratio
        disp_h = th * ratio
        px = local_x / disp_w * tw
        py = local_y / disp_h * th
        if not (0 <= px < tw and 0 <= py < th):
            return None
        return int(px), int(py)

    def _paint_stroke(widget_x: float, widget_y: float, force_render: bool = False) -> bool:
        """
        Dessine un trait de pinceau :
        - Sur le canvas vectoriel (widget coords) → rendu immédiat, zéro encodage.
        - Sur le masque PIL basse résolution (thumbnail coords) → pour l'inférence LaMa.
        """
        cache = state.get("_preview_base")
        if cache is None:
            return False
        tw, th = cache.size
        # Coordonnées dans l'espace thumbnail (vérification des bornes incluse)
        pw = state["container_w"]
        ph = state["container_h"]
        if pw < 10 or ph < 10:
            pw = max((page.window.width  or 1024) - 410, 200)
            ph = max((page.window.height or  720) - 100, 200)
        ratio  = min(pw / tw, ph / th)
        disp_w = tw * ratio
        disp_h = th * ratio
        px = widget_x / disp_w * tw
        py = widget_y / disp_h * th
        if not (0 <= px < tw and 0 <= py < th):
            return False  # hors image : ne rien dessiner
        brush_r = state["brush_size"]
        # Espacement : ne peindre un nouveau cercle que si le pointeur a avancé
        # d'au moins la moitié du rayon depuis le dernier coup de pinceau.
        min_dist = max(2.0, brush_r * 0.5)
        dx = widget_x - state["_last_stroke_x"]
        dy = widget_y - state["_last_stroke_y"]
        if not force_render and (dx * dx + dy * dy) < min_dist * min_dist:
            return False
        state["_last_stroke_x"] = widget_x
        state["_last_stroke_y"] = widget_y
        # 1. Canvas vectoriel : cercle en coordonnées widget — aucun encodage
        mask_canvas.shapes.append(
            _ftcv.Circle(
                x=widget_x, y=widget_y, radius=brush_r,
                paint=ft.Paint(
                    color=ft.Colors.with_opacity(0.55, "#DC3232"),
                    style=ft.PaintingStyle.FILL,
                ),
            )
        )
        # 2. Masque PIL (thumbnail resolution) : pour l'inférence LaMa
        if state["mask_img"] is None:
            state["mask_img"] = Image.new("L", (tw, th), 0)
        elif state["mask_img"].size != (tw, th):
            state["mask_img"] = state["mask_img"].resize((tw, th), Image.Resampling.NEAREST)
        radius_pil = max(2, int(brush_r * tw / disp_w))
        from PIL import ImageDraw
        draw = ImageDraw.Draw(state["mask_img"])
        draw.ellipse(
            [int(px) - radius_pil, int(py) - radius_pil,
             int(px) + radius_pil, int(py) + radius_pil],
            fill=255,
        )
        lama_run_btn.disabled   = False
        lama_clear_btn.disabled = False
        now = time.monotonic()
        if force_render or (now - state["_last_render_t"] >= 0.03):
            state["_last_render_t"] = now
            return True
        return False

    def on_brush_size_change(e) -> None:
        state["brush_size"] = int(e.control.value)

    def on_lama_toggle_mask(e) -> None:
        """Active / désactive le mode pinceau."""
        if not LAMA_AVAILABLE:
            return
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            lama_status.value = "Chargez d'abord une image."
            page.update()
            return
        state["mask_mode"] = not state["mask_mode"]
        if state["mask_mode"]:
            lama_mask_btn.text = "Arrêter le pinceau"
            lama_mask_btn.icon = ft.Icons.STOP_CIRCLE_OUTLINED
            lama_status.value  = "Mode pinceau actif — cliquez/glissez sur l'image"
        else:
            lama_mask_btn.text = "Dessiner le masque"
            lama_mask_btn.icon = ft.Icons.BRUSH
            lama_status.value  = ""
        page.update()

    def on_lama_clear_mask(e) -> None:
        """Efface le masque courant."""
        state["mask_img"]        = None
        state["mask_mode"]       = False
        lama_mask_btn.text       = "Dessiner le masque"
        lama_mask_btn.icon       = ft.Icons.BRUSH
        lama_run_btn.disabled    = True
        lama_clear_btn.disabled  = True
        lama_status.value        = "Masque effacé"
        mask_canvas.shapes.clear()
        mask_canvas.update()
        _render_preview()

    async def on_preview_pan_down(e: ft.DragDownEvent) -> None:
        """Capture la position initiale du stylo/doigt (avant le pan)."""
        if not state["mask_mode"]:
            return
        lp = getattr(e, "local_position", None)
        if lp is not None:
            state["pen_x"] = float(lp.x)
            state["pen_y"] = float(lp.y)

    async def on_preview_pan_start(e: ft.DragStartEvent) -> None:
        if not state["mask_mode"]:
            return
        # Réinitialiser la position du dernier cercle pour peindre dès le premier point
        state["_last_stroke_x"] = -9999.0
        state["_last_stroke_y"] = -9999.0
        if _paint_stroke(state["pen_x"], state["pen_y"]):
            await _render_preview_fast()

    async def on_preview_pan_update(e: ft.DragUpdateEvent) -> None:
        if not state["mask_mode"]:
            return
        lp = getattr(e, "local_position", None)
        if lp is not None:
            state["pen_x"] = float(lp.x)
            state["pen_y"] = float(lp.y)
        elif e.local_delta:
            state["pen_x"] += e.local_delta.x
            state["pen_y"] += e.local_delta.y
        if _paint_stroke(state["pen_x"], state["pen_y"]):
            await _render_preview_fast()

    async def on_preview_pan_end(e) -> None:
        """Fin du glisser : rendu final forcé."""
        if not state["mask_mode"] or state["mask_img"] is None:
            return
        state["_last_render_t"] = 0.0
        await _render_preview_fast()

    async def on_preview_tap(e: ft.TapEvent) -> None:
        if not state["mask_mode"]:
            return
        lx, ly = e.local_position.x, e.local_position.y
        state["pen_x"] = lx
        state["pen_y"] = ly
        coords = _thumb_coords_from_pointer(lx, ly)
        if coords:
            state["_last_render_t"] = 0.0
            state["_last_stroke_x"] = -9999.0
            state["_last_stroke_y"] = -9999.0
            _paint_stroke(lx, ly, force_render=True)
            await _render_preview_fast()
        else:
            lama_status.value = (
                f"clic ({lx:.0f},{ly:.0f}) hors image "
                f"(container {state['container_w']:.0f}×{state['container_h']:.0f})"
            )
            page.update()

    async def on_run_lama(e) -> None:
        """Lance la reconstruction LaMa sur les zones masquées."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        mask = state["mask_img"]
        if base is None or mask is None or state["lama_running"]:
            return

        state["lama_running"]     = True
        lama_run_btn.disabled     = True
        lama_mask_btn.disabled    = True
        lama_clear_btn.disabled   = True
        lama_progress_bar.value   = None
        lama_progress_bar.visible = True
        lama_status.value         = "Préparation…"
        page.update()

        _t0 = time.monotonic()

        def _set_status(msg: str) -> None:
            lama_status.value = msg
            page.update()

        def _do_lama():
            # Étape 1 : chargement du modèle (si premier lancement)
            if _lama_model[0] is None:
                _set_status("Chargement du modèle LaMa…")
                _lama_model[0] = _SimpleLama()
            # Étape 2 : prétraitement
            _set_status("Prétraitement de l'image…")
            rgb_img = base.convert("RGB")
            # Le masque est stocké à la résolution du thumbnail — upscaler à la pleine résolution
            m = mask.convert("L")
            if m.size != rgb_img.size:
                m = m.resize(rgb_img.size, Image.Resampling.LANCZOS)
            # Étape 3 : inférence (unique forward pass — durée variable selon taille)
            _set_status(f"Reconstruction IA ({rgb_img.width}×{rgb_img.height} px)…")
            result = _lama_model[0](rgb_img, m)
            return result

        lama_task = asyncio.create_task(asyncio.to_thread(_do_lama))
        try:
            result = await lama_task
            if base.mode == "RGBA":
                result = result.convert("RGBA")
                result.putalpha(base.split()[3])
            state["processed"]       = result
            state["mask_img"]       = None
            state["mask_mode"]      = False
            mask_canvas.shapes.clear()
            lama_mask_btn.text      = "Dessiner le masque"
            lama_mask_btn.icon      = ft.Icons.BRUSH
            lama_clear_btn.disabled = True
            lama_run_btn.disabled   = True
            lama_status.value       = f"[OK] Reconstruction terminée ({time.monotonic() - _t0:.1f} s)"
            save_btn.disabled       = False
        except Exception as ex:
            lama_status.value = f"[ERREUR] LaMa : {ex}"
        finally:
            lama_progress_bar.visible = False
            state["lama_running"]     = False
            lama_mask_btn.disabled    = not LAMA_AVAILABLE
            page.update()
            _render_preview()

    # Attacher les callbacks
    precise_switch.on_change   = on_precise_toggle
    bg_radio.on_change         = on_bg_change
    prev_btn.on_click          = on_prev
    next_btn.on_click          = on_next
    process_btn.on_click       = on_process
    run_model_btn.on_click     = on_run_model
    refresh_btn.on_click       = on_refresh_models
    save_btn.on_click          = on_save
    cancel_btn.on_click        = on_cancel
    lama_mask_btn.on_click     = on_lama_toggle_mask
    lama_clear_btn.on_click    = on_lama_clear_mask
    lama_run_btn.on_click      = on_run_lama
    brush_slider.on_change     = on_brush_size_change

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
            ft.Row([process_btn, precise_switch], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
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
            ft.Divider(color=GREY),
            # Inpainting LaMa
            ft.Text("Inpainting LaMa", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Text("Pinceau → Taille", size=10, color=LIGHT_GREY),
            ft.Row([brush_slider], spacing=4),
            ft.Row(
                [lama_mask_btn, lama_clear_btn],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            lama_progress_bar,
            lama_run_btn,
            lama_status,
            ft.Divider(color=GREY),
            save_btn,
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
                content=ft.GestureDetector(
                    content=ft.Stack([preview_placeholder, preview_img, mask_canvas]),
                    on_pan_down=on_preview_pan_down,
                    on_pan_start=on_preview_pan_start,
                    on_pan_update=on_preview_pan_update,
                    on_pan_end=on_preview_pan_end,
                    on_tap_down=on_preview_tap,
                ),
                expand=True,
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                on_size_change=lambda e: state.update({
                    "container_w": float(e.width  or state["container_w"]),
                    "container_h": float(e.height or state["container_h"]),
                }),
            ),
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
    if not ESRGAN_AVAILABLE:
        enhance_status.value = "spandrel non installé — pip install spandrel"

    if all_images:
        _load_image(0)
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
