# -*- coding: utf-8 -*-
"""
Convertit un lot de fichiers images (HEIC, WEBP, AVIF, PNG, TIFF, PDF…) en JPEG.

Utilise ImageMagick via ``wand`` pour les formats bitmap et PyMuPDF (``fitz``)
pour les PDF (une image par page à 300 DPI). Les fichiers originaux sont déplacés
dans un sous-dossier portant leur extension d'origine.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Wand (ImageMagick), PyMuPDF (fitz)
"""

__version__ = "2.6.6"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from wand.image import Image
import fitz  # PyMuPDF

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

convertible_extensions = (".avif", ".heic", ".webp", ".png", ".tiff", ".jpeg", ".bmp", ".gif", ".psd", ".svg", ".ico", ".jfif", ".jpe", ".jif", ".jfi", ".pdf")
all_files = [file for file in sorted(folder_path.iterdir()) if file.is_file() and file.suffix.lower() in convertible_extensions]
files_to_process = [file for file in all_files if file.name in selected_files_set] if selected_files_set else all_files
total_files_count = len(files_to_process)


def create_folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans folder_path s'il n'existe pas encore."""
    new_folder_path = folder_path / folder_name
    new_folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
print(f"Conversion en JPG")
print(f"Dossier de travail: {folder_path}")
print(f"Fichiers trouvés: {total_files_count}")

if total_files_count == 0:
    print("Aucun fichier à convertir trouvé.")
else:
    for index, file in enumerate(files_to_process):
        file_name = file.stem
        file_extension = file.suffix.lower()
        print(f"Image {index + 1}/{total_files_count}")
        create_folder(f"{file_extension[1:]}")

        try:
            if file_extension == ".pdf":
                pdf_document = fitz.open(str(file))
                page_count = len(pdf_document)
                for page_index, page in enumerate(pdf_document):
                    print(f"  - Conversion de la page {page_index + 1}/{page_count}")
                    pixmap_image = page.get_pixmap(dpi=300)
                    jpg_path = folder_path / f"{file_name}_{page_index + 1:03}.jpg"
                    pixmap_image.save(str(jpg_path))
                pdf_document.close()
            else:
                with Image(filename=str(file)) as actual_file:
                    actual_file.format = 'jpeg'
                    jpg_path = folder_path / f"{file_name}.jpg"
                    actual_file.save(filename=str(jpg_path))

            dest_folder = folder_path / f"{file_extension[1:]}"
            file.rename(dest_folder / file.name)
        except Exception as exception:
            print(f"  [X] Erreur pour {file.name}: {exception}")

print("Terminé")
