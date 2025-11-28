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
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(".avif")]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("AVIF en JPG")
    print("#" * 32 + "\n")
    print(f"Image {i+1} sur {TOTAL}")

    file_name, file_extension = os.path.splitext(file)
    try :
        avif_file = Image(filename =file)
    except Exception :
        print(Exception)
    else :
        image = avif_file.convert('jpg')
        image.save(filename=f"{PATH}/{file_name}.jpg")

print("Terminé")