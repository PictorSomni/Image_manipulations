# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re

WIDTH_DPI = 0
HEIGHT_DPI = 0
BORDER_DPI = 0

#############################################################
#                         CONTENT                           #
#############################################################
features = re.search(r"(\d+)\s?x\s?(\d+)\s?x\s?(\d+)?.py", sys.argv[0]) # width x height x dpi
WIDTH = int(features.group(1))
HEIGHT = int(features.group(2))
DPI = int(features.group(3))

def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)

#############################################################
#                           MAIN                            #
#############################################################

os.system('cls' if os.name == 'nt' else 'clear')
print(f"{WIDTH} x {HEIGHT} mm")
print("#" * 32)
print(f"En {DPI} DPI -> {WIDTH_DPI} x {HEIGHT_DPI} pixels")
print("#" * 32 + "\n")

input("Appuyez sur une touche pour fermer")