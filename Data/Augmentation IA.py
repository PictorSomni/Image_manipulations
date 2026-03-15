# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

  - Suppression automatique du fond par IA (rembg / modèle ``u2net_human_seg``).
  - Restauration du visage par IA (GFPGAN v1.4) :
    amélioration des détails du visage, réduction des flous et artefacts.
  - Agrandissement ×4 par super-résolution (Real-ESRGAN) :
    upscaling haute qualité sans perte de détails.
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
* gfpgan       — restauration du visage (``pip install gfpgan``)
* realesrgan   — super-résolution ×4 (``pip install realesrgan``)
* torch        — moteur d'inférence PyTorch requis par gfpgan / realesrgan

Variables d'environnement reconnues
-------------------------------------
FOLDER_PATH    : dossier source des images (défaut : répertoire du script)
SELECTED_FILES : noms de fichiers séparés par « | » à traiter en priorité

Notes
-----
Au premier lancement, rembg télécharge automatiquement le modèle u2net_human_seg
(~175 Mo) dans ``~/.u2net/``. GFPGAN et Real-ESRGAN téléchargent leurs modèles
dans ``~/.cache/enhance_id/`` au premier usage (~350 Mo au total).

Version : 1.2.0
"""

__version__ = "1.2.0"

###############################################################
#                         IMPORTS                             #
###############################################################
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="torchvision")

import flet as ft
import os
import io
import sys
import types
import base64
import asyncio
import urllib.request
from PIL import Image
import numpy as np

# --- Monkey-patch : compatibilité basicsr avec torchvision ≥ 0.17 ---
# basicsr importe torchvision.transforms.functional_tensor (supprimé en 0.17).
try:
    import torchvision.transforms.functional as _tvF
    _ft_compat = types.ModuleType("torchvision.transforms.functional_tensor")
    _ft_compat.rgb_to_grayscale = _tvF.rgb_to_grayscale
    sys.modules.setdefault("torchvision.transforms.functional_tensor", _ft_compat)
except ImportError:
    pass

try:
    from rembg import remove as rembg_remove, new_session
    REMBG_AVAILABLE = True
except ImportError:
    REMBG_AVAILABLE = False

try:
    from gfpgan import GFPGANer as _GFPGANer
    GFPGAN_AVAILABLE = True
except Exception:
    GFPGAN_AVAILABLE = False

try:
    from realesrgan import RealESRGANer as _RealESRGANer
    from basicsr.archs.rrdbnet_arch import RRDBNet as _RRDBNet
    ESRGAN_AVAILABLE = True
except Exception:
    ESRGAN_AVAILABLE = False

###############################################################
#                       CONFIGURATION                         #
###############################################################

DPI = 300  # Résolution d'export (points par pouce)

# ---- Modèles IA (téléchargement automatique au premier usage) ----
_MODELS_DIR       = os.path.join(os.path.expanduser("~"), ".cache", "enhance_id")
GFPGAN_MODEL_URL  = "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.4/GFPGANv1.4.pth"
GFPGAN_MODEL_PATH = os.path.join(_MODELS_DIR, "GFPGANv1.4.pth")
ESRGAN_MODEL_URL    = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
ESRGAN_MODEL_PATH   = os.path.join(_MODELS_DIR, "RealESRGAN_x4plus.pth")
ESRGAN_X2_MODEL_URL  = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth"
ESRGAN_X2_MODEL_PATH = os.path.join(_MODELS_DIR, "RealESRGAN_x2plus.pth")
os.makedirs(_MODELS_DIR, exist_ok=True)

# Couleurs de fond disponibles (nom affiché → valeur RGB)
BG_COLORS: dict[str, tuple[int, int, int]] = {
    "Blanc":      (255, 255, 255),
    "Gris clair": (210, 210, 210),
    "Noir":       (0, 0, 0),
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


def _ensure_model(url: str, path: str) -> None:
    """Télécharge le modèle IA si absent du cache local (~/.cache/enhance_id/)."""
    if not os.path.exists(path):
        tmp = path + ".part"
        urllib.request.urlretrieve(url, tmp)
        os.rename(tmp, path)


def _pil_to_bgr(img: Image.Image) -> np.ndarray:
    """Convertit une image PIL RGB/RGBA en tableau numpy BGR pour GFPGAN/ESRGAN."""
    return np.array(img.convert("RGB"))[:, :, ::-1].copy()


def _bgr_to_pil(arr: np.ndarray) -> Image.Image:
    """Convertit un tableau numpy BGR en image PIL RGB."""
    return Image.fromarray(arr[:, :, ::-1])


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
    page.title = f"Préparation photo ID  v{__version__}"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_UI
    page.window.width = 1024
    page.window.height = 600
    page.window.min_width = 720
    page.window.min_height = 560

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
        "index":     0,      # Indice de l'image affichée dans all_images
        "orig_img":  None,   # PIL.Image chargée depuis le disque
        "processed": None,   # PIL.Image RGBA retournée par rembg (ou None)
        "bg_color":  "Blanc",
        "working":   False,  # True pendant l'exécution de rembg
        "enhancing": False,  # True pendant GFPGAN ou ESRGAN
    }

    # Session rembg partagée
    _session: list = [None]
    # Instances GFPGAN et ESRGAN (initialisation différée au premier usage).
    _gfpgan_rstr:    list = [None]
    _esrgan_x4_upsr: list = [None]
    _esrgan_x2_upsr: list = [None]

    # ------------------------------------------------------------------ #
    #                        ÉLÉMENTS UI                                  #
    # ------------------------------------------------------------------ #
    status_text      = ft.Text("", size=12, color=LIGHT_GREY)
    image_label      = ft.Text("—", size=13, color=WHITE, text_align=ft.TextAlign.CENTER, expand=True)
    counter_text     = ft.Text("", size=12, color=LIGHT_GREY)
    progress_ring    = ft.ProgressRing(width=18, height=18, stroke_width=2, color=BLUE, visible=False)

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
            [ft.Radio(value=k, label=k, fill_color=BLUE) for k in BG_COLORS],
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

    esrgan_x2_btn = ft.Button(
        "Agrandir ×2 (ESRGAN)",
        icon=ft.Icons.HD,
        bgcolor=ORANGE if ESRGAN_AVAILABLE else GREY,
        color=DARK if ESRGAN_AVAILABLE else LIGHT_GREY,
        disabled=not ESRGAN_AVAILABLE,
        tooltip=(
            "Super-résolution ×2 avec Real-ESRGAN"
            if ESRGAN_AVAILABLE
            else "pip install realesrgan"
        ),
    )
    esrgan_x4_btn = ft.Button(
        "Agrandir ×4 (ESRGAN)",
        icon=ft.Icons.HD,
        bgcolor=ORANGE if ESRGAN_AVAILABLE else GREY,
        color=DARK if ESRGAN_AVAILABLE else LIGHT_GREY,
        disabled=not ESRGAN_AVAILABLE,
        tooltip=(
            "Super-résolution ×4 avec Real-ESRGAN"
            if ESRGAN_AVAILABLE
            else "pip install realesrgan"
        ),
    )
    gfpgan_btn = ft.Button(
        "Restaurer visage (GFPGAN)",
        icon=ft.Icons.FACE_RETOUCHING_NATURAL,
        bgcolor=BLUE if GFPGAN_AVAILABLE else GREY,
        color=DARK,
        disabled=not GFPGAN_AVAILABLE,
        tooltip=(
            "Restaure les détails du visage avec GFPGAN v1.4"
            if GFPGAN_AVAILABLE
            else "pip install gfpgan"
        ),
    )
    enhance_progress = ft.ProgressRing(
        width=16, height=16, stroke_width=2, color=BLUE, visible=False,
    )
    enhance_status = ft.Text("", size=11, color=LIGHT_GREY)

    # ------------------------------------------------------------------ #
    #                         RENDU PREVIEW                               #
    # ------------------------------------------------------------------ #
    def _render_preview() -> None:
        """Génère l'image (fond appliqué) et actualise la prévisualisation."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return
        bg_rgb = BG_COLORS[state["bg_color"]]
        rgb = apply_background(base, bg_rgb)
        display = rgb.copy()
        display.thumbnail((700, 700), Image.Resampling.BILINEAR)
        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(display)}"
        preview_img.visible = True
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

            image_label.value  = os.path.basename(path)
            counter_text.value = f"{index + 1} / {len(all_images)}"
            prev_btn.disabled  = index == 0
            next_btn.disabled  = index == len(all_images) - 1
            save_btn.disabled  = True
            status_text.value  = ""

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

        state["working"]      = True
        process_btn.disabled  = True
        save_btn.disabled     = True
        progress_ring.visible = True
        status_text.value     = "Traitement IA en cours…"
        page.update()

        def _do_rembg():
            if _session[0] is None:
                _session[0] = new_session("u2net_human_seg")
            buf = io.BytesIO()
            state["orig_img"].save(buf, format="PNG")
            buf.seek(0)
            result_bytes = rembg_remove(buf.getvalue(), session=_session[0])
            return Image.open(io.BytesIO(result_bytes)).convert("RGBA")

        try:
            result = await asyncio.to_thread(_do_rembg)
            state["processed"] = result
            status_text.value  = "[OK] Fond supprimé"
        except Exception as ex:
            status_text.value = f"[ERREUR] rembg : {ex}"
        finally:
            state["working"]      = False
            process_btn.disabled  = False
            progress_ring.visible = False
            _render_preview()

    async def on_gfpgan(e) -> None:
        """Restaure le visage de l'image courante avec GFPGAN via asyncio.to_thread."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None or state["enhancing"]:
            return

        def _set_all_ia_btns(disabled: bool) -> None:
            gfpgan_btn.disabled  = disabled
            esrgan_x2_btn.disabled = disabled
            esrgan_x4_btn.disabled = disabled

        state["enhancing"]        = True
        _set_all_ia_btns(True)
        enhance_progress.visible  = True
        enhance_status.value      = "Restauration du visage (GFPGAN)…"
        page.update()

        has_alpha = (base.mode == "RGBA")
        alpha     = base.split()[3] if has_alpha else None

        def _do_gfpgan():
            _ensure_model(GFPGAN_MODEL_URL, GFPGAN_MODEL_PATH)
            if _gfpgan_rstr[0] is None:
                _gfpgan_rstr[0] = _GFPGANer(
                    model_path=GFPGAN_MODEL_PATH,
                    upscale=1,
                    arch="clean",
                    channel_multiplier=2,
                    bg_upsampler=None,
                )
            _, _, out_bgr = _gfpgan_rstr[0].enhance(
                _pil_to_bgr(base), has_aligned=False, only_center_face=False, paste_back=True
            )
            out = _bgr_to_pil(out_bgr)
            if has_alpha and alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha if alpha.size == out.size else alpha.resize(out.size, Image.Resampling.LANCZOS))
            return out

        try:
            result = await asyncio.to_thread(_do_gfpgan)
            state["processed"] = result
            enhance_status.value = "[OK] Visage restauré (GFPGAN)"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] GFPGAN : {ex}"
        finally:
            state["enhancing"]        = False
            _set_all_ia_btns(False)
            enhance_progress.visible  = False
            _render_preview()

    async def on_esrgan_x2(e) -> None:
        """Agrandit l'image ×2 avec Real-ESRGAN x2plus via asyncio.to_thread."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None or state["enhancing"]:
            return

        def _set_all_ia_btns(disabled: bool) -> None:
            gfpgan_btn.disabled    = disabled
            esrgan_x2_btn.disabled = disabled
            esrgan_x4_btn.disabled = disabled

        state["enhancing"]       = True
        _set_all_ia_btns(True)
        enhance_progress.visible = True
        enhance_status.value     = "Agrandissement ×2 (Real-ESRGAN)…"
        page.update()

        has_alpha = (base.mode == "RGBA")
        alpha     = base.split()[3] if has_alpha else None

        def _do_esrgan_x2():
            _ensure_model(ESRGAN_X2_MODEL_URL, ESRGAN_X2_MODEL_PATH)
            if _esrgan_x2_upsr[0] is None:
                model = _RRDBNet(
                    num_in_ch=3, num_out_ch=3, num_feat=64,
                    num_block=23, num_grow_ch=32, scale=2,
                )
                _esrgan_x2_upsr[0] = _RealESRGANer(
                    scale=2,
                    model_path=ESRGAN_X2_MODEL_PATH,
                    model=model,
                    tile=256,
                    tile_pad=10,
                    pre_pad=0,
                    half=False,
                )
            out_bgr, _ = _esrgan_x2_upsr[0].enhance(_pil_to_bgr(base), outscale=2)
            out = _bgr_to_pil(out_bgr)
            if has_alpha and alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha.resize(out.size, Image.Resampling.LANCZOS))
            return out

        try:
            result = await asyncio.to_thread(_do_esrgan_x2)
            state["processed"] = result
            enhance_status.value = f"[OK] Image ×2 ({result.width}×{result.height} px)"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] ESRGAN x2 : {ex}"
        finally:
            state["enhancing"]       = False
            _set_all_ia_btns(False)
            enhance_progress.visible = False
            _render_preview()

    async def on_esrgan_x4(e) -> None:
        """Agrandit l'image ×4 avec Real-ESRGAN x4plus via asyncio.to_thread."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None or state["enhancing"]:
            return

        def _set_all_ia_btns(disabled: bool) -> None:
            gfpgan_btn.disabled    = disabled
            esrgan_x2_btn.disabled = disabled
            esrgan_x4_btn.disabled = disabled

        state["enhancing"]       = True
        _set_all_ia_btns(True)
        enhance_progress.visible = True
        enhance_status.value     = "Agrandissement ×4 (Real-ESRGAN)…"
        page.update()

        has_alpha = (base.mode == "RGBA")
        alpha     = base.split()[3] if has_alpha else None

        def _do_esrgan_x4():
            _ensure_model(ESRGAN_MODEL_URL, ESRGAN_MODEL_PATH)
            if _esrgan_x4_upsr[0] is None:
                model = _RRDBNet(
                    num_in_ch=3, num_out_ch=3, num_feat=64,
                    num_block=23, num_grow_ch=32, scale=4,
                )
                _esrgan_x4_upsr[0] = _RealESRGANer(
                    scale=4,
                    model_path=ESRGAN_MODEL_PATH,
                    model=model,
                    tile=256,
                    tile_pad=10,
                    pre_pad=0,
                    half=False,
                )
            out_bgr, _ = _esrgan_x4_upsr[0].enhance(_pil_to_bgr(base), outscale=4)
            out = _bgr_to_pil(out_bgr)
            if has_alpha and alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha.resize(out.size, Image.Resampling.LANCZOS))
            return out

        try:
            result = await asyncio.to_thread(_do_esrgan_x4)
            state["processed"] = result
            enhance_status.value = f"[OK] Image ×4 ({result.width}×{result.height} px)"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] ESRGAN x4 : {ex}"
        finally:
            state["enhancing"]       = False
            _set_all_ia_btns(False)
            enhance_progress.visible = False
            _render_preview()

    def on_save(e) -> None:
        """Exporte l'image traitée (fond appliqué) dans un sous-dossier OK."""
        if state["processed"] is None:
            status_text.value = "[ATTENTION] Appliquez d'abord une amélioration IA avant d'enregistrer"
            page.update()
            return

        bg_rgb    = BG_COLORS[state["bg_color"]]
        final_img = apply_background(state["processed"], bg_rgb)

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

    # Attacher les callbacks
    bg_radio.on_change         = on_bg_change
    prev_btn.on_click          = on_prev
    next_btn.on_click          = on_next
    process_btn.on_click       = on_process
    gfpgan_btn.on_click        = on_gfpgan
    esrgan_x2_btn.on_click     = on_esrgan_x2
    esrgan_x4_btn.on_click     = on_esrgan_x4
    save_btn.on_click          = on_save

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
            ft.Row([process_btn, progress_ring], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Divider(color=GREY),
            # Améliorations IA
            ft.Text("Amélioration IA", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            esrgan_x2_btn,
            esrgan_x4_btn,
            ft.Row([gfpgan_btn, enhance_progress], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            enhance_status,
            ft.Divider(color=GREY),
            save_btn,
            ft.Container(expand=True),
            status_text,
        ],
        width=300,
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
    if not GFPGAN_AVAILABLE:
        enhance_status.value = "gfpgan non installé — pip install gfpgan"
    elif not ESRGAN_AVAILABLE:
        enhance_status.value = "realesrgan non installé — pip install realesrgan"

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
