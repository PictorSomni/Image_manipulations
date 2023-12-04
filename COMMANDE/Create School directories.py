# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from time import sleep

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
NAMES = ["A", "B", "A+B", "13x18", "15x20", "20x30", "Calendrier A4", "Magnets 10x15", "Magnets ronds", "Porte-clefs", "Tapis souris", "Tasse", "Plexi 40x60", "Boule a neige", "Voeux A", "Voeux B", "Boule B", "Photos de classes"]
#############################################################
#                           MAIN                            #
#############################################################
for name in NAMES :

    if not os.path.exists(f"{PATH}\\{name}") :
        os.makedirs(f"{PATH}\\{name}")

sleep(1)
print("Terminé !")
sleep(1)
sys.exit(1)