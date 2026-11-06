# -*- coding: utf-8 -*-
"""
Retire le suffixe « _OK » : « DSC_0012_OK.jpeg » → « DSC_0012.jpeg ».

N'écrase jamais un fichier existant (le fichier est alors laissé tel quel).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
"""


import os
import re
from pathlib import Path

SUFFIX = re.compile(r"_OK$", re.IGNORECASE)


def clean_name(name):
    """Suffixe « _OK » retiré, extension conservée."""
    p = Path(name)
    return SUFFIX.sub("", p.stem) + p.suffix


assert clean_name("DSC_0012_OK.jpeg") == "DSC_0012.jpeg"
assert clean_name("DSC_0012.jpg") == "DSC_0012.jpg"

if __name__ == "__main__":
    PATH = Path(os.environ.get("FOLDER_PATH",
                               str(Path(__file__).resolve().parent)))
    selected = os.environ.get("SELECTED_FILES", "")
    selected = set(selected.split("|")) if selected else None
    done = 0
    for file in sorted(PATH.iterdir()):
        if not file.is_file() or (selected and file.name not in selected):
            continue
        new = clean_name(file.name)
        if new == file.name:
            continue
        target = file.with_name(new)
        if target.exists():
            print(f"{file.name} : ignoré, {new} existe déjà")
            continue
        file.rename(target)
        print(f"{file.name} → {new}")
        done += 1
    print(f"{done} fichier(s) renommé(s)")
