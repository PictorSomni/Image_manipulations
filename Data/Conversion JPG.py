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

__version__ = "2.1.4"

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
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSIONS = (".avif",".heic", ".webp", ".png", ".tiff", ".jpeg", ".bmp", ".gif", ".psd", ".svg", ".ico", ".jfif", ".jpe", ".jif", ".jfi", ".pdf")
all_files = [file for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSIONS]
FOLDER = [f for f in all_files if f.name in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

def folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans PATH s'il n'existe pas encore."""
    folder_path = PATH / folder_name
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
print(f"Conversion en JPG")
print(f"Dossier de travail: {PATH}")
print(f"Fichiers trouvés: {TOTAL}")

if TOTAL == 0:
    print("Aucun fichier à convertir trouvé.")
else:
    for i, file in enumerate(FOLDER):
        file_name = file.stem
        file_extension = file.suffix.lower()
        print(f"Image {i+1} sur {TOTAL}: {file.name}")
        folder(f"{file_extension[1:]}")

        try:
            if file_extension == ".pdf":
                pdf_doc = fitz.open(str(file))
                page_count = len(pdf_doc)
                for j, page in enumerate(pdf_doc):
                    print(f"  - Conversion de la page {j+1} sur {page_count}")
                    pix = page.get_pixmap(dpi=300)
                    jpg_path = PATH / f"{file_name}_{j+1:03}.jpg"
                    pix.save(str(jpg_path))
                pdf_doc.close()
                print(f"  [OK] Converti: {page_count} page(s)")
            else:
                with Image(filename=str(file)) as actual_file:
                    image = actual_file.convert('jpg')
                    jpg_path = PATH / f"{file_name}.jpg"
                    image.save(filename=str(jpg_path))
                print(f"  [OK] Converti: {file_name}.jpg")

            dest_folder = PATH / f"{file_extension[1:]}"
            file.rename(dest_folder / file.name)
        except Exception as e:
            print(f"  [X] Erreur pour {file.name}: {e}")

print("Terminé")