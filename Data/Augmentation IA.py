# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

  - Suppression automatique du fond par IA (rembg / modèle ``birefnet-portrait``).
  - Sélection interactive par clic via SAM2 (Segment Anything Model 2) :
    clics positifs / négatifs — peut remplacer rembg pour une découpe précise.
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

"""

__version__ = "2.0.3"

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
SAM2_AVAILABLE = (
    importlib.util.find_spec("torch")   is not None
    and importlib.util.find_spec("sam2") is not None
)
CV2_AVAILABLE   = importlib.util.find_spec("cv2")     is not None
IOPAINT_AVAILABLE = importlib.util.find_spec("iopaint") is not None


def _pick_torch_device() -> str:
    """Détecte le meilleur device PyTorch disponible et configure torch au premier appel.

    Effets de bord (premier appel uniquement) :
      • cudnn.benchmark = True            — autotune cuDNN (gain 10-30 % CUDA)
      • set_float32_matmul_precision      — TF32 sur Ampere+, accélère aussi MPS
      • mps fallback pour ops manquantes  — évite les NotImplementedError sur MPS
    """
    import torch as _t
    if not hasattr(_pick_torch_device, "_configured"):
        if hasattr(_t, "set_float32_matmul_precision"):
            _t.set_float32_matmul_precision("high")
        try:
            _t.backends.cudnn.benchmark = True
        except Exception:
            pass
        try:
            _t.backends.mps.enable_fallback_for_not_implemented_ops(True)
        except Exception:
            pass
        _pick_torch_device._configured = True
    if _t.cuda.is_available():
        return "cuda"
    if getattr(_t.backends, "mps", None) and _t.backends.mps.is_available():
        return "mps"
    return "cpu"


def _rembg_providers() -> list:
    """Retourne les providers onnxruntime les plus rapides disponibles sur ce système.

    Ordre de priorité :
      CUDA (Windows/Linux + GPU NVIDIA)  → CUDAExecutionProvider
      CoreML (macOS, CPU/ANE)            → CoreMLExecutionProvider
      CPU (fallback universel)           → CPUExecutionProvider
    """
    try:
        import onnxruntime as _ort
        available = set(_ort.get_available_providers())
        for preferred in ("CUDAExecutionProvider", "CoreMLExecutionProvider"):
            if preferred in available:
                return [preferred, "CPUExecutionProvider"]
    except Exception:
        pass
    return ["CPUExecutionProvider"]


# Checkpoints SAM2 disponibles : (nom_fichier, config_yaml, url_téléchargement)
_SAM2_MODELS: dict = {
    "S":  ("sam2.1_hiera_small.pt",
           "configs/sam2.1/sam2.1_hiera_s.yaml",
           "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt"),
    "B+": ("sam2.1_hiera_base_plus.pt",
           "configs/sam2.1/sam2.1_hiera_b+.yaml",
           "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt"),
    "L":  ("sam2.1_hiera_large.pt",
           "configs/sam2.1/sam2.1_hiera_l.yaml",
           "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"),
}


###############################################################
#                       CONFIGURATION                         #
###############################################################

DPI = 300  # Résolution d'export (points par pouce)

# ---- Modèles IA ----
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(_MODELS_DIR, exist_ok=True)

# ---- Cache de compilation torch.compile ----
# Stocké dans models/_torch_cache/ → survit à git reset --hard (dossier non suivi).
# Le cache Inductor (kernels JIT) est redirigé ici via la variable d'environnement.
_COMPILE_CACHE_DIR     = os.path.join(_MODELS_DIR, "_torch_cache")
_COMPILE_MANIFEST_PATH = os.path.join(_COMPILE_CACHE_DIR, "manifest.json")
os.makedirs(_COMPILE_CACHE_DIR, exist_ok=True)
os.environ.setdefault("TORCHINDUCTOR_CACHE_DIR",
                      os.path.join(_COMPILE_CACHE_DIR, "inductor"))


def _read_compile_manifest() -> dict:
    import json
    if os.path.exists(_COMPILE_MANIFEST_PATH):
        try:
            with open(_COMPILE_MANIFEST_PATH, encoding="utf-8") as _f:
                return json.load(_f)
        except Exception:
            pass
    return {}


def _write_compile_manifest(manifest: dict) -> None:
    import json
    os.makedirs(_COMPILE_CACHE_DIR, exist_ok=True)
    with open(_COMPILE_MANIFEST_PATH, "w", encoding="utf-8") as _f:
        json.dump(manifest, _f, indent=2)


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
    "Blanc":      (255, 255, 255),
    "Gris clair": (192, 192, 192),
    "Gris foncé": (64,  64,  64),
    "Noir":       (0,   0,   0),
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
            with urllib.request.urlopen(url, timeout=120) as response:  # nosec
                with open(tmp, "wb") as f:
                    while chunk := response.read(65536):
                        f.write(chunk)
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


def _dilate_alpha(img: Image.Image, radius: int) -> Image.Image:
    """
    Dilate le canal alpha d'une image RGBA d'environ ``radius`` pixels.

    Utilise un filtre morphologique Max (ImageFilter.MaxFilter) sur le
    canal alpha pour étendre le masque vers l'extérieur.

    Parameters
    ----------
    img : PIL.Image.Image
        Image en mode RGBA à traiter.
    radius : int
        Rayon de dilatation en pixels (1–15). 0 ou négatif = pas de dilatation.

    Returns
    -------
    PIL.Image.Image
        Image RGBA avec le canal alpha dilaté.
    """
    if img.mode != "RGBA" or radius <= 0:
        return img
    r, g, b, a = img.split()
    for _ in range(radius):
        a = a.filter(ImageFilter.MaxFilter(3))
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
    await page.window.to_front()

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
        "bg_blur":         True,  # True = fond flou (remplace la couleur de fond)
        "bg_transparent":  False,  # True = fond transparent (export PNG)
        "rembg_human_seg": True,   # True = portrait, False = général
        "rembg_precise":   False,  # True = birefnet (précis), False = u2net (rapide)
        "working":         False,  # True pendant l'exécution de rembg
        "enhancing":       False,  # True pendant face SR ou ESRGAN
        "rembg_applied":   False,  # True après suppression du fond par rembg
        "history":         [],     # Pile d'annulation (max 5)
        "current_task":    None,   # asyncio.Task en cours (rembg ou modèle)
        "cancel_requested": False, # Annulation demandée (boucle de tuiles)
        "morph_pct":       0.0,    # % morphologique unifié : <0 = érosion, >0 = dilatation (−5…+5)
        "batch_running":   False,  # True pendant le batch automatique
        # SAM2
        "sam2_points":       [],     # [(x, y, label), ...] coords image originale
        "sam2_working":      False,  # True pendant l'inférence SAM2
        "sam2_preview_size": None,   # (w, h) de l'image affichée dans preview_img
        "sam2_preview_mask": None,   # bool ndarray (H, W) — aperçu masque avant application
        "sam2_model":        "S",     # clé dans _SAM2_MODELS (S / B+ / L)
        "sam2_threshold":    0.0,     # seuil de binarisation du masque
        # Inpainting
        "inpaint_radius":    20,        # Rayon TELEA (inpaintRadius)
    }

    # Sessions rembg (une par modèle pour éviter le rechargement)
    _rembg_sessions: dict = {}  # {model_name: session}
    # Modèles spandrel : cache par nom de fichier
    _custom_model_cache: dict = {}  # {nom_fichier: desc}
    # Cache SAM2 : un predictor par taille de modèle
    _sam2_predictor_cache: dict = {}  # {model_key: predictor}
    # Cache IOPaint : un ModelManager par nom de modèle
    _iopaint_mgr_cache: dict = {}  # {model_name: ModelManager}
    # Tâche d'aperçu SAM2 en cours (annulable)
    _sam2_preview_task: list = []     # [task] ou [] si aucun aperçu en cours

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
        fit=ft.BoxFit.FILL,    # taille fixe contrôlée par width/height
        gapless_playback=True,
        visible=False,
    )

    def _place_sam2_point(e, label: int) -> None:
        """Enregistre un point SAM2 positif (label=1) et lance l'aperçu."""
        if not SAM2_AVAILABLE:
            sam2_status.value = "sam2 non disponible"
            page.update()
            return
        if state["sam2_working"] or state["orig_img"] is None:
            return
        preview_size = state.get("sam2_preview_size")
        if preview_size is None:
            sam2_status.value = "Attendez que l'image soit chargée"
            page.update()
            return
        orig = state["orig_img"]
        pw, ph = preview_size
        _pos = getattr(e, "local_position", None)
        if _pos is None:
            sam2_status.value = "⚠️ Événement invalide — réessayez"
            page.update()
            return
        ox, oy = _pos.x, _pos.y
        img_x = int(ox / pw * orig.width)
        img_y = int(oy / ph * orig.height)
        img_x = max(0, min(img_x, orig.width  - 1))
        img_y = max(0, min(img_y, orig.height - 1))
        state["sam2_points"].append((img_x, img_y, label))
        n = len(state["sam2_points"])
        sam2_status.value = f"{n} point(s) placé(s) — clic gauche positif / clic droit négatif — calcul aperçu…"
        page.update()
        # Annuler l'aperçu précédent si encore en cours, puis relancer
        if _sam2_preview_task:
            _sam2_preview_task[0].cancel()
            _sam2_preview_task.clear()
        task = asyncio.create_task(_sam2_live_preview())
        _sam2_preview_task.append(task)

    def _remove_last_sam2_point() -> None:
        """Retire le dernier point placé."""
        if not state["sam2_points"]:
            sam2_status.value = "Aucun point à retirer"
            page.update()
            return
        state["sam2_points"].pop()
        if _sam2_preview_task:
            _sam2_preview_task[0].cancel()
            _sam2_preview_task.clear()
        if not state["sam2_points"]:
            state["sam2_preview_mask"] = None
            sam2_status.value = "Tous les points effacés"
            _render_preview()
        else:
            n = len(state["sam2_points"])
            sam2_status.value = f"{n} point(s) restant(s) — calcul aperçu…"
            page.update()
            task = asyncio.create_task(_sam2_live_preview())
            _sam2_preview_task.append(task)

    def _on_preview_tap(e) -> None:
        """Clic gauche = point SAM2 positif."""
        _place_sam2_point(e, 1)

    def _on_preview_secondary_tap(e) -> None:
        """Clic droit = point SAM2 négatif."""
        _place_sam2_point(e, 0)

    def _run_sam2_inference(snap_img, snap_points, snap_model, snap_thresh):
        """
        Exécute l'inférence SAM2 et retourne un masque de probabilité doux.

        Charge le predictor SAM2 (mis en cache par clé de modèle), applique
        les points fournis sur l'image et retourne un tableau float32 [0, 1]
        de la même résolution que `snap_img`, avec des bords adoucis via
        la passe sigmoid + clip.

        Parameters
        ----------
        snap_img : PIL.Image
            Image RGB source (snapshot pris avant le thread).
        snap_points : list of (x, y, label)
            Points SAM2 : label 1 = positif, 0 = négatif.
        snap_model : str
            Clé dans `_SAM2_MODELS` identifiant le checkpoint.
        snap_thresh : float
            Seuil de masque transmis à `predictor.mask_threshold`.

        Returns
        -------
        numpy.ndarray
            Tableau float32 (H, W) de valeurs dans [0, 1].
        """
        import torch as _torch
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        ckpt_name, cfg_name, ckpt_url = _SAM2_MODELS[snap_model]
        ckpt_path = os.path.join(_MODELS_DIR, ckpt_name)
        _ensure_model(ckpt_url, ckpt_path)
        if snap_model not in _sam2_predictor_cache:
            _dev = _pick_torch_device()
            model = build_sam2(cfg_name, ckpt_path, device=_dev)
            predictor = SAM2ImagePredictor(model)
            # torch.compile désactivé pour SAM2 : les transforms torchvision internes
            # (Resize) provoquent "Can't redefine method: forward" à la 2ème utilisation
            _sam2_predictor_cache[snap_model] = predictor
        predictor = _sam2_predictor_cache[snap_model]
        predictor.mask_threshold = snap_thresh
        img_np = np.array(snap_img)
        multimask = len(snap_points) == 1
        with _torch.inference_mode():
            predictor.set_image(img_np)
            points_np = np.array([[x, y] for x, y, _ in snap_points], dtype=np.float32)
            labels_np = np.array([l for _, _, l in snap_points], dtype=np.int32)
            # Premier passage — multimask pour choisir le meilleur candidat
            masks, scores, logits_out = predictor.predict(
                point_coords=points_np,
                point_labels=labels_np,
                multimask_output=multimask,
                return_logits=True,
            )
            best_idx = int(np.argmax(scores))
            # Second passage — réinjection des logits comme mask_input pour affiner
            # et supprimer les artefacts rectangulaires liés aux patches de l'encodeur
            masks, scores, _ = predictor.predict(
                point_coords=points_np,
                point_labels=labels_np,
                mask_input=logits_out[best_idx : best_idx + 1],
                multimask_output=False,
                return_logits=True,
            )
            best_idx = 0
        logits = masks[best_idx].astype(np.float32)
        prob = 1.0 / (1.0 + np.exp(-logits))
        return np.clip((prob - 0.05) / (0.95 - 0.05), 0.0, 1.0)

    async def _sam2_live_preview() -> None:
        """Calcule et affiche un aperçu du masque SAM2 sans modifier state['processed']."""
        if not state["sam2_points"] or state["orig_img"] is None:
            return
        snap_img    = state["orig_img"].convert("RGB")
        snap_points = list(state["sam2_points"])
        snap_model  = state["sam2_model"]
        snap_thresh = state["sam2_threshold"]

        def _do_preview():
            return _run_sam2_inference(snap_img, snap_points, snap_model, snap_thresh)

        try:
            mask = await asyncio.to_thread(_do_preview)
            state["sam2_preview_mask"] = mask
            n_pos = sum(1 for _, _, l in state["sam2_points"] if l == 1)
            n_neg = sum(1 for _, _, l in state["sam2_points"] if l == 0)
            sam2_status.value = f"{n_pos} point(s) +, {n_neg} − — aperçu masque visible"
            _render_preview()
        except asyncio.CancelledError:
            pass  # Nouveau clic arrivé, on abandonne cet aperçu
        except Exception as ex:
            sam2_status.value = f"[aperçu] {ex}"
            page.update()
        finally:
            current = asyncio.current_task()
            if current in _sam2_preview_task:
                _sam2_preview_task.remove(current)

    preview_gesture = ft.GestureDetector(
        content=preview_img,
        on_tap_down=_on_preview_tap,
        on_secondary_tap_down=_on_preview_secondary_tap,
        mouse_cursor=ft.MouseCursor.CELL if SAM2_AVAILABLE else ft.MouseCursor.BASIC,
    )
    # Wrapper centré : expand=True pour remplir le panneau,
    # alignment pour centrer le gesture (thumbnail-sized) dans l'espace disponible.
    preview_centered = ft.Container(
        content=preview_gesture,
        expand=True,
        alignment=ft.Alignment(0, 0),
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

    # ---- Overlay de compilation ---- #
    _compile_overlay_label = ft.Text(
        "Compilation des modèles…",
        size=15,
        weight=ft.FontWeight.BOLD,
        color=WHITE,
        text_align=ft.TextAlign.CENTER,
    )
    _compile_overlay_sub = ft.Text(
        "",
        size=12,
        color=LIGHT_GREY,
        text_align=ft.TextAlign.CENTER,
    )
    _compile_overlay_bar = ft.ProgressBar(
        width=260,
        color=BLUE,
        bgcolor=GREY,
    )
    compile_overlay = ft.Container(
        content=ft.Column(
            [
                ft.ProgressRing(color=BLUE, stroke_width=3),
                _compile_overlay_label,
                _compile_overlay_sub,
                _compile_overlay_bar,
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=14,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
        bgcolor=ft.Colors.with_opacity(0.72, BG_UI),
        border_radius=8,
        visible=False,
    )

    bg_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=5,
        bgcolor=GREY,
        thumb_color=BG_UI,
        proportional_width=True,
        controls=[
            ft.Text("Blanc",      size=11, color=WHITE),
            ft.Text("Gris clair", size=11, color=WHITE),
            ft.Text("Gris foncé", size=11, color=WHITE),
            ft.Text("Noir",       size=11, color=WHITE),
            ft.Text("Transp.",    size=11, color=WHITE),
            ft.Text("Flou",       size=11, color=WHITE),
        ],
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
        icon_color=DARK,
        bgcolor=RED,
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

    # Couleur personnalisée (hex)
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

    # ---- SAM2 ---- #
    sam2_clear_btn = ft.Button(
        "Effacer points",
        icon=ft.Icons.CLEAR,
        bgcolor=GREY,
        color=ORANGE,
        disabled=not SAM2_AVAILABLE,
        tooltip="Effacer tous les points SAM2 et recommencer",
    )
    sam2_apply_btn = ft.Button(
        "Appliquer masque",
        icon=ft.Icons.CONTENT_CUT,
        bgcolor=BLUE if SAM2_AVAILABLE else GREY,
        color=DARK,
        disabled=not SAM2_AVAILABLE,
    )
    sam2_inpaint_btn = ft.Button(
        "Remplissage",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=ORANGE if (SAM2_AVAILABLE and (CV2_AVAILABLE or IOPAINT_AVAILABLE)) else GREY,
        color=DARK,
        disabled=not (SAM2_AVAILABLE and (CV2_AVAILABLE or IOPAINT_AVAILABLE)),
        tooltip=(
            "IOPaint — meilleure qualité" if IOPAINT_AVAILABLE
            else "ShiftMap (opencv-contrib) — synthèse par patches" if CV2_AVAILABLE
            else "Installez opencv-contrib-python ou iopaint"
        ),
    )
    # Sélecteur de moteur d'inpainting — ordre : telea, lama, mat
    _inpaint_engines = []
    if CV2_AVAILABLE:
        _inpaint_engines.append("telea")
    if IOPAINT_AVAILABLE:
        from iopaint.download import scan_models as _sm
        _io_available = [m.name for m in _sm()]
        for _m in ["lama", "mat"]:
            if _m in _io_available:
                _inpaint_engines.append(_m)
    if not _inpaint_engines:
        _inpaint_engines = ["telea"]
    _inpaint_controls = [ft.Text(e, size=10, color=BG_UI) for e in _inpaint_engines]
    if len(_inpaint_controls) < 2:
        _inpaint_controls.append(ft.Text("—", size=10, color=GREY))
    sam2_inpaint_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,  # telea par défaut
        bgcolor=GREY,
        thumb_color=ORANGE,
        controls=_inpaint_controls,
        disabled=not (SAM2_AVAILABLE and (CV2_AVAILABLE or IOPAINT_AVAILABLE)),
    )

    # ---- Bouton d'installation IOPaint ---- #
    inpaint_install_btn = ft.FilledButton(
        "Installer IOPaint",
        icon=ft.Icons.DOWNLOAD,
        visible=not IOPAINT_AVAILABLE,
        tooltip="pip install iopaint  (ajoute les moteurs lama et mat)",
    )
    inpaint_install_status = ft.Text("", size=11, color=LIGHT_GREY, visible=not IOPAINT_AVAILABLE)

    sam2_status = ft.Text("", size=11, color=LIGHT_GREY)
    sam2_progress_bar = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)

    # ---- Inpainting : rayon TELEA ---- #
    sam2_inpaint_radius_slider = ft.Slider(
        value=20,
        min=1,
        max=20,
        divisions=19,
        label="{value}",
        active_color=BLUE,
        expand=True,
        disabled=not (SAM2_AVAILABLE and CV2_AVAILABLE),
    )

    # Sélecteur de modèle SAM2 (S = small ~40 Mo, B+ = base+ ~120 Mo, L = large ~230 Mo)
    sam2_model_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,  # S par défaut
        bgcolor=GREY,
        thumb_color=BLUE,
        controls=[
            ft.Text("S",  size=11, color=BG_UI),
            ft.Text("B+", size=11, color=BG_UI),
            ft.Text("L",  size=11, color=BG_UI),
        ],
        disabled=not SAM2_AVAILABLE,
    )
    # Seuil de binarisation : < 0 = masque plus large, > 0 = masque plus strict
    sam2_threshold_slider = ft.Slider(
        value=0.0,
        min=-2.0,
        max=2.0,
        divisions=40,
        label="0.0",
        active_color=BLUE,
        expand=True,
        disabled=not SAM2_AVAILABLE,
    )

    # ---- Bouton d'installation SAM2 ---- #
    sam2_install_btn = ft.FilledButton(
        "Installer SAM2",
        icon=ft.Icons.DOWNLOAD,
        visible=not SAM2_AVAILABLE,
        tooltip="pip install -e git+https://github.com/facebookresearch/sam2",
    )
    sam2_install_status = ft.Text("", size=11, color=LIGHT_GREY, visible=not SAM2_AVAILABLE)

    # ---- Slider morphologique unifié : négatif = érosion, positif = dilatation ---- #
    morph_slider = ft.Slider(
        value=0,
        min=-2,
        max=2,
        divisions=100,
        label="0.00 %",
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
    recompile_btn = ft.IconButton(
        icon=ft.Icons.SYNC_ROUNDED,
        icon_color=DARK,
        bgcolor=BLUE if ESRGAN_AVAILABLE else GREY,
        tooltip="Forcer la recompilation (torch.compile)\nEfface le manifeste et recompile tous les modèles",
        disabled=not ESRGAN_AVAILABLE,
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
        # Afficher le résultat traité
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return
        max_px = state.get("preview_max_px", 700)
        thumb = base.copy()
        thumb.thumbnail((max_px, max_px), Image.Resampling.BILINEAR)
        # Érosion / dilatation au format d'affichage (ne modifie pas state["processed"])
        morph = state["morph_pct"]
        if morph < 0 and state["processed"] is not None and thumb.mode == "RGBA":
            scaled_radius = round(min(thumb.size) * abs(morph) / 100)
            if scaled_radius > 0:
                thumb = _erode_alpha(thumb, scaled_radius)
        elif morph > 0 and state["processed"] is not None and thumb.mode == "RGBA" and state.get("sam2_preview_mask") is None:
            scaled_radius = round(min(thumb.size) * morph / 100)
            if scaled_radius > 0:
                thumb = _dilate_alpha(thumb, scaled_radius)
        # Mode "avant" retiré
        if state["bg_blur"] and thumb.mode != "RGBA":
            display = thumb.convert("RGB")
        elif state["bg_blur"]:
            display = apply_background(thumb, None, state["orig_img"])
        elif state["bg_transparent"]:
            # Damier pour visualiser la transparence
            rgba = thumb.convert("RGBA")
            chk = _make_checkerboard(rgba.size)
            display = Image.alpha_composite(chk, rgba).convert("RGB")
        else:
            display = apply_background(thumb, BG_COLORS[state["bg_color"]], state["orig_img"])
        # Superposition du masque SAM2 en aperçu (bleu semi-transparent)
        if state.get("sam2_preview_mask") is not None:
            mask = state["sam2_preview_mask"]
            # Binarisation à 0.5 : évite l'affichage des zones à faible probabilité
            mask_binary = ((mask >= 0.5) * 255).astype(np.uint8)
            mask_img = Image.fromarray(mask_binary, "L")
            mask_resized = mask_img.resize(display.size, Image.Resampling.NEAREST)
            # Dilatation visuelle : montre en temps réel l'expansion du masque
            dil = max(0.0, state.get("morph_pct", 0))
            if dil > 0:
                display_dil = max(1, round(min(display.size) * dil / 100))
                for _ in range(display_dil):
                    mask_resized = mask_resized.filter(ImageFilter.MaxFilter(3))
            overlay_rgba = Image.new("RGBA", display.size, (69, 184, 245, 180))
            mask_alpha = mask_resized.point(lambda p: 180 if p > 0 else 0)
            overlay_rgba.putalpha(mask_alpha)
            display = Image.alpha_composite(display.convert("RGBA"), overlay_rgba).convert("RGB")
        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(display)}"
        # Taille explicite : le GestureDetector aura exactement ces dimensions,
        # donc e.local_position est directement en pixels thumbnail.
        tw, th = display.size
        preview_img.width  = tw
        preview_img.height = th
        state["sam2_preview_size"] = display.size  # (w, h) identique
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
            state["sam2_points"].clear()
            state["sam2_preview_size"] = None
            state["sam2_preview_mask"] = None

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

    async def on_force_recompile(e) -> None:
        """Efface le manifeste de compilation et relance _run_compile_warmup."""
        if state.get("enhancing"):
            return
        # Vider le manifeste → tous les modèles seront recompilés
        _write_compile_manifest({})
        # Vider uniquement le cache spandrel — SAM2 ne peut pas être recompilé
        # dans la même session Python (torch.compile interdit de redéfinir forward)
        _custom_model_cache.clear()
        enhance_status.value = "Manifeste effacé — recompilation en cours…"
        recompile_btn.disabled = True
        page.update()
        await _run_compile_warmup()
        recompile_btn.disabled = not ESRGAN_AVAILABLE
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
                _dev = _pick_torch_device()
                # Barre indéterminée pendant le chargement du modèle
                _progress_cb(None, f"Chargement de {model_name}…")
                desc = _ModelLoader().load_from_file(model_path)
                desc.to(_dev)
                desc.model.eval()
                # torch.compile : accélère les inférences suivantes via le cache Inductor
                if hasattr(_torch, "compile") and _dev != "mps" and sys.platform != "win32":
                    try:
                        desc.model = _torch.compile(desc.model, mode="reduce-overhead")
                    except Exception:
                        pass
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

    def on_morph_slider_change(e) -> None:
        """Met à jour le % morphologique en temps réel (label pendant le drag)."""
        v = round(e.control.value, 2)
        state["morph_pct"] = v
        morph_slider.label = f"{v:.2f} %"

    def on_morph_slider_end(e) -> None:
        """Regénère la preview au relâchement du slider."""
        v = round(e.control.value, 2)
        state["morph_pct"] = v
        morph_slider.label = f"{v:.2f} %"
        if state["processed"] is not None or state.get("sam2_preview_mask") is not None:
            _render_preview()

    def on_morph_slider_reset(e) -> None:
        """Double-clic : remet le slider à 0."""
        morph_slider.value = 0
        morph_slider.label = "0.00 %"
        morph_slider.update()
        state["morph_pct"] = 0.0
        if state["processed"] is not None or state.get("sam2_preview_mask") is not None:
            _render_preview()

    def on_bg_change(e) -> None:
        """Met à jour la couleur de fond sélectionnée et rafraîchit la preview."""
        idx = e.control.selected_index
        _color_map = ["Blanc", "Gris clair", "Gris foncé", "Noir"]
        if idx == 5:  # Flou
            state["bg_blur"]        = True
            state["bg_transparent"] = False
        elif idx == 4:  # Transparent
            state["bg_blur"]        = False
            state["bg_transparent"] = True
            state["bg_color"]       = "Blanc"  # fallback interne
        else:  # 0-3 : couleur fixe
            state["bg_blur"]        = False
            state["bg_transparent"] = False
            state["bg_color"]       = _color_map[idx]
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
            _model_key_map = {
                (True,  True):  "birefnet-portrait",
                (True,  False): "birefnet-general",
                (False, True):  "u2net_human_seg",
                (False, False): "u2net",
            }
            model_key = _model_key_map[(use_precise, use_human)]
            if model_key not in _rembg_sessions:
                _rembg_sessions[model_key] = new_session(model_key, providers=_rembg_providers())
            sess = _rembg_sessions[model_key]
            with contextlib.redirect_stderr(io.StringIO()):
                result = rembg_remove(state["orig_img"].convert("RGB"), session=sess)
            return result.convert("RGBA")

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
        has_morpho = state["morph_pct"] != 0 and state["processed"].mode == "RGBA"
        if has_morpho:
            morpho_pct = state["morph_pct"]
            if morpho_pct < 0:
                status_text.value = f"Érosion {abs(morpho_pct):.1f} % en cours…"
            else:
                status_text.value = f"Dilatation {morpho_pct:.1f} % en cours…"
            progress_bar.value = None  # indéterminée
            progress_bar.visible = True
        else:
            status_text.value = "Enregistrement…"
        page.update()

        use_transparent = state["bg_transparent"]
        snap_processed  = state["processed"]
        snap_orig       = state["orig_img"]
        morph_pct       = state["morph_pct"]
        bg_blur         = state["bg_blur"]
        bg_color        = BG_COLORS.get(state["bg_color"])

        def _do_export():
            proc = snap_processed
            # Érosion / dilatation pleine résolution
            if morph_pct < 0 and proc is not None and proc.mode == "RGBA":
                radius_px = round(min(proc.size) * abs(morph_pct) / 100)
                if radius_px > 0:
                    proc = _erode_alpha(proc, radius_px)
            elif morph_pct > 0 and proc is not None and proc.mode == "RGBA":
                radius_px = round(min(proc.size) * morph_pct / 100)
                if radius_px > 0:
                    proc = _dilate_alpha(proc, radius_px)
            if use_transparent:
                return proc.convert("RGBA"), ".png", "PNG", {}
            else:
                # Le fond flou n'a de sens que si l'image a une couche alpha.
                # Sans transparence (ex : après inpainting), on exporte directement.
                if bg_blur and proc.mode == "RGBA":
                    img = apply_background(proc, None, snap_orig)
                elif proc.mode == "RGBA":
                    img = apply_background(proc, bg_color, snap_orig)
                else:
                    img = proc.convert("RGB")
                return img, ".jpg", "JPEG", {"dpi": (DPI, DPI), "quality": 100}

        try:
            final_img, ext, fmt, save_kwargs = await asyncio.to_thread(_do_export)

            if has_morpho:
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
        _rembg_sessions.clear()
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

    def on_sam2_clear(e) -> None:
        """Efface tous les points SAM2."""
        if _sam2_preview_task:
            _sam2_preview_task[0].cancel()
            _sam2_preview_task.clear()
        state["sam2_points"].clear()
        state["sam2_preview_mask"] = None
        sam2_status.value = "Points effacés"
        _render_preview()

    async def on_sam2_install(e) -> None:
        """Installe le paquet sam2 via pip dans un sous-processus."""
        global SAM2_AVAILABLE
        sam2_install_btn.disabled = True
        sam2_install_status.value = "Installation en cours…"
        sam2_install_status.color = LIGHT_GREY
        page.update()
        import sys
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-q",
            "git+https://github.com/facebookresearch/sam2",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            import importlib as _il
            _il.invalidate_caches()
            SAM2_AVAILABLE = importlib.util.find_spec("sam2") is not None
            if SAM2_AVAILABLE:
                sam2_install_status.value = "SAM2 installé — relancez l'application"
                sam2_install_status.color = ft.Colors.GREEN_400
                sam2_install_btn.visible  = False
            else:
                sam2_install_status.value = "Installé — redémarrez pour activer SAM2"
                sam2_install_status.color = ft.Colors.AMBER_400
                sam2_install_btn.disabled = False
        else:
            err_msg = stderr.decode(errors="replace").strip().splitlines()
            sam2_install_status.value = err_msg[-1] if err_msg else "Erreur d'installation"
            sam2_install_status.color = RED
            sam2_install_btn.disabled = False
        page.update()

    sam2_install_btn.on_click = on_sam2_install

    async def on_sam2_apply(e) -> None:
        """Lance l'inférence SAM2 sur les points collectés."""
        if not SAM2_AVAILABLE:
            return
        if not state["sam2_points"]:
            sam2_status.value = "⚠️ Cliquez d'abord sur l'image pour placer des points"
            page.update()
            return
        if state["sam2_working"] or state["orig_img"] is None:
            return

        state["sam2_working"] = True
        _push_history()
        sam2_apply_btn.disabled = True
        sam2_clear_btn.disabled = True
        sam2_progress_bar.value   = None
        sam2_progress_bar.visible = True
        sam2_status.value = "SAM2 — inférence en cours…"
        page.update()

        snap_img    = state["orig_img"].convert("RGB")
        snap_points = list(state["sam2_points"])
        snap_model  = state["sam2_model"]
        snap_thresh = state["sam2_threshold"]

        def _do_sam2():
            prob = _run_sam2_inference(snap_img, snap_points, snap_model, snap_thresh)

            # Construire image RGBA avec alpha proportionnel (bords doux)
            rgba = snap_img.convert("RGBA")
            alpha_arr = (prob * 255).astype(np.uint8)
            rgba.putalpha(Image.fromarray(alpha_arr, "L"))
            return rgba

        try:
            result = await asyncio.to_thread(_do_sam2)
            state["processed"]        = result
            state["rembg_applied"]     = False  # marqué différemment
            state["sam2_preview_mask"] = None   # remplacé par le résultat final
            process_btn.text      = "Supprimer le fond (IA)"
            process_btn.bgcolor   = VIOLET if REMBG_AVAILABLE else GREY
            save_btn.disabled     = False
            sam2_status.value     = f"[OK] SAM2 — masque appliqué ({len(snap_points)} point(s))"
            _render_preview()
        except Exception as ex:
            sam2_status.value = f"[ERREUR] SAM2 : {ex}"
            page.update()
        finally:
            state["sam2_working"]    = False
            sam2_apply_btn.disabled  = not SAM2_AVAILABLE
            sam2_clear_btn.disabled  = not SAM2_AVAILABLE
            sam2_progress_bar.value   = 1.0
            sam2_progress_bar.visible = False
            page.update()

    sam2_clear_btn.on_click   = on_sam2_clear
    sam2_apply_btn.on_click   = on_sam2_apply

    async def on_sam2_inpaint(e) -> None:
        """Reconstruit la zone sélectionnée par SAM2 via OpenCV INPAINT_TELEA."""
        if not CV2_AVAILABLE:
            sam2_status.value = "⚠️ opencv-python requis — pip install opencv-python"
            page.update()
            return
        if state["sam2_preview_mask"] is None:
            sam2_status.value = "⚠️ Placez des points SAM2 d'abord"
            page.update()
            return
        if state["sam2_working"] or state["orig_img"] is None:
            return

        state["sam2_working"] = True
        _push_history()
        sam2_inpaint_btn.disabled = True
        sam2_apply_btn.disabled   = True
        sam2_clear_btn.disabled   = True
        sam2_progress_bar.value   = None
        sam2_progress_bar.visible = True

        # Travailler sur l'image courante (processed si existe, sinon orig)
        src_img = (state["processed"] or state["orig_img"]).convert("RGB")
        prob    = state["sam2_preview_mask"]  # float [0,1] (H, W) — taille orig_img

        # Choisir le moteur selon la sélection de l'utilisateur
        _sel_idx = sam2_inpaint_segment.selected_index or 0
        engine = (_inpaint_engines[_sel_idx] if _inpaint_engines and _sel_idx < len(_inpaint_engines) else "telea")
        if engine in ("lama", "mat"):
            engine = f"iopaint:{engine}"  # normalise pour la suite

        _engine_label = {
            "shiftmap": "ShiftMap",
            "telea":    "TELEA",
        }.get(engine, f"IOPaint ({engine.split(':')[1]})" if engine.startswith("iopaint:") else engine)
        sam2_status.value = f"Inpainting {_engine_label}…"
        page.update()

        snap_dilation = max(0.0, state["morph_pct"])
        snap_inpaint_radius = state["inpaint_radius"]

        def _do_inpaint():
            mask_np = ((prob > 0.1) * 255).astype(np.uint8)

            # Dilatation du masque pour englober les bords de la sélection
            if snap_dilation > 0:
                import cv2 as _cv2_d
                dil_px = max(1, round(min(mask_np.shape[:2]) * snap_dilation / 100))
                kernel = np.ones((dil_px * 2 + 1, dil_px * 2 + 1), np.uint8)
                mask_np[:] = _cv2_d.dilate(mask_np, kernel, iterations=1)

            if engine.startswith("iopaint:"):
                _model_name = engine.split(":")[1]
                from iopaint.model_manager import ModelManager
                from iopaint.schema import InpaintRequest, HDStrategy
                import torch as _torch
                # LaMa et MAT ne supportent pas MPS — on passe directement CPU sur macOS
                _raw_dev = _pick_torch_device()
                _io_dev = "cpu" if _raw_dev == "mps" else _raw_dev
                if _model_name not in _iopaint_mgr_cache:
                    _iopaint_mgr_cache[_model_name] = ModelManager(
                        name=_model_name, device=_torch.device(_io_dev)
                    )
                mgr = _iopaint_mgr_cache[_model_name]
                import cv2 as _cv2_io
                img_np     = np.array(src_img)                                   # uint8 RGB — IOPaint attend RGB
                req        = InpaintRequest(hd_strategy=HDStrategy.ORIGINAL)
                result_bgr = mgr(img_np, mask_np, req)                           # retourne BGR
                result_rgb = _cv2_io.cvtColor(result_bgr.astype(np.uint8), _cv2_io.COLOR_BGR2RGB)
                return Image.fromarray(result_rgb)

            import cv2 as _cv2
            img_np  = np.array(src_img)
            img_bgr = _cv2.cvtColor(img_np, _cv2.COLOR_RGB2BGR)

            if engine == "shiftmap":
                # Dilater le masque pour couvrir les bords
                kernel = np.ones((5, 5), np.uint8)
                mask_d = _cv2.dilate(mask_np, kernel, iterations=2)
                alg = _cv2.xphoto.createInpainter(_cv2.xphoto.SHIFTMAP)
                result = img_bgr.copy()
                alg.inpaint(img_bgr, mask_d, result)
            else:
                # Pyramide multi-échelle : TELEA ne voit JAMAIS le masque complet en pleine résolution.
                # À chaque niveau, le centre est déjà rempli par le niveau précédent ;
                # TELEA ne traite qu'un anneau de bordure fin → aucune traînée visible.
                h_f, w_f = img_bgr.shape[:2]
                scales   = [0.0625, 0.125, 0.25, 0.5, 1.0]
                guide    = None
                for sc in scales:
                    sw    = max(4, round(w_f * sc))
                    sh    = max(4, round(h_f * sc))
                    r     = max(1, round(snap_inpaint_radius * sc))
                    img_s = _cv2.resize(img_bgr, (sw, sh), interpolation=_cv2.INTER_AREA)
                    msk_s = _cv2.resize(mask_np, (sw, sh), interpolation=_cv2.INTER_NEAREST)
                    _, msk_s = _cv2.threshold(msk_s, 1, 255, _cv2.THRESH_BINARY)
                    if guide is not None:
                        # Injecter le guide du niveau précédent dans la zone masquée
                        g_up  = _cv2.resize(guide, (sw, sh), interpolation=_cv2.INTER_CUBIC)
                        m3    = msk_s[:, :, np.newaxis].astype(np.float32) / 255.0
                        img_s = (img_s.astype(np.float32) * (1.0 - m3)
                                 + g_up.astype(np.float32) * m3).astype(np.uint8)
                        # TELEA uniquement sur l'anneau de bordure à ce niveau
                        k_e   = np.ones((r * 2 + 1, r * 2 + 1), np.uint8)
                        inner = _cv2.erode(msk_s, k_e, iterations=1)
                        ring  = msk_s.copy()
                        ring[inner > 0] = 0
                        guide = (_cv2.inpaint(img_s, ring, inpaintRadius=r, flags=_cv2.INPAINT_TELEA)
                                 if ring.max() > 0 else img_s)
                    else:
                        # Premier niveau (6 %) : zone minuscule → TELEA lisse sans artefacts
                        guide = _cv2.inpaint(img_s, msk_s, inpaintRadius=r, flags=_cv2.INPAINT_TELEA)
                result = guide
                # Feathering gaussien sur les bords du masque
                blur_r    = max(3, snap_inpaint_radius * 4 + 1) | 1
                mask_soft = _cv2.GaussianBlur(mask_np.astype(np.float32) / 255.0,
                                              (blur_r, blur_r), 0)[:, :, np.newaxis]
                result    = (img_bgr.astype(np.float32) * (1.0 - mask_soft)
                             + result.astype(np.float32) * mask_soft).astype(np.uint8)

            return Image.fromarray(_cv2.cvtColor(result, _cv2.COLOR_BGR2RGB))

        try:
            result = await asyncio.to_thread(_do_inpaint)
            state["processed"]        = result
            state["sam2_preview_mask"] = None
            state["sam2_points"].clear()
            save_btn.disabled = False
            sam2_status.value = "[OK] Inpainting terminé"
            _render_preview()
        except Exception as ex:
            sam2_status.value = f"[ERREUR] Inpainting : {ex}"
            page.update()
        finally:
            state["sam2_working"]      = False
            sam2_inpaint_btn.disabled  = not (SAM2_AVAILABLE and (CV2_AVAILABLE or IOPAINT_AVAILABLE))
            sam2_apply_btn.disabled    = not SAM2_AVAILABLE
            sam2_clear_btn.disabled    = not SAM2_AVAILABLE
            sam2_progress_bar.value    = 1.0
            sam2_progress_bar.visible  = False
            page.update()

    sam2_inpaint_btn.on_click = on_sam2_inpaint

    # Attacher les callbacks
    bg_segment.on_change       = on_bg_change
    model_toggle_btn.on_click   = on_rembg_model_toggle
    precise_toggle_btn.on_click = on_rembg_precise_toggle
    undo_btn.on_click          = on_undo
    ignore_btn.on_click        = on_ignore
    process_btn.on_click       = on_process
    run_model_btn.on_click     = on_run_model
    refresh_btn.on_click       = on_refresh_models
    recompile_btn.on_click     = on_force_recompile
    save_btn.on_click            = on_save
    cancel_btn.on_click          = on_cancel
    morph_slider.on_change       = on_morph_slider_change
    morph_slider.on_change_end   = on_morph_slider_end

    def on_sam2_model_change(e) -> None:
        """Change le modèle SAM2 actif (S / B+ / L)."""
        state["sam2_model"] = ["S", "B+", "L"][e.control.selected_index]

    def on_sam2_threshold_change(e) -> None:
        """Met à jour le seuil de binarisation du masque SAM2 en temps réel."""
        state["sam2_threshold"] = round(e.control.value, 2)
        e.control.label = f"{e.control.value:.1f}"
        e.control.update()

    sam2_model_segment.on_change    = on_sam2_model_change
    sam2_threshold_slider.on_change = on_sam2_threshold_change

    def on_inpaint_radius_change(e) -> None:
        state["inpaint_radius"] = int(e.control.value)

    def on_sam2_inpaint_engine_change(e) -> None:
        idx = e.control.selected_index or 0
        engine = _inpaint_engines[idx] if _inpaint_engines and idx < len(_inpaint_engines) else "telea"
        _quality_row.visible = (engine == "telea")
        _quality_row.update()

    sam2_inpaint_radius_slider.on_change   = on_inpaint_radius_change
    sam2_inpaint_segment.on_change         = on_sam2_inpaint_engine_change

    async def on_inpaint_install(e) -> None:
        """Installe iopaint via pip et rafraîchit la liste des moteurs."""
        global IOPAINT_AVAILABLE
        inpaint_install_btn.disabled      = True
        inpaint_install_status.value      = "Installation en cours…"
        inpaint_install_status.color      = LIGHT_GREY
        inpaint_install_status.visible    = True
        page.update()
        import sys
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-q", "iopaint",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            import importlib as _il
            _il.invalidate_caches()
            IOPAINT_AVAILABLE = importlib.util.find_spec("iopaint") is not None
            if IOPAINT_AVAILABLE:
                # Reconstruire la liste des moteurs
                from iopaint.download import scan_models as _sm2
                _io_available = [m.name for m in _sm2()]
                for _m in ["lama", "mat"]:
                    if _m in _io_available and _m not in _inpaint_engines:
                        _inpaint_engines.append(_m)
                # Reconstruire les contrôles du segmented button
                _new_controls = [ft.Text(e, size=10, color=BG_UI) for e in _inpaint_engines]
                if len(_new_controls) < 2:
                    _new_controls.append(ft.Text("—", size=10, color=GREY))
                sam2_inpaint_segment.controls = _new_controls
                sam2_inpaint_segment.disabled = not SAM2_AVAILABLE
                sam2_inpaint_btn.disabled     = not SAM2_AVAILABLE
                sam2_inpaint_btn.bgcolor      = ORANGE if SAM2_AVAILABLE else GREY
                morph_slider.disabled         = not (REMBG_AVAILABLE or SAM2_AVAILABLE)
                inpaint_install_status.value  = "IOPaint installé — moteurs lama et mat disponibles"
                inpaint_install_status.color  = ft.Colors.GREEN_400
                inpaint_install_btn.visible   = False
            else:
                inpaint_install_status.value  = "Installé — redémarrez pour activer IOPaint"
                inpaint_install_status.color  = ft.Colors.AMBER_400
                inpaint_install_btn.disabled  = False
        else:
            err_msg = stderr.decode(errors="replace").strip().splitlines()
            inpaint_install_status.value  = err_msg[-1] if err_msg else "Erreur d'installation"
            inpaint_install_status.color  = RED
            inpaint_install_btn.disabled  = False
        page.update()

    inpaint_install_btn.on_click = on_inpaint_install

    # ------------------------------------------------------------------ #
    #                           MISE EN PAGE                              #
    # ------------------------------------------------------------------ #
    _quality_row = ft.Row(
        [ft.Text("Qualité", size=11, color=LIGHT_GREY, width=46), sam2_inpaint_radius_slider],
        spacing=6,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        visible=not _inpaint_engines or _inpaint_engines[0] == "telea",
    )

    left_panel = ft.Column(
        [
            # Fond
            ft.Row(
                [
                    ft.Text("Couleur de fond", size=13, weight=ft.FontWeight.BOLD, color=WHITE, expand=True),
                    undo_btn,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bg_segment,
            ft.Divider(color=GREY),
            ft.Row([model_toggle_btn, precise_toggle_btn], spacing=6),
            # Supprimer le fond
            process_btn,
            # SAM2
            ft.Divider(color=GREY),
            ft.Text("Sélection", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Text(
                "Clic gauche : sélectionner  /  clic droit : retirer",
                size=11,
                color=LIGHT_GREY,
            ) if SAM2_AVAILABLE else ft.Text(
                "sam2 non installé",
                size=10,
                color=RED,
            ),
            sam2_install_btn,
            sam2_install_status,
            ft.Row(
                [ft.Text("Modèle", size=11, color=LIGHT_GREY, width=46), sam2_model_segment, sam2_clear_btn],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Row(
                [ft.Text("Seuil", size=11, color=LIGHT_GREY, width=46), sam2_threshold_slider],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Row(
                [ft.Text("Moteur", size=11, color=LIGHT_GREY, width=46), sam2_inpaint_segment],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            inpaint_install_btn,
            inpaint_install_status,
            _quality_row,
            ft.Row([sam2_apply_btn, sam2_inpaint_btn], spacing=6),
            sam2_progress_bar,
            sam2_status,
            ft.Divider(color=GREY),
            # Morphologie du masque (érosion / dilatation)
            ft.Row(
                [
                    ft.Text("Morpho.", size=12, color=LIGHT_GREY),
                    ft.GestureDetector(
                        content=morph_slider,
                        on_double_tap=on_morph_slider_reset,
                        expand=True,
                    ),
                ],
                spacing=6,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            progress_bar,
            ft.Divider(color=GREY),
            # Amélioration IA
            ft.Text("Amélioration IA", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            ft.Text("📂 Data/models/", size=10, color=LIGHT_GREY),
            # Lien MSVC — visible uniquement sur Windows (torch.compile désactivé sans cl.exe)
            *(
                [
                    ft.TextButton(
                        "⚡ Activer torch.compile (MSVC requis)",
                        url="https://visualstudio.microsoft.com/fr/visual-cpp-build-tools/",
                        style=ft.ButtonStyle(color=LIGHT_GREY),
                        tooltip="Ouvre la page de téléchargement des Build Tools Visual Studio\n"
                                "(nécessaire pour torch.compile sous Windows — gain ~15-30% sur GPU)",
                    )
                ]
                if sys.platform == "win32" else []
            ),
            ft.Row(
                [model_dropdown, refresh_btn, recompile_btn, run_model_btn],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            enhance_progress_bar,
            cancel_btn,
            enhance_status,
            ft.Divider(color=GREY),
            ft.Row([save_btn, ignore_btn], spacing=8),
            ft.Container(expand=True),
            status_text,
        ],
        width=350,
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
    )

    center_panel = ft.Column(
        [
            ft.Row(
                [image_label, counter_text],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                content=ft.Stack(
                    [preview_placeholder, preview_centered, compile_overlay],
                ),
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

    def _on_page_resize(e=None) -> None:
        """Recalcule la taille max de la preview selon l'espace disponible."""
        # e.width/e.height sont fournis par Flet lors d'un resize réel
        w = int(getattr(e, 'width', None) or page.width or 1200)
        h = int(getattr(e, 'height', None) or page.height or 800)
        new_max = max(400, min(w - 320, h - 100))
        state["preview_max_px"] = new_max
        if state["orig_img"] is not None:
            _render_preview()
            page.update()

    page.on_resized = _on_page_resize
    _on_page_resize()  # valeur initiale (fenoêtre non encore maximisée)

    # ------------------------------------------------------------------ #
    #               COMPILATION DES MODÈLES (1ère utilisation)           #
    # ------------------------------------------------------------------ #
    async def _run_compile_warmup() -> None:
        """Compile tous les modèles IA présents sur disque et non encore compilés.

        Utilise torch.compile(mode="reduce-overhead") + une passe factice pour
        générer et mettre en cache les kernels Inductor dans
        models/_torch_cache/inductor/.  Un manifeste JSON retient le mtime et la
        taille de chaque modèle : on ne recompile que si le fichier a changé.
        MPS (Apple Silicon GPU) est exclu : torch.compile y est instable.
        """
        manifest   = _read_compile_manifest()
        to_compile: list = []

        # ── Modèles spandrel (.pth / .safetensors) ──────────────────────
        if ESRGAN_AVAILABLE:
            for name in _list_pth_models():
                path = os.path.join(_MODELS_DIR, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                mkey = f"spandrel:{name}"
                rec  = manifest.get(mkey, {})
                if rec.get("mtime") != st.st_mtime or rec.get("size") != st.st_size:
                    to_compile.append(("spandrel", name, path, mkey, st))

        # ── Modèles SAM2 déjà téléchargés ───────────────────────────────
        if SAM2_AVAILABLE:
            for model_key, (ckpt_name, _cfg, _url) in _SAM2_MODELS.items():
                path = os.path.join(_MODELS_DIR, ckpt_name)
                if not os.path.exists(path):
                    continue
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                mkey = f"sam2:{model_key}"
                rec  = manifest.get(mkey, {})
                if rec.get("mtime") != st.st_mtime or rec.get("size") != st.st_size:
                    to_compile.append(("sam2", model_key, path, mkey, st))

        if not to_compile:
            return

        total = len(to_compile)
        enhance_progress_bar.value    = 0.0
        enhance_progress_bar.visible  = True
        _compile_overlay_sub.value    = ""
        _compile_overlay_bar.value    = 0.0
        compile_overlay.visible       = True
        page.update()

        def _compile_one(kind: str, name: str, path: str) -> None:
            """Chargement + compilation + passe de chauffe (dans un thread worker)."""
            import torch as _t
            _dev = _pick_torch_device()
            use_compile = hasattr(_t, "compile") and _dev != "mps" and sys.platform != "win32"

            if kind == "spandrel" and name not in _custom_model_cache:
                from spandrel import ModelLoader as _ML
                desc = _ML().load_from_file(path)
                desc.to(_dev)
                desc.model.eval()
                if use_compile:
                    try:
                        desc.model = _t.compile(desc.model, mode="reduce-overhead")
                    except Exception:
                        pass
                tile  = 512 if _dev == "cuda" else 384 if _dev == "mps" else 256
                dummy = _t.zeros(1, 3, tile, tile, device=_dev)
                try:
                    with _t.inference_mode():
                        _ = desc.model(dummy)
                except Exception:
                    pass
                _custom_model_cache[name] = desc

            elif kind == "sam2" and name not in _sam2_predictor_cache:
                from sam2.build_sam import build_sam2 as _bs2
                from sam2.sam2_image_predictor import SAM2ImagePredictor as _Pred
                _cfg_name = _SAM2_MODELS[name][1]
                model     = _bs2(_cfg_name, path, device=_dev)
                predictor = _Pred(model)
                # torch.compile désactivé pour SAM2 (cf. _run_sam2_inference)
                dummy_img = np.zeros((224, 224, 3), dtype=np.uint8)
                try:
                    with _t.inference_mode():
                        predictor.set_image(dummy_img)
                except Exception:
                    pass
                _sam2_predictor_cache[name] = predictor

        ok_count   = 0
        fail_count = 0
        for i, (kind, name, path, mkey, st) in enumerate(to_compile):
            label = name if kind == "spandrel" else f"SAM2 {name}"
            enhance_status.value         = f"Compilation {i + 1}/{total} — {label}…"
            enhance_progress_bar.value   = i / total
            _compile_overlay_sub.value   = f"{i + 1} / {total} — {label}…"
            _compile_overlay_bar.value   = i / total
            page.update()
            try:
                await asyncio.to_thread(_compile_one, kind, name, path)
                manifest[mkey] = {"mtime": st.st_mtime, "size": st.st_size}
                _write_compile_manifest(manifest)
                ok_count += 1
            except Exception as ex:
                # Enregistrer l'échec dans le manifest (mtime+size identiques) pour
                # ne pas retenter à chaque lancement si le fichier n'a pas changé.
                manifest[mkey] = {"mtime": st.st_mtime, "size": st.st_size, "error": str(ex)}
                _write_compile_manifest(manifest)
                enhance_status.value       = f"[AVERT.] {label} : {ex}"
                _compile_overlay_sub.value = f"⚠️ {ex}"
                page.update()
                fail_count += 1
                await asyncio.sleep(1.5)

        enhance_progress_bar.value    = 1.0
        enhance_progress_bar.visible  = False
        if fail_count:
            enhance_status.value = (
                f"[OK] {ok_count} modèle(s) compilé(s)"
                f" — {fail_count} non supporté(s) par spandrel (ignoré(s))"
            )
        else:
            enhance_status.value = f"[OK] {total} modèle(s) compilé(s) — prêt"
        compile_overlay.visible       = False
        page.update()

    # ------------------------------------------------------------------ #
    #                         INITIALISATION                              #
    # ------------------------------------------------------------------ #
    if not REMBG_AVAILABLE:
        status_text.value = "⚠️ rembg non installé — exécutez : pip install rembg onnxruntime"
        page.update()
    if not ESRGAN_AVAILABLE:
        enhance_status.value = "spandrel non installé — pip install spandrel"
    if not SAM2_AVAILABLE:
        sam2_status.value = "sam2 non installé"

    # Compilation JIT au premier démarrage (ne bloque pas si tous les modèles
    # sont déjà dans le cache Inductor ou si aucun modèle n'est présent).
    await _run_compile_warmup()

    if all_images:
        asyncio.create_task(_load_image(0))
    else:
        status_text.value = f"Aucune image trouvée dans : {source_folder}"
        page.update()


    # ── Mettre la fenêtre en plein écran ────────────────────────────────────────────────
    async def _maximize():
        page.window.maximized = True
        page.update()
        await asyncio.sleep(0.25)  # laisse le layout se stabiliser
        _on_page_resize()  # recalcule et re-rend la preview à la bonne taille

    page.run_task(_maximize)

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
