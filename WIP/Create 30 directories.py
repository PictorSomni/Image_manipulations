# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import sleep

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
NAME = "Classe"
how_many = re.search(r"Create\s?(\d+)\s?directories.py", sys.argv[0])
HOW_MANY = int(how_many.group(1))
#############################################################
#                           MAIN                            #
#############################################################
for index, directories in enumerate(range(1, HOW_MANY + 1)) :
    os.makedirs(f"{PATH}\\{NAME} {index:02}")
    os.makedirs(f"{PATH}\\{NAME} {index:02}\\{NAME} {index:02}")

sleep(1)
print("Terminé !")