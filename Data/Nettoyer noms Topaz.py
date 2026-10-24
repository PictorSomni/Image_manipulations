# -*- coding: utf-8 -*-
"""
Retire le suffixe ajouté par Topaz cloud au nom des fichiers :
« IMG_0550-cloud-wonder 3.5-1x.jpg » → « IMG_0550.jpg ».

N'écrase jamais un fichier existant (le fichier est alors laissé tel quel).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
"""

__version__ = "2.10.113"

import os
import re
from pathlib import Path

SUFFIX = re.compile(r"-cloud-.*$")


def clean_name(name):
    """Nom sans le suffixe Topaz, extension conservée."""
    p = Path(name)
    return SUFFIX.sub("", p.stem) + p.suffix


assert clean_name("IMG_0550-cloud-wonder 3.5-1x.jpg") == "IMG_0550.jpg"
assert clean_name("IMG_0550.jpg") == "IMG_0550.jpg"

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
