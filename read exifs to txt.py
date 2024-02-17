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
        parsed_data = metadata["parameters"]
    except Exception :
        continue
    else:
        with open(f"{PATH}\\prompts.txt", "a") as text:
            text.write("-" * 64 + "\n")
            text.write(file)
            text.write("\n \n")
            text.write(parsed_data)
            text.write("\n" + "-" * 64 + "\n \n")
