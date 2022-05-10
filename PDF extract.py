# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################

import minecart
import sys
import os
from PIL import Image
import PIL

#############################################################
#                           PATH                            #
#############################################################

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

FOLDER = [file for file in sorted(os.listdir()) if file.endswith(".pdf")]
TOTAL = len(FOLDER)
#############################################################
#                           MAIN                            #
#############################################################

if not os.path.exists(PATH + "\\IMAGES") :
    os.makedirs(PATH + f"\\IMAGES")

for index, pdf in enumerate(FOLDER) :
    filename, file_extension = os.path.splitext(pdf)
    pdffile = open(pdf, 'rb')
    doc = minecart.Document(pdffile)

    #iterating through all pages
    for i, page in enumerate(doc.iter_pages()):
        # os.system('cls' if os.name == 'nt' else 'clear')
        print("PDF {} sur {}".format(index+1, TOTAL))
        print("#" * 32)
        print(f"Page {i+1}")

        im = page.images[0].as_pil()  # requires pillow
        if im.width < im.height : 
            im = im.rotate(-90, expand=True)
        # im.show()
        im.save(f"{PATH}\\IMAGES\\{filename}_{i+1:03}.jpg", format='JPEG', subsampling=0, quality=100)

print("Terminé")