__version__ = "2.1.5"

#############################################################
#                          IMPORTS                          #
#############################################################
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import os
from PIL.ExifTags import TAGS
from datetime import datetime

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

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".GIF", ".TIFF")  # extensions d'image acceptées
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)



def folder(folder) :
    """Crée le sous-dossier ``folder`` dans PATH s'il n'existe pas encore."""
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)



def get_date_taken(image):
    """Retourne la date de prise de vue depuis les EXIF, ou None."""
    try:
        exif_data = image._getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) == "DateTimeOriginal":
                    # Format EXIF : "YYYY:MM:DD HH:MM:SS"
                    dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    MOIS = ["janvier","février","mars","avril","mai","juin",
                            "juillet","août","septembre","octobre","novembre","décembre"]
                    return f"{dt.day} {MOIS[dt.month - 1]} {dt.year}"
    except Exception:
        pass
    return None



def add_copyright(image, label) :
        draw = ImageDraw.Draw(image, "RGBA")
        img_w, img_h = image.size

        font_size = round(img_h / 40)  # taille de police proportionnelle à la largeur
        myFont = ImageFont.truetype(str(Path(__file__).resolve().parent.parent / "assets" / "Montserrat-Regular.ttf"), font_size)

        # Mesurer le texte
        bbox = draw.textbbox((0, 0), label, font=myFont)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        padding_x, padding_y = round(img_w / 40), round(img_h / 40)
        margin_bottom = round(img_h / 40)

        # Position centrée en bas
        box_x0 = (img_w - text_w) // 2 - padding_x
        box_y0 = img_h - text_h - padding_y * 2 - margin_bottom
        box_x1 = (img_w + text_w) // 2 + padding_x
        box_y1 = img_h - margin_bottom

        # Encadré blanc translucide
        draw.rounded_rectangle([box_x0, box_y0, box_x1, box_y1], radius=16, fill=(255, 255, 255, 200))

        # Texte centré dans l'encadré
        text_x = (img_w - text_w) // 2
        text_y = box_y0 + padding_y
        draw.text((text_x, text_y), label, font=myFont, fill=(0, 0, 0, 255))

        return image

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
        base_image = Image.open(PATH / file)
    except Exception:
        continue
    else:
        if copyright_mode == "custom" and copyright_custom:
            label = copyright_custom
        elif copyright_mode == "filename":
            label = filename
        else:  # "date" (défaut)
            label = get_date_taken(base_image) or filename
        base_image = base_image.convert("RGB")
        base_image = add_copyright(base_image, label)
        base_image.save(str(PATH / "Copyright" / f"{filename}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")