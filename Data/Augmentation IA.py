# -*- coding: utf-8 -*-
"""
Preparation ID.py — Préparation IA de photos d'identité
=========================================================

Application Flet de préparation de photos d'identité :

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

Variables d'environnement reconnues
-------------------------------------
FOLDER_PATH    : dossier source des images (défaut : répertoire du script)
SELECTED_FILES : noms de fichiers séparés par « | » à traiter en priorité

Notes
-----
Au premier lancement, rembg télécharge automatiquement le modèle u2net_human_seg
(~175 Mo) dans ``~/.u2net/``. Les modèles spandrel (RealESRGAN, FaceUpSharpDAT)
sont téléchargés dans ``~/.cache/enhance_id/`` au premier usage (~350 Mo au total).

Version : 1.2.0
"""

__version__ = "1.2.0"

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
    "Noir":  (0, 0, 0),
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
    page.window.height = 640
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
        "bg_blur":   False,  # True = fond flou (remplace la couleur de fond)
        "precise":   False,  # True = alpha matting précis pour rembg
        "working":   False,  # True pendant l'exécution de rembg
        "enhancing": False,  # True pendant face SR ou ESRGAN
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

    blur_switch = ft.Switch(
        label="Fond flou",
        active_color=BLUE,
        value=False,
        tooltip="Fond flou gaussien — recliquer pour annuler",
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

    enhance_progress_bar = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    enhance_status = ft.Text("", size=11, color=LIGHT_GREY)

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
        """Génère l'image (fond appliqué) et actualise la prévisualisation."""
        base = state["processed"] if state["processed"] is not None else state["orig_img"]
        if base is None:
            return
        bg_rgb = None if state["bg_blur"] else BG_COLORS[state["bg_color"]]
        rgb = apply_background(base, bg_rgb, state["orig_img"])
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

        state["enhancing"]            = True
        _set_all_ia_btns(True)
        enhance_progress_bar.value   = None  # indéterminé jusqu'au début des tuiles
        enhance_progress_bar.visible = True
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

        try:
            result = await asyncio.to_thread(_do_run)
            state["processed"] = result
            enhance_status.value = f"[OK] {model_name} → {result.width}×{result.height} px"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] {model_name} : {ex}"
        finally:
            enhance_progress_bar.value   = 1.0
            enhance_progress_bar.visible = False
            state["enhancing"]     = False
            _set_all_ia_btns(False)
            run_model_btn.disabled = not _list_pth_models()
            page.update()
            _render_preview()

    def on_blur_toggle(e) -> None:
        """Active/annule le fond flou."""
        state["bg_blur"] = bool(e.control.value)
        _render_preview()

    def on_precise_toggle(e) -> None:
        """Active/désactive le mode précis (alpha matting) pour rembg."""
        state["precise"] = bool(e.control.value)

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

        state["working"]     = True
        process_btn.disabled = True
        save_btn.disabled    = True
        progress_bar.value   = 0.0
        progress_bar.visible = True
        status_text.value    = "Traitement IA en cours…"
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
            if state["precise"]:
                r, g, b, a = img.split()
                a = a.filter(ImageFilter.MinFilter(7))
                img = Image.merge("RGBA", (r, g, b, a))
            return img

        try:
            result = await asyncio.to_thread(_do_rembg)
            state["processed"] = result
            status_text.value  = "[OK] Fond supprimé"
        except Exception as ex:
            status_text.value = f"[ERREUR] rembg : {ex}"
        finally:
            _stop_anim.set()
            await anim_task
            state["working"]     = False
            process_btn.disabled = False
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

    # Attacher les callbacks
    blur_switch.on_change      = on_blur_toggle
    precise_switch.on_change   = on_precise_toggle
    bg_radio.on_change         = on_bg_change
    prev_btn.on_click          = on_prev
    next_btn.on_click          = on_next
    process_btn.on_click       = on_process
    run_model_btn.on_click     = on_run_model
    refresh_btn.on_click       = on_refresh_models
    save_btn.on_click          = on_save

    # ------------------------------------------------------------------ #
    #                           MISE EN PAGE                              #
    # ------------------------------------------------------------------ #
    left_panel = ft.Column(
        [
            # Fond
            ft.Text("Couleur de fond", size=13, weight=ft.FontWeight.BOLD, color=WHITE),
            bg_radio,
            blur_switch,
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
            enhance_status,
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
