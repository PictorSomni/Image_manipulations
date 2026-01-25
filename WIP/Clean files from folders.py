import os
from time import sleep

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)


print("Ce script supprimera tous les fichiers des sous-dossiers")
choice = input("Voulez-vous continuer ? Ecrivez 'oui' puis entrée pour confirmer : ")

if choice.lower() == "oui":
    for root, dirs, files in os.walk(PATH):
        for file in files:
            try:
                os.remove(os.path.join(root, file))
                print(f"{file} has been deleted.")
            except FileNotFoundError:
                print(f"{file} does not exist.")
            except PermissionError:
                print(f"Permission denied to delete {file}.")

print("Nettoyage terminé.")
sleep(1)
