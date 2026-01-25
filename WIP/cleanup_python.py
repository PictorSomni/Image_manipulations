import os
from time import sleep

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

EXTENSION = ".py"
print("Ce script supprimera tous les fichiers avec l'extension " + EXTENSION + " dans le répertoire : " + PATH)
choice = input("Voulez-vous continuer ? Tapez 'oui' puis entrée pour confirmer : ")

if choice.lower() == "oui":
    for root, dirs, files in os.walk(PATH):
        for file in files:
            if file.endswith(EXTENSION) : # and file != "cleanup_python.py":
                try:
                    os.remove(os.path.join(root, file))
                    print(f"{file} has been deleted.")
                except FileNotFoundError:
                    print(f"{file} does not exist.")
                except PermissionError:
                    print(f"Permission denied to delete {file}.")

print("Nettoyage terminé.")
sleep(1)
