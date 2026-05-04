# -*- coding: utf-8 -*-
"""
Redimensionne des images à une dimension maximale en appliquant un filigrane.

Utilise ``Image.thumbnail`` pour conserver le ratio d'aspect, corrige l'orientation
EXIF via ``ImageOps.exif_transpose``, puis applique ``watermark.png`` avec une
opacité de 35 %. Les résultats sont enregistrés dans ``Projet_<N>px/``.

Variables d'environnement :
  FOLDER_PATH            — dossier source (défaut : répertoire du script).
  DATA_PATH              — chemin du dossier Data (pour trouver watermark.png).
  RESIZE_WATERMARK_SIZE  — dimension maximale en pixels (défaut : 640).
  SELECTED_FILES         — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Pillow (PIL)
"""

__version__ = "2.3.1"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from pathlib import Path
from PIL import Image, ImageFile, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))
os.chdir(PATH)

# Récupère le chemin du dossier Data depuis l'environnement (si lancé via Dashboard)
DATA_PATH = Path(os.environ.get("DATA_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer la taille depuis la variable d'environnement
try:
    MAXSIZE_VALUE = int(os.environ.get("RESIZE_WATERMARK_SIZE", str(CONSTANTS.RESIZE_DEFAULT)))
    MAXSIZE = (MAXSIZE_VALUE, MAXSIZE_VALUE)
except ValueError:
    print("Erreur : La variable d'environnement RESIZE_WATERMARK_SIZE doit être un nombre.")
    sys.exit()

# Configuration du watermark
WATERMARK_PATH = DATA_PATH / "watermark.png"
ALPHA   = CONSTANTS.WATERMARK_ALPHA
QUALITY = CONSTANTS.RESIZE_QUALITY

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
    print(f"{i+1}/{TOTAL}")

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
        
        # Appliquer le watermark (étiré proportionnellement pour couvrir toute l'image si > 2000 px)
        wm = watermark
        if new_size[0] > 2000 or new_size[1] > 2000:
            scale = max(new_size[0] / watermark.width, new_size[1] / watermark.height)
            wm_size = (int(watermark.width * scale), int(watermark.height * scale))
            wm = watermark.resize(wm_size, Image.Resampling.LANCZOS)
        base_image.paste(wm, (0, 0), wm)
        
        # Convertir en RGB pour la sauvegarde JPEG
        base_image = base_image.convert("RGB")
        filename, _ = os.path.splitext(file)
        output_path = output_folder / f"{filename}.jpg"
        base_image.save(output_path, format='JPEG', subsampling=0, quality=QUALITY)
        
    except Exception as e:
        print(f"Erreur lors du traitement : {e}")
        continue

print("Termine !")
