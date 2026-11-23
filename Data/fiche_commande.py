# -*- coding: utf-8 -*-
"""Moteur des fiches de commande (photos de classe) : modèles JSON,
objets avec masque et dessin de la fiche complète en PIL.

Utilisé par « Fiche commande.pyw ». Les images des objets, les polices
et le filigrane sont dans COMMANDE/Order_data ; les modèles de fiche
dans COMMANDE/Order_data/modeles/*.json et les objets dans objets.json.
"""
import copy
import json
import os
import re

import numpy
from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = None
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "COMMANDE", "Order_data")
MODELS = os.path.join(ASSETS, "modeles")
OBJECTS = os.path.join(ASSETS, "objets.json")
EXTS = (".jpg", ".jpeg", ".png")

# Fiche A4 paysage à 300 dpi.
W, H = 3508, 2480
MARGIN = 70
GAP = 50
PANEL_W = 860            # colonne de droite : photo filigranée + nom
PHOTO_MAX = 1800         # côté max : photo nette à 300 dpi dans le panneau
Y_OFFSET = 4             # remonte la photo dans la zone : visages visibles
RED_TXT = (220, 40, 40)


def _font(name, size):
    return ImageFont.truetype(os.path.join(ASSETS, name), max(8, int(size)))


def title_font(s): return _font("Baloo2-Bold.ttf", 78 * s)
def item_font(s): return _font("Baloo2-Regular.ttf", 46 * s)
def sub_font(s): return _font("Baloo2-Regular.ttf", 30 * s)
def num_font(s): return _font("Montserrat-Regular.ttf", 50 * s)


# ── Objets (photo de l'objet + masque + zone de la photo) ───────────────
DEFAULT_OBJECTS = {
    "mug": {"name": "Tasse", "bg": "MUG.png", "alpha": "MUG_ALPHA.png",
            "box": [100, 420, 1510, 2080], "fit": False, "orient": False},
    "calendrier": {"name": "Calendrier", "bg": "CALENDRIER.png",
                   "alpha": "CALENDRIER_ALPHA.png",
                   "box": [71, 72, 2302, 1513], "fit": True,
                   "orient": False},
    "magnet": {"name": "Magnet rond", "bg": "MAGNET_ROND.png",
               "alpha": "MAGNET_ROND_ALPHA.png",
               "box": [78, 157, 1708, 1634], "fit": False, "orient": False},
    "porte_clef": {"name": "Porte-clef", "bg": "PORTE-CLEF.png",
                   "alpha": "PORTE-CLEF_ALPHA.png",
                   "box": [467, 451, 1310, 1498], "fit": False,
                   "orient": False},
    "plumier": {"name": "Plumier", "bg": "PLUMIER.png",
                "alpha": "PLUMIER_ALPHA.png", "box": [153, 302, 1980, 734],
                "fit": False, "orient": False},
    "cadre": {"name": "Cadre", "bg": "CADRE.png", "alpha": "CADRE_ALPHA.png",
              "box": [575, 390, 1585, 1800], "fit": False, "orient": True},
    "passe": {"name": "Passe-partout", "bg": "PASSE.png",
              "alpha": "PASSE_ALPHA.png", "box": [316, 541, 1138, 1647],
              "fit": False, "orient": True},
    "bois": {"name": "Support bois", "bg": "SUPPORT_BOIS.png",
             "alpha": "SUPPORT_BOIS_ALPHA.png",
             "box": [442, 442, 1348, 1601], "fit": False, "orient": True},
    "neige": {"name": "Boule à neige", "bg": "NEIGE.png",
              "alpha": "NEIGE_ALPHA.png", "box": [176, 235, 1610, 1483],
              "fit": False, "orient": False},
    "voeux01": {"name": "Carte de vœux 1", "bg": "VOEUX01.png",
                "alpha": "VOEUX01_ALPHA.png", "box": [72, 592, 1132, 1669],
                "fit": False, "orient": False},
    "voeux02": {"name": "Carte de vœux 2", "bg": "VOEUX02.png",
                "alpha": "VOEUX02_ALPHA.png", "box": [0, 0, 1205, 1364],
                "fit": False, "orient": False},
    "voeux04": {"name": "Carte de vœux 4", "bg": "VOEUX04.png",
                "alpha": "VOEUX04_ALPHA.png", "box": [130, 118, 1075, 1064],
                "fit": False, "orient": False},
    "voeux05": {"name": "Carte de vœux 5", "bg": "VOEUX05.png",
                "alpha": "VOEUX05_ALPHA.png", "box": [96, 89, 1108, 1239],
                "fit": False, "orient": False},
    "gourde": {"name": "Gourde", "bg": "GOURDE.png",
               "alpha": "GOURDE_ALPHA.png", "box": [613, 910, 1538, 2106],
               "fit": True, "orient": False},
    "portefeuille": {"name": "Portefeuille", "bg": "PORTEFEUILLE.png",
                     "alpha": "PORTEFEUILLE_ALPHA.png",
                     "box": [280, 534, 2023, 1574], "fit": True,
                     "orient": False},
    "boite": {"name": "Boîte à tartines", "bg": "BOITE-TARTINE.png",
              "alpha": "BOITE-TARTINE_ALPHA.png",
              "box": [313, 566, 1842, 1311], "fit": False,
              "orient": False, "persp": 60},
    "voeux03": {"name": "Carte de vœux 3", "bg": "VOEUX03.png",
                "alpha": "VOEUX03_ALPHA.png", "box": [0, 0, 1796, 1205],
                "fit": False, "orient": False},
    "boule_01": {"name": "Boule de Noël gravée A", "bg": "BOULE_01.png",
                 "alpha": "", "box": [0, 0, 487, 487], "static": True},
    "boule_02": {"name": "Boule de Noël gravée B", "bg": "BOULE_02.png",
                 "alpha": "", "box": [0, 0, 487, 487], "static": True},
}


