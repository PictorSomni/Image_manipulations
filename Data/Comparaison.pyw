# -*- coding: utf-8 -*-
"""
Comparaison.pyw — Comparaison côte à côte de deux lots d'images (Flet)
=======================================================================

Charge en parallèle les images de deux dossiers, les affiche côte à côte
dans des visionneuses synchronisées (pan + zoom identiques), puis permet
de choisir quelle version conserver.

Action "Valider" :
  · L'image choisie est copiée dans SELECTION/ (sous le dossier 1).
  · L'image rejetée est déplacée dans AUTRES/{sous-dossier}/ :
      - si elle provient du dossier 2 → AUTRES/{nom_dossier2}/{fichier}
      - si elle provient du dossier 1 → AUTRES/{fichier}

Variables d'environnement :
  FOLDER_PATH    — dossier 1 (obligatoire si lancé depuis Dashboard).
  SECOND_FOLDER  — dossier 2 (optionnel ; sinon l'app demande le dossier).

Dépendances : flet >= 0.84, Pillow
"""

__version__ = "2.2.0"

# ─────────────────────────────────────────────────────────────────────────────
#  IMPORTS
# ─────────────────────────────────────────────────────────────────────────────
import flet as ft
import os
import shutil
import difflib
from pathlib import Path

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None


# ─────────────────────────────────────────────────────────────────────────────
#  CONSTANTES
# ─────────────────────────────────────────────────────────────────────────────
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}

DARK         = "#222429"
BACKGROUND   = "#373d4a"
GREY         = "#2C3038"
LIGHT_GREY   = "#9399A6"
BLUE         = "#45B8F5"
VIOLET       = "#B587FE"
GREEN        = "#49B76C"
YELLOW       = "#FBCD5F"
HOVER_YELLOW = "#F9BA4E"
ORANGE       = "#FFA071"
RED          = "#F17171"
WHITE        = "#c7ccd8"

# ─────────────────────────────────────────────────────────────────────────────
#  UTILITAIRES
# ─────────────────────────────────────────────────────────────────────────────
def _get_image_files(folder: str) -> list:
    """Retourne la liste triée des images dans le dossier (niveau 1 seulement)."""
    p = Path(folder)
    return sorted(
        [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS],
        key=lambda f: f.name.lower(),
    )


def _match_score(stem1: str, stem2: str) -> tuple:
    """
    Retourne (substring_len, ratio) pour trier les candidats.
    - substring_len : longueur de stem1 si stem1 ⊆ stem2 (ou inversement),
                      0 si aucun containment.
    - ratio         : similarité globale SequenceMatcher (départage à égalité).
    Le containment strict est requis : pas de fallback préfixe.
    """
    if stem1 in stem2:
        sub = len(stem1)
    elif stem2 in stem1:
        sub = len(stem2)
    else:
        sub = 0
    ratio = difflib.SequenceMatcher(None, stem1, stem2).ratio()
    return sub, ratio


def _match_pairs(files1: list, files2: list) -> list:
    """
    Associe chaque image de files1 à la meilleure correspondance dans files2.

    Règle : le stem du fichier dossier 1 doit être entièrement contenu dans
    le stem du fichier dossier 2 (ou inversement). Le ratio SequenceMatcher
    sert uniquement à départager deux candidats de même longueur de containment.
    """
    if not files1 or not files2:
        return []

    unmatched2 = list(files2)
    pairs = []

    for f1 in files1:
        if not unmatched2:
            break
        stem1 = f1.stem.lower()

        best_sub   = 0
        best_ratio = -1.0
        best_idx   = -1
        for i, f2 in enumerate(unmatched2):
            stem2 = f2.stem.lower()
            sub, ratio = _match_score(stem1, stem2)
            if sub > best_sub or (sub == best_sub and sub > 0 and ratio > best_ratio):
                best_sub   = sub
                best_ratio = ratio
                best_idx   = i

        # Paire acceptée uniquement si containment réel (sub > 0)
        if best_idx >= 0 and best_sub > 0:
            pairs.append((f1, unmatched2.pop(best_idx)))

    return pairs


