# -*- coding: utf-8 -*-

__version__ = "1.6.9"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from pathlib import Path
from PIL import Image, ImageFile, ImageOps

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent
os.chdir(PATH)

# Récupère le chemin du dossier Data depuis l'environnement (si lancé via Dashboard)
DATA_PATH = Path(os.environ.get("DATA_PATH", PATH))

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer la taille depuis la variable d'environnement
try:
    MAXSIZE_VALUE = int(os.environ.get("RESIZE_WATERMARK_SIZE", "640"))
    MAXSIZE = (MAXSIZE_VALUE, MAXSIZE_VALUE)
except ValueError:
    print("Erreur : La variable d'environnement RESIZE_WATERMARK_SIZE doit être un nombre.")
    sys.exit()

# Configuration du watermark
WATERMARK_PATH = DATA_PATH / "watermark.png"
ALPHA = 0.35  # Transparence du watermark
QUALITY = 85  # Qualité JPEG

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
all_files = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
if TOTAL == 0:
    print("Aucune image trouvée dans le dossier.")
    sys.exit()

# Vérifier que le watermark existe
if not WATERMARK_PATH.exists():
    print(f"Erreur : Watermark introuvable à {WATERMARK_PATH}")
    sys.exit()

# Charger le watermark une seule fois
try:
    watermark = Image.open(str(WATERMARK_PATH))
    if watermark.mode != "RGBA":
        watermark = watermark.convert("RGBA")
    
    # Appliquer la transparence
    r, g, b, a = watermark.split()
    a = a.point(lambda i: int(i * ALPHA))
    watermark = Image.merge("RGBA", (r, g, b, a))
except Exception as e:
    print(f"Erreur lors du chargement du watermark : {e}")
    sys.exit()

output_folder = PATH / f"Projet_{MAXSIZE[0]}px"
output_folder.mkdir(exist_ok=True)

for i, file in enumerate(FOLDER):
    print(f"Image {i+1} sur {TOTAL}")
    print(f"Fichier : {file}")

    try:
        base_image = Image.open(file)
    except Exception as e:
        print(f"Erreur lors de l'ouverture : {e}")
        continue
    
    try:
        # Respect EXIF orientation first
        base_image = ImageOps.exif_transpose(base_image)
        original_size = base_image.size
        
        # Thumbnail maintient le ratio et réduit uniquement si nécessaire
        base_image.thumbnail(MAXSIZE, Image.Resampling.LANCZOS)
        new_size = base_image.size
        
        # Convertir en RGBA pour le watermark
        if base_image.mode != "RGBA":
            base_image = base_image.convert("RGBA")
        
        # Appliquer le watermark
        base_image.paste(watermark, (0, 0), watermark)
        
        # Convertir en RGB pour la sauvegarde JPEG
        base_image = base_image.convert("RGB")
        filename, _ = os.path.splitext(file)
        output_path = output_folder / f"{filename}.jpg"
        base_image.save(output_path, format='JPEG', subsampling=0, quality=QUALITY)
        
        print(f"  {original_size[0]}x{original_size[1]} -> {new_size[0]}x{new_size[1]}")
    except Exception as e:
        print(f"Erreur lors du traitement : {e}")
        continue

print("Termine !")
