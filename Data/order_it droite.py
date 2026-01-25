# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import sys
import re
from collections import Counter
from pathlib import Path
import platform
from shutil import copyfile

# Import smbprotocol si disponible pour accès SMB automatique
try:
    import smbclient
    SMB_AVAILABLE = True
except ImportError:
    SMB_AVAILABLE = False
    if platform.system() != "Windows":
        print("[yellow]Note: Installez smbprotocol pour l'accès SMB automatique: pip install smbprotocol[/yellow]")

#############################################################
#                           PATH                            #
#############################################################

def get_smb_path(smb_path_str):
    """
    Convertit un chemin SMB Windows en format compatible selon la plateforme.
    Avec smbprotocol: utilise smb:// (accès direct sans montage)
    Sans smbprotocol sur Windows: utilise Path standard
    Sans smbprotocol sur Linux/macOS: suppose un montage dans /mnt
    """
    if platform.system() == "Windows" and not SMB_AVAILABLE:
        return Path(smb_path_str)
    elif SMB_AVAILABLE:
        # Format SMB pour smbprotocol: smb://server/share/path
        path_str = smb_path_str.replace("\\", "/")
        if path_str.startswith("//"):
            return "smb:" + path_str
        return path_str
    else:
        # Linux/macOS sans smbprotocol: chemin monté
        path_str = smb_path_str.replace("\\", "/")
        if path_str.startswith("//"):
            parts = path_str[2:].split("/", 1)
            if len(parts) == 2:
                server, rest = parts
                return Path("/mnt") / server / rest
            else:
                return Path("/mnt") / parts[0]
        return Path(path_str)

PATH = get_smb_path("\\\\studioc-kiosk2\\kiosk-data\\it-HotFolder")
DESTINATION = get_smb_path("\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE")

# Wrappers pour gérer SMB et chemins locaux de manière transparente
def list_dir(path):
    if isinstance(path, str) and path.startswith("smb://"):
        return [entry.name for entry in smbclient.scandir(path)]
    return [f.name for f in Path(path).iterdir()]

def is_dir(path):
    if isinstance(path, str) and path.startswith("smb://"):
        return smbclient.path.isdir(path)
    return Path(path).is_dir()

def is_file(path):
    if isinstance(path, str) and path.startswith("smb://"):
        return smbclient.path.isfile(path)
    return Path(path).is_file()

def join_path(base, *parts):
    if isinstance(base, str) and base.startswith("smb://"):
        result = base.rstrip("/")
        for part in parts:
            result += "/" + str(part)
        return result
    result = Path(base)
    for part in parts:
        result = result / part
    return result

def copy_file_wrapper(src, dst):
    src_str, dst_str = str(src), str(dst)
    if src_str.startswith("smb://") or dst_str.startswith("smb://"):
        smbclient.copyfile(src_str, dst_str)
    else:
        copyfile(src_str, dst_str)

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
    if isinstance(folder_path, str) and folder_path.startswith("smb://"):
        smbclient.makedirs(folder_path, exist_ok=True)
    else:
        Path(folder_path).mkdir(parents=True, exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
## Lists all the already sorted id folders at the destination.
try:
    DESTINATION_FOLDERS = sorted([name for name in list_dir(DESTINATION) if is_dir(join_path(DESTINATION, name))])
    DESTINATION_FOLDERS = sorted(
        list(dict.fromkeys(DESTINATION_FOLDERS)))  ## -> Delete doubles !
    DESTINATION_FOLDERS = [name for name in DESTINATION_FOLDERS]
except Exception as e:
    print(f"Érreur d'accès à la destination: {e}")
    DESTINATION_FOLDERS = []

## Creates 2 lists, the first containing every files of every folders, the second containing the ID to finds them later.
try:
    dir_list = [d for d in list_dir(PATH) if is_dir(join_path(PATH, d))]
except (FileNotFoundError, OSError, Exception) as e:
    print(f"\n⚠️  Impossible d'accéder au partage SMB source")
    print(f"Erreur: {e}")
    print(f"\nVérifiez que:")
    print("  • Vous êtes connecté au bon réseau")
    print("  • Les partages SMB sont montés ou accessibles")
    print("  • Installez smbprotocol: pip install smbprotocol\n")
    sys.exit(1)

for dir_name in sorted(dir_list):
    directory = join_path(PATH, dir_name)
    files = [f for f in list_dir(directory) if is_file(join_path(directory, f)) and f != "Thumbs.db"]
    
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
                                    print(f"\t==>\t{original}")
                                    print(f"\t\t⤷ {value}X_{filename}\n")

                                    copy_file_wrapper(join_path(PATH, size, original),
                                             join_path(DESTINATION, id, size, f"{value}X_{filename}"))
                                previous_filename = filename
                                
            filenames.clear()
sys.exit(1)