# -*- coding: utf-8 -*-
"""
Transfère et renomme les commandes photo du kiosk 1 (gauche) vers le NAS du studio.

Même logique que ``Kiosk droite.py`` : seules les commandes absentes de
``DESTINATION`` sont transférées, et les fichiers déjà présents ne sont pas
ré-copiés.

Chemins :
  Source      : \\\\studioc-kiosk1\\kiosk-data\\it-HotFolder (Windows)
                /Volumes/kiosk-data/it-HotFolder              (macOS)
  Destination : NAS TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE.

Dépendances : modules standard (sys, re, collections, pathlib, platform, shutil)
"""

__version__ = "1.9.4"

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
    """Crée récursivement le dossier ``folder_path`` s'il n'existe pas encore."""
    Path(folder_path).mkdir(parents=True, exist_ok=True)


#############################################################
#                           MAIN                            #
#############################################################
print("Demarrage de order-it gauche...", flush=True)
print(f"Source: {PATH}", flush=True)
print(f"Destination: {DESTINATION}", flush=True)

## Lists all the already sorted id folders at the destination.
## Only folders that contain at least one sub-directory are considered complete.
try:
    DESTINATION_FOLDERS = sorted([
        f.name for f in DESTINATION.iterdir()
        if f.is_dir() and any(sf.is_dir() for sf in f.iterdir())])
    DESTINATION_FOLDERS = list(dict.fromkeys(DESTINATION_FOLDERS))
except Exception as e:
    print(f"Erreur d'accès à la destination: {e}", flush=True)
    DESTINATION_FOLDERS = []

## Creates 2 lists, the first containing every files of every folders, the second containing the ID to finds them later.
try:
    dir_list = [f.name for f in PATH.iterdir() if f.is_dir()]
except (FileNotFoundError, OSError, Exception) as e:
    print(f"\n⚠️  Impossible d'accéder au dossier source", flush=True)
    print(f"Erreur: {e}", flush=True)
    print("  • Vérifiez que le chemin est correct", flush=True)
    print("  • Vérifiez les permissions\n", flush=True)
    sys.exit(1)

for dir_name in sorted(dir_list):
    directory = PATH / dir_name
    files = [f.name for f in directory.iterdir() if f.is_file() and f.name != "Thumbs.db" and not f.name.startswith("._")]
    
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
total_orders = 0
total_files = 0

for id in RESULT :
    files_copied = 0
    folder(DESTINATION / id)

    for size, files in RESULT[id].items():
        if files :
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
                                    dest_file = DESTINATION / id / size / f"{value}X_{filename}"
                                    if not dest_file.exists():
                                        copyfile(PATH / size / original, dest_file)
                                        files_copied += 1
                                previous_filename = filename

            filenames.clear()

    if files_copied > 0:
        print(f"Commande {id} : {files_copied} fichier(s) copie(s)", flush=True)
        total_orders += 1
        total_files += files_copied

print(f"Termine ! {total_orders} commande(s), {total_files} fichier(s).", flush=True)
sys.exit(0)
