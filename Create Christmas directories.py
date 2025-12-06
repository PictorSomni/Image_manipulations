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
NAME = 9
halves = False
# how_many = re.search(r"Create (\d+) directories.py", sys.argv[0])
# HOW_MANY = int(how_many.group(1))
HOW_MANY = 16
#############################################################
#                           MAIN                            #
#############################################################
for index, directories in enumerate(range(1, HOW_MANY + 1)) :
    if halves == False :
        if not os.path.exists(f"{PATH}\\{NAME:02}00") :
            os.makedirs(f"{PATH}\\{NAME:02}H00")
            os.makedirs(f"{PATH}\\{NAME:02}H00\\RAW")
            os.makedirs(f"{PATH}\\{NAME:02}H00\\JPG")
            os.makedirs(f"{PATH}\\{NAME:02}H00\\RAW\\SELECTION {NAME:02}H00")
            os.makedirs(f"{PATH}\\{NAME:02}H00\\RAW\\AUTRES")
    else :
        if not os.path.exists(f"{PATH}\\{NAME:02}30") :
            os.makedirs(f"{PATH}\\{NAME:02}H30")
            os.makedirs(f"{PATH}\\{NAME:02}H30\\RAW")
            os.makedirs(f"{PATH}\\{NAME:02}H30\\JPG")
            os.makedirs(f"{PATH}\\{NAME:02}H30\\RAW\\SELECTION {NAME:02}H30")
            os.makedirs(f"{PATH}\\{NAME:02}H30\\RAW\\AUTRES")
            NAME += 1
    halves = not halves

sleep(1)
print("Terminé !")
sleep(1)
sys.exit(1)