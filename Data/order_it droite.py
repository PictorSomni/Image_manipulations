# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from collections import Counter

from time import sleep
from shutil import copyfile
from rich import print
from rich.console import Console

#############################################################
#                           PATH                            #
#############################################################
PATH = "\\\\studioc-kiosk2\\kiosk-data\\it-HotFolder"
DESTINATION = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE"

#############################################################
#                         CONTENT                           #
#############################################################
console = Console()

FOLDERS = {}
KIOSK_FOLDERS = []
FILES = {}
DESTINATION_FOLDERS = []
RESULT = {}
filenames = []
COPY_FILES = []

## Clears the terminal
def clear():
    os.system("cls" if os.name == "nt" else "clear")


## Creates folder if it doesn't exists
def folder(folder):
    if not os.path.exists(folder):
        os.makedirs(folder)


## Print on steroïds
def LOG(log, color="grey75") :
    print(f"[{color}]{log}[/{color}]")


## Print on steroïds
def DEBUG(log, color="bright_red") :
    print(f"[{color}]{log}[/{color}]")


#############################################################
#                           MAIN                            #
#############################################################
clear()

## Lists all the already sorted id folders at the destination.
DESTINATION_FOLDERS = sorted([file for file in os.listdir(DESTINATION)])
DESTINATION_FOLDERS = sorted(
    list(dict.fromkeys(DESTINATION_FOLDERS)))  ## -> Delete doubles !
DESTINATION_FOLDERS = [name for name in DESTINATION_FOLDERS]

## Creates 2 lists, the first containing every files of every folders, the second containing the ID to finds them later.
for directory in sorted(os.listdir(PATH)):
    files = [file for file in os.listdir(os.path.join(PATH, directory)) if not file == "Thumbs.db"]
    
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
    FOLDERS[directory] = files
    
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
    LOG(f"\nCommande : {id}", "violet")
    LOG("~" * 21, "violet")
    folder(f"{DESTINATION}\\{id}")

    for size, files in RESULT[id].items():
        if files :
            LOG(f"\n\t{size}", "deep_sky_blue1")
            LOG(f"\t" + "-" * 51,  "deep_sky_blue1")
            folder(f"{DESTINATION}\\{id}\\{size}")            

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
                                    LOG(f"\t==>\t{original}", "gold1")
                                    LOG(f"\t\t⤷ {value}X_{filename}\n", "bright_green")

                                    copyfile(f"{PATH}\\{size}\\{original}",
                                             f"{DESTINATION}\\{id}\\{size}\\{value}X_{filename}")
                                previous_filename = filename
                                
            filenames.clear()

print("[deep_sky_blue1]C'est bon ![/deep_sky_blue1]")
sleep(1)
sys.exit(1)