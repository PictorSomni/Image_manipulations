# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import sys
from time import sleep
from token import NAME
from rich import print
from rich.console import Console

#############################################################
#                         CONSTANT                          #
#############################################################
NAME = "StudioC" #Optional, if you want to name your file before the iteration.

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
console = Console()

EXTENSION = (".JPG", ".JPEG", ".PNG")
FOLDER = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")

#############################################################
#                           MAIN                            #
#############################################################
clear()

print(f"[deep_sky_blue1]Renommage des fichiers[/deep_sky_blue1]")
print("[violet]~[/violet]" * 23)

with console.status("[bold blue]En cours...") as status:
    for index, file in enumerate(FOLDER) :
        filename, ext = os.path.splitext(file)
        new_index = index + 1
        if NAME:
            new_name = f"{NAME}_{new_index:03}{ext}"
        else:
            new_name = f"{new_index:03}{ext}"

        os.rename(file, new_name)

print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
sleep(.5)
sys.exit(1)