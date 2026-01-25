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
FOLDER = [file for file in os.listdir() if file.lower().endswith(".jpeg")]

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
    for file in FOLDER:
        try:
            filename  = os.path.splitext(file)[0]
            os.rename(file, f"{filename}.jpg")
        except FileExistsError:
            print(f"[red]Erreur:[/red] Le fichier [yellow]{filename}.jpg[/yellow] existe déjà.")
            pass
    
print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait(.5)
sys.exit(1)