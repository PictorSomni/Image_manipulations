# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
import cv2

#############################################################
#                           PATH                            #
#############################################################
# CONVERT_FORMAT = re.search(r"([\w\s]+).py", sys.argv[0])
# CONVERT_FORMAT.group(1)

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################

os.system('cls' if os.name == 'nt' else 'clear')
print("Normalisation des images")
print("#" * 30)

for i, file in enumerate(FOLDER) :
    print("Image {} sur {}".format(i+1, TOTAL))
    try :
        base_image = cv2.imread(file, 0)
    except Exception :
        pass
    else :
        clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(4,4))
        result_image = clahe.apply(base_image)

        cv2.imwrite('N&B_{}'.format(file),result_image)
print("Terminé !")