def load_objects():
    try:
        with open(OBJECTS, encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, ValueError):
        saved = {}
    objs = copy.deepcopy(DEFAULT_OBJECTS)
    objs.update(saved)
    return objs


def save_objects(objs):
    with open(OBJECTS, "w", encoding="utf-8") as f:
        json.dump(objs, f, ensure_ascii=False, indent=1)


# ── Modèles de fiche ────────────────────────────────────────────────────
def _it(name, price, sub="", price2="", obj=None):
    return {"name": name, "sub": sub, "price": price, "price2": price2,
            "object": obj, "on": True}


DEFAULT_MODEL = {
    "deadline": "28 novembre",
    "note": "Vos commandes sont au profit de l'école !",
    "footer": "à remettre pour le {date}\navec le montant exact en liquide",
    "sections": [
        {"name": "Packs photos", "col": 0, "items": [
            _it("Pack A", "12", "1X 13x18 + 2X 9x13 + 2X 3.5x4.5"),
            _it("Pack B", "18", "1X 20x30 + 2X 15x20"),
            _it("A + B", "25")]},
        {"name": "Impressions", "col": 0, "items": [
            _it("Photo 13x18", "6", "+ cadre", "8", "cadre"),
            _it("Photo 13x18 sur support bois", "13", "", "", "bois"),
            _it("Photo 15x20", "7", "+ cadre", "9"),
            _it("Photo 20x30", "9", "+ cadre", "10"),
            _it("Photo 30x40", "19", "+ cadre", "13"),
            _it("Photo 40x60", "38", "+ cadre", "20")]},
        {"name": "Objets personnalisés", "col": 1, "items": [
            _it("Calendrier A4", "9", obj="calendrier"),
            _it("Magnet 10x15", "8"),
            _it("Magnets ronds Ø5cm X3", "15", obj="magnet"),
            _it("Porte-clefs plexi X2", "9", obj="porte_clef"),
            _it("Tapis de souris X2", "10"),
            _it("Toile sur châssis 30x40cm", "49"),
            _it("Dibond 30x40cm", "49"),
            _it("Plexi 30x40cm", "49"),
            _it("Toile sur châssis 40x60cm", "79"),
            _it("Dibond 40x60cm", "79"),
            _it("Plexi 40x60cm", "79"),
            _it("Tasse", "15", obj="mug")]},
        {"name": "Mais aussi", "col": 2, "items": [
            _it("Boule à neige", "9", obj="neige"),
            _it("Badge X2", "10"),
            _it("Calendrier dépliants A6 X3", "8"),
            _it("Cartes de vœux modèle A", "6", "X5", obj="voeux05"),
            _it("Cartes de vœux modèle B", "6", "X5", obj="voeux02"),
            _it("Boule de Noël modèle A", "6", "avec prénom gravé"),
            _it("Boule de Noël modèle B", "6", "avec prénom gravé")]},
        {"name": "Photos de classes", "col": 2, "items": [
            _it("P1, P2, P3", "3,5"), _it("P4, P5, P6", "3,5"),
            _it("P6", "3,5"), _it("Maternelles", "3,5")]},
    ],
}


