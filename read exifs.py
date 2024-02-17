#############################################################
#                          IMPORTS                          #
#############################################################
import os
from PIL import Image, ImageFile

#############################################################
#                           SIZES                           #
#############################################################
DPI = 300       # DPI

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]

#############################################################
#                           MAIN                            #
#############################################################

for file in FOLDER :
    photo = Image.open(file)

    # Get the metadata
    metadata = photo.info
    try :
        text = metadata["parameters"]
    except Exception :
        continue
    else:
        print("-" * 64)
        print(file)
        print("-" * 64)
        print(text)
        print("#" * 64 + "\n")

input("Press a key to exit")
