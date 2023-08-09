# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from PIL import Image, ImageFile
from time import monotonic
from rich import print
from rich.console import Console

#############################################################
#                           PATH                            #
#############################################################
## Set path to python file
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
PREFIX = "NO2023_Spy_"

console = Console()
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [Image.open(file.lower()) for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")

## Creates file if it doesn't exists
def file(path):
    if not os.path.exists(f"{path}"):
        open(f"{path}", 'wb').close()


## Real timer
def wait(delay=1):
    now = monotonic()
    while monotonic() <= (now + delay):
        pass


#############################################################
#                           MAIN                            #
#############################################################
clear()

print(f"[deep_sky_blue1]Création d'un PDF à partir de [/deep_sky_blue1][violet]{TOTAL}[/violet] [deep_sky_blue1]images[/deep_sky_blue1]")
print("[violet]~[/violet]" * 39)
try:
    first = FOLDER.pop(0)
except IndexError :
    print("Aucune image trouvée !")
    sys.exit(1)
    
filename = console.input(f"[gold1]Comment doit se nommer le fichier PDF ? --> {PREFIX}??\n[/gold1]")
# file(f"{PATH}\\PDF\\{PREFIX}_{filename}.pdf")

with console.status("[bold blue]En cours...") as status:
    first.save(f"{PATH}\\{PREFIX}{filename}.pdf", "PDF" ,resolution=100.0, save_all=True, append_images=FOLDER)

print("[bright_green]Terminé ![/bright_green]")
wait(.5)
print(f"[bright_green]Vous trouverez votre fichier '{PREFIX}{filename}.pdf' dans le dossier PDF.[/bright_green]")
wait(.5)
print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
sys.exit(1)
