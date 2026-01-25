# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
import sys
from time import monotonic
from rich import print
from rich.console import Console

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
console = Console()
FOLDER = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.lower() == ".jpeg"]

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
            file_path = PATH / file
            filename = file_path.stem
            new_file = file_path.with_suffix('.jpg')
            file_path.rename(new_file)
        except FileExistsError:
            print(f"[red]Erreur:[/red] Le fichier [yellow]{filename}.jpg[/yellow] existe déjà.")
            pass
    
print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait(.5)
sys.exit(1)