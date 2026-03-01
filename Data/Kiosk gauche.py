# -*- coding: utf-8 -*-

__version__ = "1.6.9"

#############################################################
#                          IMPORTS                          #
#############################################################
import sys
import re
from collections import Counter
from pathlib import Path
import platform
from shutil import copyfile


#############################################################
#                           PATH                            #
#############################################################
if platform.system() == "Windows":
    PATH = "\\\\studioc-kiosk1\\kiosk-data\\it-HotFolder"
    DESTINATION = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK GAUCHE"
else :
    PATH = "/Volumes/kiosk-data/it-HotFolder"
    DESTINATION = "/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE"

PATH = Path(PATH)
DESTINATION = Path(DESTINATION)

#############################################################
#                         CONTENT                           #
#############################################################
FOLDERS = {}
KIOSK_FOLDERS = []
FILES = {}
DESTINATION_FOLDERS = []
RESULT = {}
filenames = []
COPY_FILES = []


## Creates folder if it doesn't exists
def folder(folder_path):
    Path(folder_path).mkdir(parents=True, exist_ok=True)


#############################################################
#                           MAIN                            #
#############################################################
print("Demarrage de order-it gauche...")
print(f"Source: {PATH}")
print(f"Destination: {DESTINATION}")

## Lists all the already sorted id folders at the destination.
try:
    DESTINATION_FOLDERS = sorted([f.name for f in DESTINATION.iterdir() if f.is_dir()])
    DESTINATION_FOLDERS = sorted(
        list(dict.fromkeys(DESTINATION_FOLDERS)))  ## -> Delete doubles !
    DESTINATION_FOLDERS = [name for name in DESTINATION_FOLDERS]
except Exception as e:
    print(f"Erreur d'accès à la destination: {e}")
    DESTINATION_FOLDERS = []

## Creates 2 lists, the first containing every files of every folders, the second containing the ID to finds them later.
try:
    dir_list = [f.name for f in PATH.iterdir() if f.is_dir()]
except (FileNotFoundError, OSError, Exception) as e:
    print(f"Erreur: {e}")
    print(f"\nVérifiez que:")
    print(f"\n⚠️  Impossible d'accéder au dossier source")
    print("  • Le chemin est correct")
    print("  • Vous avez les permissions nécessaires\n")
    sys.exit(1)

for dir_name in sorted(dir_list):
    directory = PATH / dir_name
    files = [f.name for f in directory.iterdir() if f.is_file() and f.name != "Thumbs.db"]
    
    for file in files:
        new_name = re.split(r"_", file)
        id_name = new_name[0]
        order_counter = int(new_name[2])
        folder_name = id_name[10:]

        ## -> Filters the already transfered folders to speed up the process.
        if folder_name not in DESTINATION_FOLDERS:
            KIOSK_FOLDERS.append(id_name)
            FILES[f"{file}"] = f"{id_name}_{new_name[1]}_{order_counter:03}_{new_name[-1]}"
    files.sort()
    FOLDERS[dir_name] = files
    
KIOSK_FOLDERS = sorted(list(dict.fromkeys(KIOSK_FOLDERS)))  ## -> Delete doubles !

## Removes the Kiosk's ID (LIDxxxxxxx) of the order names and filters hidden files.
KIOSK_FOLDERS = [name[10:] for name in KIOSK_FOLDERS if len(name) > 10]

## Puts everything in a single sorted dictionnary.
for id in KIOSK_FOLDERS:
    RESULT[id] = {}
    for size, files in sorted(FOLDERS.items()):
        RESULT[id][size] = {}
        for file in files:
            if id in file:
                RESULT[id][size][file] = FILES[file]

## Browse the sorted dictionnary and copy the right file in the right place.
for id in RESULT :
    print(f"\nCommande : {id}")
    print("~" * 21)
    folder(DESTINATION / id)

    for size, files in RESULT[id].items():
        if files :
            print(f"\n\t{size}")
            print(f"\t" + "-" * 51)
            folder(DESTINATION / id / size)            

            ## Isolate the end of the name of each file and puts them on a new list to count them.
            names = []
            for original, corrected in files.items() :
                filenames.append(re.split("_", corrected)[-1])
                names.append(corrected)

            ## Counts the files.
            counter = Counter(sorted(filenames))
            previous_filename = ""
            for name in sorted(names) :
                for key, value in counter.items() :
                    if key in name :
                        filename = re.split("_", name)[-1]
                        for original, corrected in files.items() :
                            if filename in corrected :
                                if filename == previous_filename :
                                    pass
                                else :
                                    print(f"\t->\t{original}")
                                    print(f"\t\t-->{value}X_{filename}\n")

                                    copyfile(PATH / size / original,
                                            DESTINATION / id / size / f"{value}X_{filename}")
                                previous_filename = filename
                                 
            filenames.clear()

print("Termine !")
sys.exit(0)