def _find_resume_index(pairs_list: list, base_dir: Path) -> int:
    """
    Vérifie les dossiers SELECTION et AUTRES dans base_dir pour déterminer
    quelles paires ont déjà été traitées, et retourne l'index de la première
    paire non encore traitée.
    """
    sel_dir = base_dir / "SELECTION"
    aut_dir = base_dir / "AUTRES"

    if not sel_dir.is_dir() and not aut_dir.is_dir():
        return 0

    # Collecter tous les noms de fichiers déjà traités (SELECTION + AUTRES/*)
    processed_names: set[str] = set()
    for folder in (sel_dir, aut_dir):
        if folder.is_dir():
            for f in folder.rglob("*"):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                    processed_names.add(f.name.lower())

    if not processed_names:
        return 0

    # Première paire dont aucun des deux fichiers n'est déjà traité
    for i, (p1, p2) in enumerate(pairs_list):
        if p1.name.lower() not in processed_names and p2.name.lower() not in processed_names:
            return i

    return len(pairs_list)  # Toutes les paires ont déjà été traitées


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main(page: ft.Page):

    # ── Fenêtre ──────────────────────────────────────────────────────────
    page.title       = "Comparaison d'images"
    page.theme_mode  = ft.ThemeMode.DARK
    page.bgcolor     = BACKGROUND
    page.window.title_bar_hidden         = True
    page.window.title_bar_buttons_hidden = True
    page.window.width  = 1400
    page.window.height = 900
    page.window.maximized = True

    # ── État global ──────────────────────────────────────────────────────
    folder1   = {"path": os.environ.get("FOLDER_PATH",    "").strip()}
    folder2   = {"path": os.environ.get("SECOND_FOLDER",  "").strip()}
    pairs     = {"list": []}
    cur_idx   = {"value": 0}
    choice    = {"value": 0}   # 0 = gauche (folder1), 1 = droite (folder2)

    # État partagé des visionneuses (zoom + pan)
    vs = {
        "scale":              1.0,
        "offset_x":           0.0,
        "offset_y":           0.0,
        "gesture_scale_start": 1.0,
    }

    # ── Widgets images ────────────────────────────────────────────────────
    _BLANK = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

    image_left  = ft.Image(src=_BLANK, fit=ft.BoxFit.CONTAIN, expand=True, gapless_playback=True)
    image_right = ft.Image(src=_BLANK, fit=ft.BoxFit.CONTAIN, expand=True, gapless_playback=True)

    cont_left  = ft.Container(content=image_left,  expand=True)
    cont_right = ft.Container(content=image_right, expand=True)

    # Overlay du dossier choisi (bordure colorée sur le panneau sélectionné)
    border_left  = ft.Container(
        expand=True,
        border=ft.Border.all(7, GREEN),
        border_radius=4,
    )
    border_right = ft.Container(
        expand=True,
        border=ft.Border.all(7, ft.Colors.TRANSPARENT),
        border_radius=4,
    )

    stack_left  = ft.Stack(
        controls=[cont_left,  border_left],
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )
    stack_right = ft.Stack(
        controls=[cont_right, border_right],
        expand=True,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )

    # ── Labels ───────────────────────────────────────────────────────────
    folder1_lbl  = ft.Text("", size=11, color=LIGHT_GREY, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, expand=True)
    folder2_lbl  = ft.Text("", size=11, color=LIGHT_GREY, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, expand=True)
    fname1_text  = ft.Text("—", size=12, color=WHITE, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                           text_align=ft.TextAlign.CENTER)
    fname2_text  = ft.Text("—", size=12, color=WHITE, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS, expand=True,
                           text_align=ft.TextAlign.CENTER)
    counter_text = ft.Text("0 / 0", size=12, color=LIGHT_GREY,
                           text_align=ft.TextAlign.CENTER, width=80)
    status_text  = ft.Text("", size=12, color=LIGHT_GREY,
                           text_align=ft.TextAlign.CENTER, expand=True)
    progress_bar = ft.ProgressBar(value=0, bgcolor=GREY, color=BLUE, height=3)

    # ── Segmented button ─────────────────────────────────────────────────
    choice_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        bgcolor=GREY,
        thumb_color=DARK,
        controls=[
            ft.Text("◀  Gauche", size=13, color=WHITE),
            ft.Text("Droite  ▶", size=13, color=WHITE),
        ],
    )

    # ── Barre de titre ────────────────────────────────────────────────────
    async def _close(e):
        await page.window.close()

    def _minimize(e):
        page.window.minimized = True

    def _toggle_maximize(e):
        page.window.maximized = not page.window.maximized
        page.update()

    title_bar = ft.WindowDragArea(
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.COMPARE, color=VIOLET, size=18),
                ft.Text(f"Comparaison  v{__version__}",
                        size=14, color=WHITE, weight=ft.FontWeight.W_500),
                ft.Container(expand=True),
                ft.IconButton(icon=ft.Icons.REMOVE, icon_size=16,
                              on_click=_minimize, tooltip="Réduire"),
                ft.IconButton(icon=ft.Icons.FULLSCREEN, icon_size=16,
                              on_click=_toggle_maximize, tooltip="Maximiser"),
                ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16,
                              on_click=_close, tooltip="Fermer"),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=DARK, padding=ft.Padding(10, 6, 6, 6),
        )
    )

    # ═════════════════════════════════════════════════════════════════════
    #  TRANSFORM / VISIONNEUSE
    # ═════════════════════════════════════════════════════════════════════
    def _viewer_size():
        """Retourne (w, h) du viewer en pixels (estimé depuis les dims de la page)."""
        pw = page.width  or 1400
        ph = page.height or 900
        return max(100, (int(pw) - 40) // 2), max(100, int(ph) - 140)

    def _update_transform():
        """Applique zoom + pan aux deux visionneuses simultanément."""
        vw, vh = _viewer_size()
        scale_t  = ft.Scale(vs["scale"], alignment=ft.Alignment(0, 0))
        # ft.Offset est fractionnel (× taille du contrôle) → convertir depuis pixels
        offset_t = ft.Offset(vs["offset_x"] / vw, vs["offset_y"] / vh)
        cont_left.scale  = scale_t;  cont_left.offset  = offset_t;  cont_left.update()
        cont_right.scale = scale_t;  cont_right.offset = offset_t;  cont_right.update()

    def _reset_view():
        vs["scale"]    = 1.0
        vs["offset_x"] = 0.0
        vs["offset_y"] = 0.0
        _update_transform()

    # Gestionnaires de gestes (partagés par les deux GestureDetector)
    def on_gesture_start(e):
        vs["gesture_scale_start"] = vs["scale"]

    def on_gesture_update(e):
        vs["scale"] = max(0.1, min(10.0,
                          vs["gesture_scale_start"] * e.scale))
        vs["offset_x"] += e.focal_point_delta.x
        vs["offset_y"] += e.focal_point_delta.y
        _update_transform()

    def on_gesture_scroll(e):
        dy = e.scroll_delta.y
        if dy != 0:
            vs["scale"] = max(0.1, min(10.0,
                              vs["scale"] * (1.0 - dy * 0.002)))
            _update_transform()

    def _select_side(side: int):
        """Sélectionne le côté 0=gauche, 1=droite et met à jour le bouton."""
        choice["value"] = side
        choice_segment.selected_index = side
        choice_segment.update()
        _update_border()

    gesture_left = ft.GestureDetector(
        content=stack_left,
        expand=True,
        mouse_cursor=ft.MouseCursor.MOVE,
        on_tap=lambda e: _select_side(0),
        on_scale_start=on_gesture_start,
        on_scale_update=on_gesture_update,
        on_scroll=on_gesture_scroll,
    )
    gesture_right = ft.GestureDetector(
        content=stack_right,
        expand=True,
        mouse_cursor=ft.MouseCursor.MOVE,
        on_tap=lambda e: _select_side(1),
        on_scale_start=on_gesture_start,
        on_scale_update=on_gesture_update,
        on_scroll=on_gesture_scroll,
    )

    # ═════════════════════════════════════════════════════════════════════
    #  NAVIGATION ENTRE PAIRES
    # ═════════════════════════════════════════════════════════════════════
    def _load_pair(idx: int):
        pl = pairs["list"]
        if not pl or idx >= len(pl):
            return
        p1, p2 = pl[idx]
        vs["scale"] = 1.0;  vs["offset_x"] = 0.0;  vs["offset_y"] = 0.0
        image_left.src  = str(p1)
        image_right.src = str(p2)
        cont_left.scale  = ft.Scale(1.0);  cont_left.offset  = ft.Offset(0, 0)
        cont_right.scale = ft.Scale(1.0);  cont_right.offset = ft.Offset(0, 0)
        n = len(pl)
        fname1_text.value  = p1.name
        fname2_text.value  = p2.name
        counter_text.value = f"{idx + 1} / {n}"
        progress_bar.value = (idx + 1) / n
        status_text.value  = ""
        page.update()

    def _next_pair():
        idx = cur_idx["value"] + 1
        if idx >= len(pairs["list"]):
            _show_completion()
            return
        cur_idx["value"] = idx
        choice["value"]  = 0
        choice_segment.selected_index = 0
        _update_border()
        _load_pair(idx)

    # ═════════════════════════════════════════════════════════════════════
    #  ACTIONS
    # ═════════════════════════════════════════════════════════════════════
    def _update_border():
        """Met à jour la bordure verte selon le choix courant."""
        if choice["value"] == 0:
            border_left.border  = ft.Border.all(7, GREEN)
            border_right.border = ft.Border.all(7, ft.Colors.TRANSPARENT)
        else:
            border_left.border  = ft.Border.all(7, ft.Colors.TRANSPARENT)
            border_right.border = ft.Border.all(7, GREEN)
        try:
            border_left.update()
            border_right.update()
        except Exception:
            pass

    def on_choice_change(e):
        choice["value"] = e.control.selected_index
        _update_border()

    def on_validate(e):
        pl = pairs["list"]
        if not pl:
            return
        idx = cur_idx["value"]
        if idx >= len(pl):
            return

        p1, p2 = pl[idx]
        base_dir = Path(folder1["path"])
        sel_dir  = base_dir / "SELECTION"
        aut_dir  = base_dir / "AUTRES"
        sel_dir.mkdir(exist_ok=True)
        aut_dir.mkdir(exist_ok=True)

        chosen_val = choice["value"]

        if chosen_val == 0:
            # Garder gauche (folder1)
            chosen_path   = p1
            rejected_path = p2
            # Le rejeté vient de folder2 → AUTRES/{nom_dossier2}/
            subfolder = aut_dir / Path(folder2["path"]).name
        else:
            # Garder droite (folder2)
            chosen_path   = p2
            rejected_path = p1
            # Le rejeté vient de folder1 → AUTRES/ directement
            subfolder = aut_dir

        subfolder.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(str(chosen_path), str(sel_dir / chosen_path.name))
            shutil.move(str(rejected_path), str(subfolder / rejected_path.name))
            status_text.value = f"✓  {chosen_path.name}"
        except Exception as err:
            status_text.value = f"Erreur : {err}"
            page.update()
            return

        _next_pair()

    def on_skip(e):
        _next_pair()

    def on_reset_view(e):
        _reset_view()
        page.update()

    # ── Complétion ───────────────────────────────────────────────────────
    def _show_completion():
        n = len(pairs["list"])
        fname1_text.value  = "—"
        fname2_text.value  = "—"
        counter_text.value = f"{n} / {n}"
        progress_bar.value = 1.0
        status_text.value  = f"[OK]  Toutes les paires ont été traitées ({n} image(s))."
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  INITIALISATION DES PAIRES
    # ═════════════════════════════════════════════════════════════════════
    def _build_pairs_and_start():
        f1 = folder1["path"]
        f2 = folder2["path"]

        if not f1 or not os.path.isdir(f1):
            status_text.value = f"Dossier 1 introuvable : {repr(f1)}"
            page.update()
            return
        if not f2 or not os.path.isdir(f2):
            status_text.value = f"Dossier 2 introuvable : {repr(f2)}"
            page.update()
            return

        imgs1 = _get_image_files(f1)
        imgs2 = _get_image_files(f2)

        if not imgs1:
            status_text.value = f"Aucune image dans {os.path.basename(f1)}."
            page.update()
            return
        if not imgs2:
            status_text.value = f"Aucune image dans {os.path.basename(f2)}."
            page.update()
            return

        matched = _match_pairs(imgs1, imgs2)
        pairs["list"] = matched

        # Reprendre là où on s'était arrêté
        resume_idx = _find_resume_index(matched, Path(f1))
        cur_idx["value"] = resume_idx
        choice["value"]  = 0

        # Mettre à jour les labels de dossiers
        folder1_lbl.value = f"◀  {f1}"
        folder2_lbl.value = f"▶  {f2}"

        # Masquer l'écran de configuration, afficher le comparateur
        setup_overlay.visible = False
        main_col.visible      = True
        page.update()

        if resume_idx >= len(matched):
            _show_completion()
        else:
            if resume_idx > 0:
                status_text.value = f"-->  Reprise à la paire {resume_idx + 1} ({resume_idx} déjà traitée(s))"
            _load_pair(resume_idx)

    # ═════════════════════════════════════════════════════════════════════
    #  ÉCRAN DE CONFIGURATION (si SECOND_FOLDER non fourni)
    # ═════════════════════════════════════════════════════════════════════
    setup_folder1_field = ft.TextField(
        label="Dossier 1 (source principale)",
        value=folder1["path"],
        hint_text="Chemin du premier dossier",
        bgcolor=DARK, border_color=GREY,
        expand=True, read_only=False,
        text_size=13,
    )
    setup_folder2_field = ft.TextField(
        label="Dossier 2 (à comparer)",
        value=folder2["path"],
        hint_text="Chemin du second dossier",
        bgcolor=DARK, border_color=GREY,
        expand=True, read_only=False,
        text_size=13,
    )

    setup_status = ft.Text("", size=12, color=RED, text_align=ft.TextAlign.CENTER)

    async def _pick_folder1(e):
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Sélectionner le dossier 1")
        if picked:
            folder1["path"] = os.path.normpath(picked)
            setup_folder1_field.value = folder1["path"]
            setup_folder1_field.update()

    async def _pick_folder2(e):
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Sélectionner le dossier 2")
        if picked:
            folder2["path"] = os.path.normpath(picked)
            setup_folder2_field.value = folder2["path"]
            setup_folder2_field.update()

    def _on_start(e):
        f1 = (setup_folder1_field.value or "").strip()
        f2 = (setup_folder2_field.value or "").strip()
        if not f1 or not os.path.isdir(f1):
            setup_status.value = "Dossier 1 introuvable."
            setup_status.update()
            return
        if not f2 or not os.path.isdir(f2):
            setup_status.value = "Dossier 2 introuvable."
            setup_status.update()
            return
        if f1 == f2:
            setup_status.value = "Les deux dossiers doivent être différents."
            setup_status.update()
            return
        folder1["path"] = f1
        folder2["path"] = f2
        _build_pairs_and_start()

    setup_overlay = ft.Container(
        visible=True,
        expand=True,
        alignment=ft.Alignment(0, 0),
        content=ft.Container(
            width=620,
            bgcolor=DARK,
            border_radius=12,
            padding=ft.Padding(32, 28, 32, 28),
            border=ft.Border.all(1, GREY),
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.COMPARE, color=VIOLET, size=28),
                    ft.Text("Comparaison d'images",
                            size=18, color=WHITE, weight=ft.FontWeight.W_600),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(color=GREY, height=20),
                ft.Row([
                    setup_folder1_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Parcourir…", on_click=_pick_folder1,
                    ),
                ], spacing=6),
                ft.Row([
                    setup_folder2_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Parcourir…", on_click=_pick_folder2,
                    ),
                ], spacing=6),
                setup_status,
                ft.Container(height=8),
                ft.Row([
                    ft.Button(
                        "Démarrer",
                        icon=ft.Icons.PLAY_ARROW,
                        bgcolor=VIOLET, color=DARK,
                        style=ft.ButtonStyle(
                            shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=_on_start,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ),
    )

    # ═════════════════════════════════════════════════════════════════════
    #  INTERFACE PRINCIPALE (comparateur)
    # ═════════════════════════════════════════════════════════════════════
    choice_segment.on_change = on_choice_change

    validate_btn = ft.Button(
        "Valider",
        icon=ft.Icons.CHECK,
        bgcolor=GREEN, color=DARK,
        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        on_click=on_validate,
    )
    skip_btn = ft.OutlinedButton(
        "Ignorer",
        icon=ft.Icons.SKIP_NEXT,
        style=ft.ButtonStyle(
            side=ft.BorderSide(1, GREY),
            shape=ft.RoundedRectangleBorder(radius=8),
        ),
        on_click=on_skip,
    )
    reset_btn = ft.IconButton(
        icon=ft.Icons.FIT_SCREEN,
        icon_color=LIGHT_GREY,
        tooltip="Réinitialiser la vue",
        on_click=on_reset_view,
    )

    # Ligne d'en-tête des dossiers
    header_row = ft.Row([
        ft.Icon(ft.Icons.FOLDER, color=BLUE, size=14),
        folder1_lbl,
        ft.Container(width=20),
        ft.Icon(ft.Icons.FOLDER, color=ORANGE, size=14),
        folder2_lbl,
    ], spacing=4)

    # Ligne des visionneuses
    viewers_row = ft.Row([
        ft.Container(content=gesture_left,  expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE),
        ft.Container(width=8),
        ft.Container(content=gesture_right, expand=True, clip_behavior=ft.ClipBehavior.HARD_EDGE),
    ], spacing=0, expand=True)

    # Ligne des noms de fichiers + contrôles (fusionnés en une seule barre)
    controls_row = ft.Row([
        reset_btn,
        fname1_text,
        ft.Container(expand=True),
        choice_segment,
        ft.Container(expand=True),
        counter_text,
        ft.Container(width=8),
        skip_btn,
        ft.Container(width=8),
        validate_btn,
        ft.Container(width=16),
        fname2_text,
        status_text,
    ], alignment=ft.MainAxisAlignment.CENTER,
       vertical_alignment=ft.CrossAxisAlignment.CENTER)

    main_col = ft.Column([
        ft.Container(
            content=header_row,
            bgcolor=DARK,
            padding=ft.Padding(10, 6, 10, 6),
        ),
        ft.Container(content=viewers_row, expand=True),
        progress_bar,
        ft.Container(
            content=controls_row,
            bgcolor=DARK,
            height=64,
            padding=ft.Padding(10, 0, 10, 0),
        ),
    ], spacing=0, expand=True, visible=False)

    # ═════════════════════════════════════════════════════════════════════
    #  RACCOURCIS CLAVIER
    # ═════════════════════════════════════════════════════════════════════
    def on_keyboard(e: ft.KeyboardEvent):
        if e.key == "Enter":
            on_validate(None)
        elif e.key == "Escape":
            on_skip(None)
        elif e.key == "Tab":
            on_reset_view(None)

    page.on_keyboard_event = on_keyboard

    # ═════════════════════════════════════════════════════════════════════
    #  ASSEMBLAGE DE LA PAGE
    # ═════════════════════════════════════════════════════════════════════
    page.add(
        ft.Column([
            title_bar,
            ft.Divider(height=1, color=GREY),
            ft.Stack([
                main_col,
                setup_overlay,
            ], expand=True),
        ], spacing=0, expand=True)
    )

    # ── Démarrage auto ────────────────────────────────────────────────────
    if folder1["path"] and folder2["path"]:
        _build_pairs_and_start()
    elif folder1["path"]:
        setup_folder1_field.value = folder1["path"]
        setup_folder1_field.update()


ft.run(main)
