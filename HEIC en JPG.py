# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from PIL import Image
import pyheif

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True
EXTENSION = (".heic", ".HEIC")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION)]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################

for i, file in enumerate(FOLDER) :
    filename, file_extension = os.path.splitext(file)
    try :
        heif_file = pyheif.read(file)
    except Exception :
        print(Exception)
    else :
        if not os.path.exists(PATH + "/JPG") :
            os.makedirs(PATH + "/JPG")

        image = Image.frombytes(
            heif_file.mode, 
            heif_file.size, 
            heif_file.data,
            "raw",
            heif_file.mode,
            heif_file.stride,
            )
        image = image.convert("RGB")
        image.save(f"{PATH}/JPG/{filename}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)