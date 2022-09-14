# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from time import sleep

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)
directories = [directory for directory in os.listdir(PATH) if os.path.isdir(directory)]

#############################################################
#                           MAIN                            #
#############################################################
for directory in directories :
    content = [file for file in os.listdir(directory) if os.path.isdir(file) == False]
    
    for file in content :
        os.rename(f"{PATH}\\{directory}\\{file}", f"{PATH}\\{directory}\\{directory}\\{file}")

sleep(1)
print("Terminé !")