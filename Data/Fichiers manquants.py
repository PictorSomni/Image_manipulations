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

__version__ = "1.7.6"

ENV_SELECTED_FILES_KEY = "SELECTED_FILES"
OUTPUT_SELECTED_FILES_PREFIX = "SELECTED_FILES:"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os

#############################################################
#                          CONTENT                          #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_dir_str = os.environ.get("SELECTED_FILES", "")
selected_dir_set = set(selected_dir_str.split("|")) if selected_dir_str else None
dest_dir = Path(selected_dir_str) if os.path.isdir(selected_dir_str) else None

#############################################################
#                           MAIN                            #
#############################################################
if dest_dir:
    # Déterminer le dossier de travail (cwd si lancé depuis Dashboard, sinon PATH)
    all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file()]
    copied_files = [file.name for file in sorted(dest_dir.iterdir()) if file.is_file()]
    missing_files = [file for file in all_files if file not in copied_files and not file.startswith('.') and not file.endswith('.py')]
    print(f"{len(missing_files)} fichier(s) manquant(s) dans le dossier {dest_dir} :")
    for file in missing_files:
        print(f"- {file}")
    missing_files_str = "|".join(os.path.basename(f) for f in missing_files)
    os.environ[ENV_SELECTED_FILES_KEY] = missing_files_str
    print(f"{OUTPUT_SELECTED_FILES_PREFIX}{missing_files_str}")
else:
    print("Sélectionnez un dossier de destination valide.")


#############################################################
#                           MAIN                            #
#############################################################

