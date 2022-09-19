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
START = 362
console = Console()

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in os.listdir() if file.lower().endswith(EXTENSION) and not "NZ6" in file]

file_name = re.search(r"([\w\s]+).py", sys.argv[0])

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
        filename, ext = os.path.splitext(file)
        os.rename(file, f"{file_name.group(1)}_{index + START:03}{ext}")
    
print("[bright_green]Terminé ![/bright_green]")
wait(.5)
print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
sys.exit(1)