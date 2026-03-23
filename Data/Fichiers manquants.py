# -*- coding: utf-8 -*-
"""
Compare deux répertoires et identifie les fichiers présents à la source mais absents
de la destination.

Lorsque lancé depuis le Dashboard, ``SELECTED_FILES`` doit contenir le chemin du
dossier de destination (passé en tant que sélection de dossier unique). Le script
affiche les fichiers manquants et les sélectionne automatiquement dans la preview
via le préfixe ``SELECTED_FILES:``.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — chemin du dossier de destination (fichier/dossier sélectionné).
"""

__version__ = "1.9.1"

ENV_SELECTED_FILES_KEY = "SELECTED_FILES"
OUTPUT_SELECTED_FILES_PREFIX = "SELECTED_FILES:"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
import re

#############################################################
#                         HELPERS                           #
#############################################################
_COPIES_PREFIX_RE = re.compile(r'^\d+X_', re.IGNORECASE)

def strip_copies_prefix(name: str) -> str:
    """Supprime le préfixe de compteur d'impression (ex: '3X_') si présent."""
    return _COPIES_PREFIX_RE.sub('', name)

#############################################################
#                          CONTENT                          #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_dir_str = os.environ.get("SELECTED_FILES", "")
# Le Dashboard transmet uniquement le nom de base du dossier sélectionné ;
# on reconstruit le chemin absolu en le résolvant par rapport à PATH.
dest_dir = None
if selected_dir_str:
    first_item = selected_dir_str.split("|")[0]
    if os.path.isdir(first_item):          # chemin absolu (cas rare)
        dest_dir = Path(first_item)
    elif os.path.isdir(PATH / first_item): # nom de base relatif à PATH
        dest_dir = PATH / first_item

#############################################################
#                           MAIN                            #
#############################################################
if dest_dir:
    # Déterminer le dossier de travail (cwd si lancé depuis Dashboard, sinon PATH)
    all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file()]
    copied_files = [file.name for file in sorted(dest_dir.iterdir()) if file.is_file()]
    # Construire un ensemble des noms présents dans la destination en ignorant
    # le préfixe de compteur d'impression ajouté par Recadrage.pyw (ex: "3X_").
    copied_basenames = {strip_copies_prefix(f) for f in copied_files}
    missing_files = [file for file in all_files if file not in copied_basenames and not file.startswith('.') and not file.endswith('.py')]
    print(f"{len(missing_files)} fichier(s) manquant(s) dans le dossier {dest_dir}.")
    missing_files_str = "|".join(os.path.basename(f) for f in missing_files)
    os.environ[ENV_SELECTED_FILES_KEY] = missing_files_str
    print(f"{OUTPUT_SELECTED_FILES_PREFIX}{missing_files_str}")
else:
    print("Sélectionnez un dossier de destination valide.")
