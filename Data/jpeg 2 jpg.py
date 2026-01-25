# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import sys
from time import monotonic


#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
FOLDER = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.lower() == ".jpeg"]
TOTAL = len(FOLDER)

## Real timer
def wait(delay=1):
    now = monotonic()
    while monotonic() <= (now + delay):
        pass
#############################################################
#                           MAIN                            #
#############################################################
    for i, file in enumerate(FOLDER):
        try:
            print("Image {} sur {}".format(i+1, TOTAL))
            file_path = PATH / file
            filename = file_path.stem
            new_file = file_path.with_suffix('.jpg')
            file_path.rename(new_file)
        except FileExistsError:
            print(f"Erreur:Le fichier {filename}.jpg existe déjà.")
            pass
    
print("Terminé !")

wait(.5)
sys.exit(1)