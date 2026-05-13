# -*- coding: utf-8 -*-
"""
Trie les fichiers RAW : déplace dans ``RAW/AUTRES/`` tous les fichiers qui
ne correspondent PAS aux photos de la SELECTION (ou JPG). Les RAW de la
sélection restent dans le dossier RAW.

Détection automatique des dossiers depuis le dossier de départ :
  - Nom "RAW"             → cherche SELECTION*/JPG dans le dossier parent.
  - Nom "SELECTION*"/"JPG"→ cherche RAW/ dans le dossier parent.
  - Autre (dossier session)→ cherche RAW/ et SELECTION*/JPG comme sous-dossiers.

La correspondance tolère le préfixe kiosk (ex : ``2X_102x152_DSC1234.jpg``
correspond à ``DSC1234.nef`` grâce à une comparaison par sous-chaîne).

Aucune UI : file picker direct si aucun dossier n'est fourni, puis fermeture.

Variables d'environnement :
  FOLDER_PATH     — dossier de départ (session, RAW ou SELECTION).
  SELECTED_FILES  — chemin optionnel d'un dossier SELECTION* (prioritaire).
"""

__version__ = "2.4.7"

#############################################################
#                          IMPORTS                          #
#############################################################
import re
import sys
import os
import shutil
import tkinter
import tkinter.filedialog
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS

#############################################################
#                        CONSTANTES                         #
#############################################################
RAW_EXTENSIONS = {
    ".nef", ".cr2", ".cr3", ".arw", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw",
    ".3fr", ".x3f", ".mrw", ".nrw",
}

AUTRES_SUBFOLDER_NAME = "AUTRES"
COMMANDE_FILENAME     = "commande.txt"

# Préfixe kiosk : ex. "2X_102x152_DSC1234" → groupe 1 = "DSC1234"
_KIOSK_PREFIX_RE = re.compile(r'^\d+x_\d+x\d+_(.+)$', re.IGNORECASE)

#############################################################
#                         HELPERS                           #
#############################################################

def _find_selection_candidates(folder: Path) -> list[Path]:
    """Retourne les sous-dossiers SELECTION* triés dans ``folder``."""
    return sorted(
        (entry for entry in folder.iterdir()
         if entry.is_dir() and entry.name.upper().startswith("SELECTION")),
        key=lambda path: (len(path.name), path.name),
    )


def _find_selection_or_jpg(folder: Path) -> Path | None:
    """
    Retourne le dossier SELECTION/JPG de la session depuis ``folder``.

    Ordre de recherche :
      1. SELECTION* directement dans ``folder``.
      2. SELECTION* à l'intérieur de ``folder/JPG/``.
      3. ``folder/JPG/`` lui-même.
    """
    candidates = _find_selection_candidates(folder)
    if candidates:
        return candidates[-1]

    jpg_folder = folder / "JPG"
    if jpg_folder.is_dir():
        candidates_in_jpg = _find_selection_candidates(jpg_folder)
        if candidates_in_jpg:
            return candidates_in_jpg[-1]
        return jpg_folder

    return None


def _resolve_folders(start: Path) -> tuple[Path | None, Path | None]:
    """
    Retourne ``(raw_folder, selection_folder)`` depuis un dossier de départ.

    Règles de détection par nom du dossier :
      - "RAW"                → raw = start, selection = cherche depuis parent
      - "SELECTION*"         → selection = start, raw = session/RAW
                               (session = parent.parent si parent est JPG, sinon parent)
      - "JPG"               → selection = SELECTION* dans start (ou start), raw = parent/RAW
      - autre (session)     → raw = start/RAW, selection = cherche depuis start
    """
    name_upper = start.name.upper()
    parent     = start.parent

    if name_upper == "RAW":
        return start, _find_selection_or_jpg(parent)

    if name_upper.startswith("SELECTION"):
        # SELECTION peut être directement dans la session ou dans session/JPG/
        session = parent.parent if parent.name.upper() == "JPG" else parent
        raw_folder = session / "RAW"
        return (raw_folder if raw_folder.is_dir() else None), start

    if name_upper == "JPG":
        raw_folder = parent / "RAW"
        candidates = _find_selection_candidates(start)
        selection  = candidates[-1] if candidates else start
        return (raw_folder if raw_folder.is_dir() else None), selection

    # Dossier session : RAW et SELECTION sont des sous-dossiers
    raw_subfolder = start / "RAW"
    raw_folder    = raw_subfolder if raw_subfolder.is_dir() else None
    return raw_folder, _find_selection_or_jpg(start)


