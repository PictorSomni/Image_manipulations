# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import monotonic
from rich import print
from rich.console import Console

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
REQUIRED = ["p1", "p2"]
IMAGES = []

console = Console()

EXTENSION = (".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in os.listdir() if file.upper().endswith(EXTENSION) and not file == "watermark.png"]

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")

## Real timer
def wait(delay=1):
    now = monotonic()
    while monotonic() <= (now + delay):
        pass
#############################################################
#                           MAIN                            #
#############################################################
clear()

print(f"[deep_sky_blue1]Renommage des fichiers[/deep_sky_blue1]")
print("[violet]~[/violet]" * 23)

with console.status("[bold blue]En cours...") as status:
    for file in FOLDER :
        file_name = re.search(r"([\w\s]+).\w+", file)
        if any(required_name in file_name.group(1).lower() for required_name in REQUIRED) == True :
            IMAGES.append(file)


    for file in IMAGES:
        filename, ext = os.path.splitext(file)

        name = re.search(r"(P\d)?([\w\s]+)?(\d{3})", filename)
        if "BIG" and "2X" in name.group(2).upper() :
            new_name = f"2X{name.group(1)}_B_{name.group(3)}{ext}"
        elif "2X" in name.group(2).upper() :
            new_name = f"2X{name.group(1)}_{name.group(3)}{ext}"
        elif "BIG" in name.group(2).upper() :
            new_name = f"B_{name.group(3)}{ext}"
        else :
            new_name = f"{name.group(3)}{ext}"

        os.rename(file, new_name)

print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait(.5)
sys.exit(1)