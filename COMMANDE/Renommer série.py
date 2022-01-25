# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from genericpath import isdir
from lib2to3.pygram import pattern_grammar
import os
import sys
import re
from time import monotonic
from unittest.mock import patch
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

EXTENSION = (".JPG", ".JPEG", ".PNG", ".PSD", ".PSB")
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
    # for folder in os.listdir() :
    #     if os.path.isdir(folder) :
            # for file in os.listdir(folder):
    for file in FOLDER :
        filename, ext = os.path.splitext(file)
        times = re.search(r"\d{1}x", filename.lower())
        name  = re.search(r"\d{3}", filename)

        if name :
            if times :
                # os.rename(f"{PATH}\\{folder}\\{file}", f"{PATH}\\{folder}\\{times.group(0).upper()}_{name.group(0)}{ext}")
                os.rename(file, f"{times.group(0).upper()}_{name.group(0)}{ext}")
            else :
                # os.rename(f"{PATH}\\{folder}\\{file}", f"{PATH}\\{folder}\\{name.group(0)}{ext}")
                os.rename(file, f"{name.group(0)}{ext}")
    
print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait(.5)
sys.exit(1)