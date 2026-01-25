# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import sys
import re
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

EXTENSION = (".JPG", ".JPEG", ".PNG", ".PSD", ".PSB")
FOLDER = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")

## Real timer
def wait(delay=0.5):
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
        filename, ext = os.path.splitext(file)
        
        digits = re.findall(r"\d+", filename)
        
        if digits:
            # Concatène tous les groupes de chiffres
            number = "".join(digits)
            number = number[-4:]  # Limite aux 4 derniers chiffres
            os.rename(file, f"{number}{ext}")
    
print("[bright_green]Terminé ![/bright_green]")

print("[deep_sky_blue1]Belle journée![/deep_sky_blue1]")
wait()
sys.exit(1)