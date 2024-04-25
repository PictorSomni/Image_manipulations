#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pdf2image import convert_from_path

#############################################################
#                         REQUIRED                          #
#############################################################
# https://pypi.org/project/pdf2image/
# https://github.com/oschwartz10612/poppler-windows/releases/
POPPLER_PATH = r"C:\poppler\Library\bin"

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
for pdf in FOLDER :
    pages = convert_from_path(pdf, poppler_path=POPPLER_PATH)

    for i in range(len(pages)):
        # Save pages as images in the pdf
        try:
            pages[i].save(f"page_{i+1:03}.jpg", "JPEG")
        except Exception as e:
            print(e)
        continue

print("Terminé")