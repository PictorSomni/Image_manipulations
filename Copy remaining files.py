# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from shutil import copyfile

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)
print(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".nef")
NEF = [file.split('.')[0] for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION)]
DONE = [file.split('.')[0] for file in sorted(os.listdir(f"{PATH}\\OK")) if file.lower().endswith(EXTENSION)]
REST = set(NEF) - set(DONE)
TOTAL = len(REST)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(REST) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Comparaison de fichiers")
    print("#" * 32 + "\n")
    print(f"Image {i+1} sur {TOTAL}")

    copyfile(f"{PATH}\\{file}.NEF", f"{PATH}\\Refaire\\{file}.NEF")

print("C'est bon !")

