# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from time import sleep
from PIL import Image
from rich import print
from rich.console import Console

#############################################################
#                         VARIABLES                         #
#############################################################
PROJECT = False
WATERMARK = False
MAXSIZE = 640
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
console = Console()
EXTENSION = (".JPG", ".JPEG", ".PNG", "GIF")
FOLDER = [file for file in sorted(os.listdir()) if file.upper().endswith(EXTENSION) and not file == "watermark.png"]
WATERMARK = "C:\\Users\\charl\\Documents\\PYTHON\\Image manipulation\\watermark.png" # Or just "watermark.png" if you copy it to the current folder.
TOTAL = len(FOLDER)

#############################################################
#                         FUNCTIONS                         #
#############################################################
## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")

#############################################################
#                           MAIN                            #
#############################################################
clear()
print(f"[deep_sky_blue1]Conversion en {MAXSIZE}px + filigrane[/deep_sky_blue1]")
print("[violet]~[/violet]" * 32)

with console.status("[bold blue]En cours...") as status:
    for i, file in enumerate(FOLDER):
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
            base_image.convert("RGB").save(f"{PATH}\\{file}", format="JPEG", subsampling=0, quality=QUALITY)


print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
sleep(.5)
sys.exit(1)
