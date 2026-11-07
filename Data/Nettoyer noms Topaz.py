# -*- coding: utf-8 -*-
"""
Remplace le suffixe ajouté par Topaz cloud par « _OK » :
« IMG_0550-cloud-wonder 3.5-1x.jpg » → « IMG_0550_OK.jpg »,
« DSC_0012-wonder-4.jpeg » → « DSC_0012_OK.jpeg »,
« C0042_denoise_iris3.mp4 » → « C0042_OK.mp4 ».

N'écrase jamais un fichier existant (le fichier est alors laissé tel quel).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
"""


import os
import re
from pathlib import Path

# Topaz Photo cloud (« -cloud-… », « -wonder… ») et Topaz Video
# (« _denoise_iris3 », « _proteus », « _prob-4_2x »…).
VIDEO_MODELS = ("iris|proteus|artemis|gaia|theia|dione|chronos|apollo|"
                "nyx|rhea|starlight|aion|prob|ahq|alq|amq|ghq|gcg|thd|"
                "thf|chf|chr|apf")
# Vidéo scindée par l'enregistreur (« C0042_b ») : la lettre de la
# partie est gardée, sinon toutes les parties visent le même nom.
SUFFIX = re.compile(r"-(?i:cloud|wonder)\b.*$|(_[a-z])?_(?:[a-z]{2,}_)*(?:"
                    + VIDEO_MODELS + r")-?\d+(?:_.*)?$")


def clean_name(name):
    """Suffixe Topaz remplacé par « _OK », extension conservée."""
    p = Path(name)
    def _ok(m):
        part = m.group(1) or re.search(r"(_[a-z])?$", m.group(0)).group(1)
        return (part or "") + "_OK"
    return SUFFIX.sub(_ok, p.stem) + p.suffix


assert clean_name("IMG_0550-cloud-wonder 3.5-1x.jpg") == "IMG_0550_OK.jpg"
assert clean_name("DSC_0012-wonder-4.jpeg") == "DSC_0012_OK.jpeg"
assert clean_name("DSC_0012-wonder.jpg") == "DSC_0012_OK.jpg"
assert clean_name("C0042_denoise_iris3.mp4") == "C0042_OK.mp4"
assert clean_name("C0042_prob-4_2x.mov") == "C0042_OK.mov"
assert clean_name("C0042_b_denoise_iris3.mp4") == "C0042_b_OK.mp4"
assert clean_name("C0042_denoise_iris3_c.mp4") == "C0042_c_OK.mp4"
assert clean_name("Mariage_Iris_2024.mp4") == "Mariage_Iris_2024.mp4"
assert clean_name("DSC_0012.jpg") == "DSC_0012.jpg"
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