def _strip_kiosk_prefix(stem_lower: str) -> str:
    """Retire le préfixe kiosk (ex: '2x_102x152_dsc1234' → 'dsc1234')."""
    match = _KIOSK_PREFIX_RE.match(stem_lower)
    return match.group(1) if match else stem_lower


def _collect_stems(selection_folder: Path) -> set[str]:
    """
    Retourne l'ensemble des stems originaux (sans préfixe kiosk, sans extension,
    en minuscules) des fichiers présents directement dans ``selection_folder``,
    en ignorant commande.txt.
    """
    return {
        _strip_kiosk_prefix(entry.stem.lower())
        for entry in selection_folder.iterdir()
        if entry.is_file() and entry.name.lower() != COMMANDE_FILENAME
    }


def _raw_matches_selection(raw_stem_lower: str, selection_stems: set[str]) -> bool:
    """
    Retourne True si ``raw_stem_lower`` figure dans ``selection_stems``.
    Les stems de sélection ont déjà été dépréfixés (préfixe kiosk retiré),
    la comparaison est donc exacte.
    """
    return raw_stem_lower in selection_stems


def _find_non_matching_raw_files(raw_folder: Path, selection_stems: set[str]) -> list[Path]:
    """Retourne les fichiers RAW de ``raw_folder`` ne correspondant PAS à ``selection_stems``."""
    return [
        entry for entry in sorted(raw_folder.iterdir())
        if entry.is_file()
        and entry.suffix.lower() in RAW_EXTENSIONS
        and not _raw_matches_selection(entry.stem.lower(), selection_stems)
    ]


def _move_raws(raw_files: list[Path], destination: Path) -> tuple[int, list[str]]:
    """Déplace ``raw_files`` dans ``destination``. Retourne (nombre_déplacés, erreurs)."""
    destination.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    errors: list[str] = []
    for raw_path in raw_files:
        destination_path = destination / raw_path.name
        if destination_path.exists():
            errors.append(f"Déjà présent, ignoré : {raw_path.name}")
            continue
        try:
            shutil.move(str(raw_path), destination_path)
            moved_count += 1
        except OSError as move_error:
            errors.append(f"{raw_path.name} : {move_error}")
    return moved_count, errors

#############################################################
#                           MAIN                            #
#############################################################

def run(start_folder: Path) -> None:
    raw_folder, selection_folder = _resolve_folders(start_folder)

    if not raw_folder or not raw_folder.is_dir():
        print(f"[x] Dossier RAW introuvable depuis '{start_folder.name}'", flush=True)
        return

    if not selection_folder or not selection_folder.is_dir():
        print(f"[x] Dossier SELECTION/JPG introuvable depuis '{start_folder.name}'", flush=True)
        return

    selection_stems = _collect_stems(selection_folder)

    if not selection_stems:
        print(f"[x] Aucune photo dans '{selection_folder.name}'", flush=True)
        return

    non_matching_files = _find_non_matching_raw_files(raw_folder, selection_stems)
    if not non_matching_files:
        print("[ok] Tous les RAW correspondent à la sélection, rien à déplacer.", flush=True)
        return

    destination = raw_folder / AUTRES_SUBFOLDER_NAME
    moved_count, errors = _move_raws(non_matching_files, destination)

    for error_line in errors:
        print(f"[WARN] {error_line}", flush=True)
    print(
        f"[ok] {moved_count} RAW(s) déplacés → {raw_folder.name}/{AUTRES_SUBFOLDER_NAME}/",
        flush=True,
    )


# ── Résolution du dossier de départ ───────────────────────────────────
environment_folder    = os.environ.get("FOLDER_PATH",    "").strip()
environment_selection = os.environ.get("SELECTED_FILES", "").strip()

start_folder: Path | None = None

# SELECTED_FILES peut pointer directement sur un dossier SELECTION*
if environment_selection:
    first_item = Path(environment_selection.split("|")[0].strip())
    if first_item.is_dir() and first_item.name.upper().startswith("SELECTION"):
        start_folder = first_item

if start_folder is None and environment_folder and os.path.isdir(environment_folder):
    start_folder = Path(environment_folder)

if start_folder is None:
    root = tkinter.Tk()
    root.withdraw()
    picked = tkinter.filedialog.askdirectory(
        title="Sélectionner le dossier (session, RAW ou SELECTION)",
    )
    root.destroy()
    if picked:
        start_folder = Path(picked)

if start_folder is not None:
    run(start_folder)
else:
    print("[x] Aucun dossier fourni.", flush=True)

