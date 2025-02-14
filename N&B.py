# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import cv2

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

# ## Create a folder to save the new images to
# if not os.path.exists(f"{PATH}\\N&B") :
#     os.makedirs(f"{PATH}\\N&B")

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Normalisation des images")
    print("#" * 30)
    print("Image {} sur {}".format(i+1, TOTAL))
    try :
        base_image = cv2.imread(file, 0)
    except Exception as e :
        print(e)
    else :
        clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(4,4))
        result_image = clahe.apply(base_image)
        filename, ext = file.split(".")
        # cv2.imwrite(f"{PATH}\\N&B\\{filename}_N&B.{ext}",result_image)
        cv2.imwrite(f"{PATH}\\{filename}_N&B.{ext}",result_image)
print("Terminé !")