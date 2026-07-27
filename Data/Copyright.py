__version__ = "3.1.0"

#############################################################
#                          IMPORTS                          #
#############################################################
from PIL import Image
from pathlib import Path
import os
import image_ops

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis Hub (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".GIF", ".TIFF")  # extensions d'image acceptées
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)



def folder(folder) :
    """Crée le sous-dossier ``folder`` dans PATH s'il n'existe pas encore."""
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)



#############################################################
#                           MAIN                            #
#############################################################
copyright_mode   = os.environ.get("COPYRIGHT_MODE", "date")   # "date", "filename", "custom"
copyright_custom = os.environ.get("COPYRIGHT_CUSTOM", "")

for i, file in enumerate(FOLDER):
    print(f"Image {i+1}/{TOTAL}")
    folder("Copyright")

    filename = Path(file).stem
    try:
        source_image = Image.open(PATH / file)
        # Date lue AVANT la conversion sRGB : une conversion ICC réelle
        # (profil non-sRGB embarqué) reconstruit une nouvelle image sans
        # les EXIF d'origine.
        date_label = image_ops.get_date_taken(source_image)
        base_image = image_ops.convert_to_srgb(
            source_image, source_image.info.get("icc_profile"))
    except Exception:
        continue
    else:
        if copyright_mode == "custom" and copyright_custom:
            label = copyright_custom
        elif copyright_mode == "filename":
            label = filename
        else:  # "date" (défaut)
            label = date_label or filename
        base_image = base_image.convert("RGB")
        base_image = image_ops.add_copyright(base_image, label)
        base_image.save(str(PATH / "Copyright" / f"{filename}.jpg"),
                        format="JPEG", subsampling=0, quality=100,
                        icc_profile=image_ops._SRGB_ICC)

print("Terminé !")