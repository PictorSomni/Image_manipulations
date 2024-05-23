import os
from shutil import copyfile

PASS = ["Photos Library.photoslibrary"]
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)
FOLDERS = [folder for folder in os.listdir(PATH) if os.path.isdir(folder) and folder not in PASS]
for folder in FOLDERS :
    for file in os.listdir(folder) :
        if ".nef" in file :
            print(file)
            copyfile(f"{PATH}/{folder}/{file}", f"{PATH}/{file}")