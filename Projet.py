# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from time import sleep
from PIL import Image

PROJECT = False
WATERMARK = False
MAXSIZE = 1024
QUALITY = 85
ALPHA = 0.5

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".JPG", ".JPEG", ".PNG", "GIF")
FOLDER = [file for file in sorted(os.listdir()) if file.upper().endswith(EXTENSION) and not file == "watermark.png"]
WATERMARK = "C:\\Users\\charl\\Documents\\PYTHON\\Image manipulation\\watermark.png" # Or just "watermark.png" if you copy it to the current folder.
TOTAL = len(FOLDER)


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Conversion en {MAXSIZE}px + renommage + filigrane")
    print("Image {} sur {}".format(i+1, TOTAL))

    try:
        base_image = Image.open(file)
    except Exception:
        continue
    else:
        base_image.thumbnail((MAXSIZE,MAXSIZE), Image.Resampling.LANCZOS)

    try:
        watermark = Image.open(WATERMARK)
        if watermark.mode != "RGBA":
            watermark = watermark.convert("RGBA")

        r, g, b, a = watermark.split()
        a = a.point(lambda i: i * ALPHA)
        watermark = Image.merge("RGBA", (r, g, b, a))
    except Exception:
        watermark = Image.open("watermark.png")
        continue
    else :
        base_image.paste(watermark, watermark)
        base_image.convert("RGB").save(f"{PATH}\\Projet_{file}", format="JPEG", subsampling=0, quality=QUALITY)

print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
