# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import sys
import re

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".JPG", ".JPEG", ".PNG", ".PSD", ".PSB")
FOLDER = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print(f"Image {i+1} sur {len(FOLDER)}")
    file_path = PATH / file
    filename = file_path.stem
    ext = file_path.suffix
    
    digits = re.findall(r"\d+", filename)
    
    if digits:
        # Concatène tous les groupes de chiffres
        number = "".join(digits)
        number = number[-4:]  # Limite aux 4 derniers chiffres
        file_path.rename(PATH / f"{number}{ext}")
    
sys.exit(1)