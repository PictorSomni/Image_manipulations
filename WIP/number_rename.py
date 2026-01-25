# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os, re

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

#############################################################
#                           MAIN                            #
#############################################################

for index, file in enumerate(FOLDER):
    filename, ext = file.split(".")
    os.rename(file, f"{index + 1:03}.{ext}")
