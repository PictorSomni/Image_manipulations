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
console = Console()

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in os.listdir() if file.lower().endswith(EXTENSION) and not file == "watermark.png"]

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
    for index, file in enumerate(FOLDER):
        ext = os.path.splitext(file)[1]
        os.rename(file, f"{index + 1:03}{ext}")
    
print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait(.5)
sys.exit(1)