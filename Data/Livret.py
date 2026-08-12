# -*- coding: utf-8 -*-
"""
Assemble un lot d'images en un PDF de livret (imposition pour piqûre à
cheval) : les pages sont réparties 2 par feuille, dans l'ordre qui,
imprimé en recto-verso, redonne la lecture 1, 2, 3... N. Contrairement
au mode "livret" du pilote d'imprimante, les images ne sont PAS
redimensionnées : elles sont déjà à la bonne taille d'impression
(marge blanche comprise) et sont simplement collées côte à côte.

La 1re feuille imprimée porte toujours les couvertures — dernière de
couverture à GAUCHE, première de couverture à DROITE (retour user) —
et les feuilles suivantes alternent la position des pages selon leur
rang pour rester correctes une fois recto-verso (algorithme standard
d'imposition "booklet printing", ex. psbook) : pour la feuille
d'indice s (0 = la 1re imprimée), sur n pages au total,
  recto = [page (n - 2s)   | page (2s + 1)]
  verso = [page (2s + 2)   | page (n - 2s - 1)]
Le nombre de pages est complété à un multiple de 4 avec des pages
blanches insérées juste avant la dernière image (jamais après, pour
ne jamais déplacer la dernière de couverture) — leur répartition sur
plusieurs feuilles est une conséquence inévitable de cette imposition.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|``, DANS L'ORDRE DE
                    LECTURE du livret (ordre de sélection dans Hub).
                    Sans elle : tri alphabétique de tout le dossier.
  LIVRET_NAME     — nom du fichier PDF sans extension (optionnel).

Dépendances : Pillow (PIL)
"""

__version__ = "4.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from pathlib import Path
from PIL import Image, ImageFile, ImageOps
import image_ops
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")

# Ordre de sélection dans Hub = ordre de lecture du livret. Sans
# sélection (bouton lancé sur tout le dossier), tri alphabétique.
selected_files_str = os.environ.get("SELECTED_FILES", "")
if selected_files_str:
    IMAGE_FILES = [PATH / name for name in selected_files_str.split("|")
                  if name]
else:
    IMAGE_FILES = [f for f in sorted(PATH.iterdir())
                  if f.is_file() and f.suffix.lower() in EXTENSION
                  and f.name.lower() != "watermark.png"]
TOTAL = len(IMAGE_FILES)

LIVRET_NAME = os.environ.get("LIVRET_NAME", "").strip() or PATH.name


#############################################################
#                          HELPERS                           #
#############################################################
def _load_page(img_file):
    """Charge une image de page, orientée et convertie en RGB blanc."""
    opened = Image.open(img_file)
    opened.load()
    img = image_ops.convert_to_srgb(opened, opened.info.get("icc_profile"))
    img = ImageOps.exif_transpose(img)
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _centered_on_cell(img, cell_w, cell_h):
    """Colle `img` au centre d'une cellule blanche cell_w x cell_h, sans
    redimensionner — seule une tolérance de taille entre images est
    absorbée (marges déjà imprimées, pas d'écrasement/étirement)."""
    if img.size == (cell_w, cell_h):
        return img
    cell = Image.new("RGB", (cell_w, cell_h), "white")
    x = (cell_w - img.width) // 2
    y = (cell_h - img.height) // 2
    cell.paste(img, (x, y))
    return cell


#############################################################
#                           MAIN                            #
#############################################################
print(f"Assemblage d'un livret à partir de {TOTAL} images")
print("~" * 39)

if TOTAL == 0:
    print("Aucune image trouvée !")
    sys.exit(1)

pages = []
for index, img_file in enumerate(IMAGE_FILES, start=1):
    print(f"Page {index}/{TOTAL}: {img_file.name}...")
    try:
        pages.append(_load_page(img_file))
    except Exception as e:
        print(f"Erreur lors du chargement de {img_file.name}: {e}")

if len(pages) == 0:
    print("Aucune image valide trouvée !")
    sys.exit(1)

# Cellule commune = la plus grande largeur/hauteur rencontrée, chaque
# page est centrée dedans (cf. _centered_on_cell) plutôt que redimen-
# sionnée, pour ne jamais casser une taille d'impression déjà correcte.
cell_w = max(p.width for p in pages)
cell_h = max(p.height for p in pages)
pages = [_centered_on_cell(p, cell_w, cell_h) for p in pages]

# Complète à un multiple de 4 (feuillet complet) avec des pages
# blanches insérées juste AVANT la dernière page — jamais après, pour
# que la dernière image fournie reste la dernière de couverture.
missing = (-len(pages)) % 4
if missing:
    print(f"{missing} page(s) blanche(s) ajoutée(s) pour compléter le "
         f"feuillet (dernière de couverture préservée).")
    blank = Image.new("RGB", (cell_w, cell_h), "white")
    pages = pages[:-1] + [blank] * missing + pages[-1:]

n = len(pages)
sheets = n // 4
print(f"{n} pages -> {sheets} feuille(s) recto-verso")

# Imposition piqûre à cheval : la 1re feuille imprimée porte les
# couvertures (dernière de couverture à gauche, première à droite),
# et ainsi de suite vers le centre en alternant selon le rang de la
# feuille — algorithme standard des logiciels de "booklet printing"
# (ex. psbook), garanti de retomber juste car n est un multiple de 4.
output_pages = []
for s in range(sheets):
    front_left, front_right = n - 2 * s, 2 * s + 1
    back_left, back_right = 2 * s + 2, n - 2 * s - 1

    front = Image.new("RGB", (cell_w * 2, cell_h), "white")
    front.paste(pages[front_left - 1], (0, 0))
    front.paste(pages[front_right - 1], (cell_w, 0))
    output_pages.append(front)

    back = Image.new("RGB", (cell_w * 2, cell_h), "white")
    back.paste(pages[back_left - 1], (0, 0))
    back.paste(pages[back_right - 1], (cell_w, 0))
    output_pages.append(back)

# Une seule résolution pour tout le PDF (limitation Pillow, cf.
# Hub.pyw:_images_to_pdf) : CONSTANTS.DPI, celle à laquelle les pages
# sources sont normalement déjà imprimées dans cette appli.
pdf_path = PATH / f"{LIVRET_NAME} - Livret.pdf"
output_pages[0].save(str(pdf_path), "PDF", resolution=float(CONSTANTS.DPI),
                     save_all=True, append_images=output_pages[1:])

print(f"[OK] Livret créé avec succès : {pdf_path.name} "
     f"({sheets} feuille(s) recto-verso)")
