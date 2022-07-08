# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from wand.image import Image
 
#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(".heic")]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("HEIC en JPG")
    print("#" * 32 + "\n")
    print(f"Image {i+1} sur {TOTAL}")

    file_name, file_extension = os.path.splitext(file)
    try :
        heif_file = Image(filename =file)
    except Exception :
        print(Exception)
    else :
        image = heif_file.convert('jpg')
        image.save(filename=f"{PATH}/{file_name}.jpg")

print("Terminé")