__version__ = "2.8.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from shutil import copy2

#############################################################
#                           PATH                            #
#############################################################
folder_path = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_string = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_string.split("|")) if selected_files_string else None

all_files = [file.name for file in sorted(folder_path.iterdir()) if file.is_file()]
files_to_process = [file_name for file_name in all_files if file_name in selected_files_set] if selected_files_set else all_files
total_files_count = len(files_to_process)


def create_folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans folder_path s'il n'existe pas encore."""
    new_folder_path = folder_path / folder_name
    new_folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    create_folder("SELECTION")
    print(f"Fichier {index + 1} sur {total_files_count}")

    copy2(folder_path / file_name, folder_path / "SELECTION" / file_name)


print("Terminé !")