def list_models():
    os.makedirs(MODELS, exist_ok=True)
    names = sorted(f[:-5] for f in os.listdir(MODELS)
                   if f.endswith(".json"))
    if not names:
        save_model("Photos de classe", DEFAULT_MODEL)
        names = ["Photos de classe"]
    return names


def load_model(name):
    with open(os.path.join(MODELS, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def save_model(name, model):
    os.makedirs(MODELS, exist_ok=True)
    with open(os.path.join(MODELS, name + ".json"), "w",
              encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)


def delete_model(name):
    os.remove(os.path.join(MODELS, name + ".json"))


# ── Montage d'une photo dans un objet ───────────────────────────────────
_img_cache = {}


def _asset(name):
    if name not in _img_cache:
        path = name if os.path.isabs(name) else os.path.join(ASSETS, name)
        _img_cache[name] = Image.open(path).convert("RGBA")
    return _img_cache[name]


OBJ_WORK = 1200


def _scaled(name, k):
    key = (name, k)
    if key not in _img_cache:
        img = _asset(name)
        _img_cache[key] = img if k == 1 else img.resize(
            (round(img.width * k), round(img.height * k)),
            Image.Resampling.LANCZOS)
    return _img_cache[key]


def _perspective(img, p):
    """Rétrécit le bord haut de `p` px de chaque côté (p < 0 : l'élargit)
    et tasse la hauteur, pour une face vue en biais."""
    w, h = img.size
    dst = [(p, 0), (w - p, 0), (w, h), (0, h)]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    coeffs = numpy.linalg.solve(numpy.array(rows, float),
                                numpy.array(rhs, float))
    return img.transform((w, h), Image.Transform.PERSPECTIVE,
                         tuple(coeffs), Image.Resampling.BICUBIC)


def combine(photo, bg, box, alpha=None, fit=False, orient=False,
            persp=0):
    """Photo dans la zone `box` de `bg`, découpée par le masque `alpha`
    (même principe qu'Order.pyw : le plus sombre des deux l'emporte)."""
    left, up, right, down = box
    if orient and photo.width > photo.height:
        bg = bg.rotate(90, expand=True)
        alpha = alpha.rotate(90, expand=True) if alpha else None
        left, up, right, down = up, left, down, right
    w, h = right - left, down - up
    scale = (min if fit else max)(w / photo.width, h / photo.height)
    pic = photo.resize((max(1, round(photo.width * scale)),
                        max(1, round(photo.height * scale))),
                       Image.Resampling.LANCZOS)
    zone = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    zone.paste(pic, ((w - pic.width) // 2, (h - pic.height) // Y_OFFSET))
    if persp:
        zone = _perspective(zone, persp)
    layer = Image.new("RGBA", bg.size, (255, 255, 255, 0))
    layer.paste(zone, (left, up), zone)
    if alpha is not None:
        layer = ImageChops.darker(layer, alpha)
    return Image.alpha_composite(bg, layer)


def render_object(photo, obj):
    if obj.get("static"):
        return _asset(obj["bg"]).copy()
    # Vignette finale ≤ 600 px : on monte à ~1200 px au lieu de la
    # taille native des objets (×4 plus rapide, retour audit).
    bg = _asset(obj["bg"])
    k = min(1.0, OBJ_WORK / max(bg.size))
    small = getattr(photo, "small", None)
    if small is None:
        small = photo.copy()
        small.thumbnail((OBJ_WORK, OBJ_WORK), Image.Resampling.LANCZOS)
        photo.small = small
    out = combine(small, _scaled(obj["bg"], k),
                  [round(v * k) for v in obj["box"]],
                  _scaled(obj["alpha"], k) if obj.get("alpha") else None,
                  obj.get("fit", False), obj.get("orient", False),
                  round(int(obj.get("persp", 0) or 0) * k))
    out.thumbnail((600, 600), Image.Resampling.LANCZOS)
    return out


def watermarked(photo):
    """Grande photo de la fiche : filigrane sur toute la surface, pour
    qu'un scan de la fiche ne remplace pas l'achat."""
    pic = photo.convert("RGBA")
    mark = _asset("watermark.png")
    side = max(pic.size)
    mark = mark.resize((side, side), Image.Resampling.LANCZOS)
    pic.alpha_composite(mark, ((pic.width - side) // 2,
                               (pic.height - side) // 2))
    return pic


def open_photo(path):
    img = Image.open(path)
    img.draft("RGB", (PHOTO_MAX, PHOTO_MAX))  # JPEG : décodage réduit
    img = ImageOps.exif_transpose(img)
    img.thumbnail((PHOTO_MAX, PHOTO_MAX), Image.Resampling.LANCZOS)
    return img.convert("RGBA")


# ── Dessin de la fiche ──────────────────────────────────────────────────
def _price(p):
    p = str(p or "").strip()
    return p if not p or "€" in p else p + "€"


def _wrap(draw, text, font, width):
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            test = (cur + " " + word).strip()
            if cur and draw.textlength(test, font=font) > width:
                lines.append(cur)
                cur = word
            else:
                cur = test
        lines.append(cur)
    return lines


def _layout(model, s, draw):
    """Hauteur de chaque section à l'échelle s (pour savoir si ça tient)."""
    col_w = (W - 2 * MARGIN - PANEL_W - 3 * GAP) / 3
    heights = []
    for sec in model["sections"]:
        items = [i for i in sec["items"] if i.get("on", True)]
        strip = _has_strip(sec)
        h = 150 * s + 30 * s
        for it in items:
            h += _item_h(it, s, col_w, draw, strip)
        heights.append(h + 30 * s)
    return col_w, heights


THUMB = 230
STRIP = 175            # largeur de la bande d'images d'une rubrique


def _has_strip(sec):
    """Rubrique avec au moins une image : bande d'images à gauche."""
    return any(i.get("object") and i.get("on", True) for i in sec["items"])


def _text_w(it, s, col_w, strip=False):
    """Largeur du libellé : colonne moins bande d'images, prix et case."""
    thumb = (STRIP + 15) * s if strip else 0
    return col_w - 60 * s - thumb - 78 * s - 25 * s - 130 * s


def _item_h(it, s, col_w, draw, strip=False):
    # Les images ne fixent plus la hauteur des lignes : elles sont
    # réparties dans la bande de gauche (comme l'ancien Order.pyw).
    thumb = 0
    text_w = _text_w(it, s, col_w, strip)
    lines = len(_wrap(draw, it["name"], item_font(s), text_w))
    th = lines * 52 * s + (36 * s if it.get("sub") else 0)
    box = 150 * s if it.get("price2") else 80 * s
    return max(th, thumb, box) + 26 * s


def render_sheet(model, objects, photo=None, label="", renders=None):
    """Fiche complète. `renders` : {id objet: image montée} (cache)."""
    sheet = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(sheet)
    avail = H - 2 * MARGIN - 110
    s = 1.0
    while True:
        col_w, heights = _layout(model, s, draw)
        cols = [0, 0, 0]
        for sec, h in zip(model["sections"], heights):
            cols[min(2, max(0, int(sec.get("col", 0))))] += h + GAP
        if max(cols) - GAP <= avail or s < 0.4:
            break
        s -= 0.04
    ys = [MARGIN] * 3
    renders = renders if renders is not None else {}
    # Colonnes de même hauteur : l'espace libre de chaque colonne est
    # réparti entre ses rubriques, puis entre leurs articles.
    col_of = [min(2, max(0, int(sec.get("col", 0))))
              for sec in model["sections"]]
    n_secs = [col_of.count(c) for c in range(3)]
    bottom = avail  # colonnes jusqu'au texte rouge (retour user)
    for sec, h, c in zip(model["sections"], heights, col_of):
        extra = max(0, bottom - (cols[c] - GAP)) / n_secs[c]
        n_on = sum(1 for it in sec["items"] if it.get("on", True))
        h += extra
        x, y = MARGIN + c * (col_w + GAP), ys[c]
        ys[c] += h + GAP
        draw.rectangle([x, y, x + col_w, y + h], outline="black",
                       width=max(3, round(5 * s)))
        tf = title_font(s)
        draw.text((x + col_w / 2, y + 95 * s), sec["name"], font=tf,
                  fill="black", anchor="mm")
        cy = y + 180 * s
        strip = _has_strip(sec)
        top = cy
        for it in sec["items"]:
            if not it.get("on", True):
                continue
            ih = _item_h(it, s, col_w, draw, strip) + extra / max(1, n_on)
            _draw_item(sheet, draw, it, objects, photo, renders,
                       x, cy, col_w, ih, s, strip)
            cy += ih
        if strip:
            _draw_strip(sheet, sec, objects, photo, renders,
                        x + 30 * s, top, cy, s)
    # Note en bas à gauche.
    draw.text((MARGIN, H - MARGIN), model.get("note", ""),
              font=_font("Baloo2-Regular.ttf", 56), fill=RED_TXT,
              anchor="ls")
    _draw_panel(sheet, draw, model, photo, label, MARGIN + bottom)
    return sheet


def _draw_strip(sheet, sec, objects, photo, renders, x, top, bottom, s):
    """Images de la rubrique réparties sur toute la hauteur de la bande,
    dans l'ordre des articles."""
    keys = [i["object"] for i in sec["items"] if i.get("on", True)
            and i.get("object") in objects]
    if not keys:
        return
    slot = (bottom - top) / len(keys)
    size = round(min(slot * 0.9, STRIP * s))
    for n, key in enumerate(keys):
        if photo is not None:
            if key not in renders:
                renders[key] = render_object(photo, objects[key])
            th = renders[key].copy()
        else:
            th = _asset(objects[key]["bg"]).copy()
        th.thumbnail((size, size), Image.Resampling.LANCZOS)
        cy = top + slot * (n + 0.5)
        sheet.paste(th, (round(x + (STRIP * s - th.width) / 2),
                         round(cy - th.height / 2)), th)


def _draw_item(sheet, draw, it, objects, photo, renders, x, y, col_w, ih,
               s, strip=False):
    pad = 30 * s
    tx = x + pad + ((STRIP + 15) * s if strip else 0)
    obj = None
    if obj:
        size = round(THUMB * s)
        if photo is not None:
            key = it["object"]
            if key not in renders:
                renders[key] = render_object(photo, obj)
            th = renders[key].copy()
        else:
            th = _asset(obj["bg"]).copy()
        th.thumbnail((size, size), Image.Resampling.LANCZOS)
        sheet.paste(th, (round(tx + (size - th.width) / 2),
                         round(y + (ih - th.height) / 2)), th)
        tx += size + 20 * s
    box = round(78 * s)
    bx = x + col_w - pad - box
    px = bx - 25 * s
    text_w = _text_w(it, s, col_w, strip)
    lines = _wrap(draw, it["name"], item_font(s), text_w)
    sub = it.get("sub", "")
    th = len(lines) * 52 * s + (36 * s if sub else 0)
    ty = y + (ih - th) / 2
    for ln in lines:
        draw.text((tx, ty), ln, font=item_font(s), fill="black")
        ty += 52 * s
    if sub:
        draw.text((tx, ty + 2 * s), sub if sub.startswith("(")
                  else f"({sub})", font=sub_font(s), fill="black")
    lw = max(2, round(4 * s))
    if it.get("price2"):
        top = y + (ih - 2 * box) / 2
        draw.rectangle([bx, top, bx + box, top + 2 * box], outline="black",
                       width=lw)
        draw.line([bx, top + box, bx + box, top + box], fill="grey",
                  width=max(1, lw // 2))
        draw.text((px, top + box / 2), _price(it["price"]),
                  font=item_font(s), fill="black", anchor="rm")
        draw.text((px, top + 1.5 * box), f"(+{_price(it['price2'])})",
                  font=item_font(s), fill="black", anchor="rm")
    else:
        top = y + (ih - box) / 2
        draw.rectangle([bx, top, bx + box, top + box], outline="black",
                       width=lw)
        draw.text((px, top + box / 2), _price(it["price"]),
                  font=item_font(s), fill="black", anchor="rm")


def _draw_panel(sheet, draw, model, photo, label, bottom):
    x0 = W - MARGIN - PANEL_W
    y = MARGIN
    lines = model.get("footer", "").split("\n")
    # Cadre réduit à l'essentiel : la photo prend tout le reste.
    box_h = 30 + 56 + 150 + 56 + 120 + len(lines) * 56 + 30
    photo_h = bottom - y - box_h - 40
    if photo is not None:
        pic = watermarked(photo)
        k = min(PANEL_W / pic.width, photo_h / pic.height)
        pic = pic.resize((round(pic.width * k), round(pic.height * k)),
                         Image.Resampling.LANCZOS)
        sheet.paste(pic, (round(x0 + (PANEL_W - pic.width) / 2),
                          y), pic)
    else:
        draw.rectangle([x0, y, x0 + PANEL_W, y + photo_h],
                       fill=(225, 225, 225))
    y += photo_h
    if label:  # tout à droite, sur la ligne de la note
        draw.text((W - MARGIN, H - MARGIN), label, font=num_font(1.6),
                  fill="black", anchor="rs")
    y += 40
    draw.rectangle([x0, y, x0 + PANEL_W, y + box_h], outline="black",
                   width=5)
    f = item_font(1)
    draw.text((x0 + 30, y + 30), "Nom et Prénom :", font=f, fill="black")
    draw.text((x0 + 30, y + 30 + 56 + 150), "Montant total :", font=f,
              fill="black")
    date = model.get("deadline", "")
    ly = y + box_h - 30 - len(lines) * 56
    for ln in lines:
        # La date en rouge, le reste en noir.
        lx = x0 + 30
        for part in re.split(r"(\{date\})", ln):
            txt, col = (date, RED_TXT) if part == "{date}" else (part,
                                                                "black")
            draw.text((lx, ly), txt, font=f, fill=col)
            lx += draw.textlength(txt, font=f)
        ly += 56


def photos_in(folder):
    return sorted(f for f in os.listdir(folder)
                  if f.lower().endswith(EXTS) and not f.startswith("."))


def make_sheet(model, objects, path):
    photo = open_photo(path)
    label = os.path.splitext(os.path.basename(path))[0]
    return render_sheet(model, objects, photo, label)
