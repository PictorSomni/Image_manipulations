
import sys
import os
import fitz

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
DPI = 300
NAME = "PTP"
START = 1

#############################################################
#                           MAIN                            #
#############################################################
for index, pdf in enumerate(FOLDER) :
    filename, file_extension = os.path.splitext(pdf)
    doc = fitz.open(pdf)
    
    if not os.path.exists(PATH + "\\IMAGES") :
        os.makedirs(PATH + f"\\IMAGES")

    for i in range(len(doc)):
        os.system('cls' if os.name == 'nt' else 'clear')
        print("PDF {} sur {}".format(index+1, TOTAL))
        print("#" * 32)
        print(f"Page {i+1}")
        
        for img in doc.getPageImageList(i):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n < 5:       # this is GRAY or RGB
                pix.pillowWrite(f"{PATH}\\IMAGES\\{NAME}_{i+START:03}.png", dpi=(DPI, DPI), format='PNG', subsampling=0, quality=100)
            else:               # CMYK: convert to RGB first
                pix1 = fitz.Pixmap(fitz.csRGB, pix)
                pix1.pillowWrite(f"{PATH}\\IMAGES\\{NAME}_{i+START:03}.png", dpi=(DPI, DPI), format='PNG', subsampling=0, quality=100)
                pix1 = None
            pix = None
print("Terminé")