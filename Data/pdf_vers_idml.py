"""PDF (mise en page IA, souvent rapiécée) -> IDML ouvrable dans Affinity :
vrais blocs de texte (lignes regroupées en paragraphes, interlignage
réel, crénage 0), images et aplats/filets simples, bords perdus 3 mm.

Le PDF ne contient pas de paragraphes : le regroupement est déduit
(même police/taille/couleur, lignes proches). Texte passé par
nettoyer_texte au passage.

convert(pdf_path) -> chemin du .idml, rangé comme Conversion JPG :
<dossier>/idml/<nom>.idml + <nom>_liens/, PDF d'origine -> <dossier>/pdf/.
"""

__version__ = "2.3.7"

import os
import re
import shutil
import sys
import zipfile
from xml.sax.saxutils import escape

import nettoyer_texte

BLEED = 8.504  # 3 mm en points


def _font(name):
    """« AAAAAA+DejaVuSerif-BoldItalic » -> ("DejaVu Serif", "Bold Italic")."""
    name = name.split("+", 1)[-1]
    if name.lower() in ("helv", "helvetica"):
        return "Helvetica", "Regular"
    fam, _, style = name.partition("-")
    # ponytail: découpe CamelCase naïve, Affinity propose de remplacer
    # une police introuvable de toute façon.
    fam = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", fam).replace("Deja Vu", "DejaVu")
    fam = re.sub(r"\s*(MT|PS)$", "", fam)
    style = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", style) or "Regular"
    style = {"Oblique": "Italic", "Bold Oblique": "Bold Italic",
             "Book": "Regular", "Roman": "Regular"}.get(style, style)
    return fam, style


def _rgb(c):
    if isinstance(c, int):
        return ((c >> 16) & 255, (c >> 8) & 255, c & 255)
    return tuple(round(v * 255) for v in c[:3])


def _lines(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"] != 0:
            continue
        for ln in b["lines"]:
            spans = [s for s in ln["spans"] if s["text"].strip()]
            if not spans:
                continue
            s = max(spans, key=lambda s: len(s["text"]))
            out.append({"bbox": ln["bbox"], "font": s["font"],
                        "size": round(s["size"], 1), "color": s["color"],
                        "origin_y": s["origin"][1],
                        "text": "".join(x["text"] for x in ln["spans"])})
    return out


def group_paragraphs(lines, page_w):
    """Lignes -> paragraphes (liste de dicts avec lines, align, leading)."""
    lines = sorted(lines, key=lambda l: (l["bbox"][1], l["bbox"][0]))
    paras = []
    for ln in lines:
        for p in reversed(paras[-6:]):
            last = p["lines"][-1]
            same = (last["font"] == ln["font"] and last["color"] == ln["color"]
                    and abs(last["size"] - ln["size"]) < 0.3)
            gap = ln["bbox"][1] - last["bbox"][3]
            overlap = (min(last["bbox"][2], ln["bbox"][2])
                       - max(last["bbox"][0], ln["bbox"][0]))
            # Écart négatif toléré : bbox de lignes serrées se chevauchent.
            if (same and -0.6 * ln["size"] < gap < 0.8 * ln["size"]
                    and overlap > 0):
                p["lines"].append(ln)
                break
        else:
            paras.append({"lines": [ln]})
    for p in paras:
        ls = p["lines"]
        x0 = min(l["bbox"][0] for l in ls)
        x1 = max(l["bbox"][2] for l in ls)
        centers = [(l["bbox"][0] + l["bbox"][2]) / 2 for l in ls]
        if len(ls) > 1:
            spread = lambda v: max(v) - min(v)
            lefts = [l["bbox"][0] for l in ls]
            rights = [l["bbox"][2] for l in ls]
            p["align"] = min((spread(lefts), "LeftAlign"),
                             (spread(centers), "CenterAlign"),
                             (spread(rights), "RightAlign"))[1]
            p["leading"] = round((ls[-1]["origin_y"] - ls[0]["origin_y"])
                                 / (len(ls) - 1), 2)
        else:
            p["align"] = ("CenterAlign" if abs(centers[0] - page_w / 2) < 4
                          else "LeftAlign")
            p["leading"] = round(ls[0]["size"] * 1.2, 2)
        p["bbox"] = (x0, min(l["bbox"][1] for l in ls), x1,
                     max(l["bbox"][3] for l in ls))
        # Lignes d'un même paragraphe : jointes par une espace (le PDF a
        # coupé en fin de ligne), césure « -\n » recollée.
        text = ""
        for l in ls:
            t = l["text"].strip()
            text = (text[:-1] + t if text.endswith("-") and text[-2:-1]
                    .isalpha() and t[:1].islower() else
                    (text + " " + t if text else t))
        p["text"] = nettoyer_texte.clean(text)[0]
    return paras


ROLES = ((1.12, "Texte"), (1.6, "Intertitre"),
         (2.5, "Titre"), (99, "Grand titre"))


def size_roles(items):
    """[(taille, nb_caractères)] -> {taille: (rôle, taille_du_rôle)}.
    Texte = taille la plus présente ; les autres classées par rapport à
    elle (retour user : 4 niveaux, pas une taille par bloc)."""
    weight = {}
    for sz, n in items:
        weight[sz] = weight.get(sz, 0) + n
    body = max(weight, key=weight.get)
    role_of = {sz: next(r for lim, r in ROLES if sz / body < lim)
               for sz in weight}
    out = {}
    for role in set(role_of.values()):
        members = sorted(sz for sz in weight if role_of[sz] == role)
        # Taille la plus présente du rôle, arrondie au demi-point.
        rep = max(members, key=weight.get)
        for sz in members:
            out[sz] = (role, round(rep * 2) / 2)
    return out


# ── Écriture IDML ───────────────────────────────────────────────────────
_NS = 'xmlns:idPkg="http://ns.adobe.com/AdobeInDesign/idml/1.0/packaging"'


def _pkg(tag, body):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<idPkg:{tag} {_NS} DOMVersion="8.0">{body}</idPkg:{tag}>')


def _frame(self_id, x0, y0, x1, y1, dy, inner="", attrs=""):
    pts = "".join(
        f'<PathPointType Anchor="{x} {y - dy}" LeftDirection="{x} {y - dy}"'
        f' RightDirection="{x} {y - dy}"/>'
        for x, y in ((x0, y0), (x0, y1), (x1, y1), (x1, y0)))
    return (f'<Properties><PathGeometry><GeometryPathType PathOpen="false">'
            f'<PathPointArray>{pts}</PathPointArray></GeometryPathType>'
            f'</PathGeometry></Properties>{inner}')


def convert(pdf_path):
    import pymupdf
    doc = pymupdf.open(pdf_path)
    page = doc[0]  # ponytail: 1re page seulement, multi-pages si besoin
    w, h = page.rect.width, page.rect.height
    dy = h / 2  # repère de planche IDML : origine au milieu en hauteur
    folder = os.path.dirname(os.path.abspath(pdf_path))
    name = os.path.splitext(os.path.basename(pdf_path))[0]
    base = os.path.join(folder, "idml", name)
    os.makedirs(os.path.dirname(base), exist_ok=True)
    links = base + "_liens"
    colors, items, stories = {}, [], []

    def color(c):
        r, g, b = _rgb(c)
        cid = f"Color/R{r}G{g}B{b}"
        colors[cid] = (r, g, b)
        return cid

    # Aplats et filets (rectangles englobants : coins arrondis perdus).
    for i, d in enumerate(page.get_drawings()):
        x0, y0, x1, y1 = d["rect"]
        if d.get("fill") is not None:
            attrs = f'FillColor="{color(d["fill"])}" StrokeWeight="0"'
        elif d.get("color") is not None:
            attrs = (f'FillColor="Swatch/None" StrokeColor='
                     f'"{color(d["color"])}" StrokeWeight='
                     f'"{d.get("width") or 1}"')
        else:
            continue
        if x1 - x0 < 0.5 or y1 - y0 < 0.5:  # filet : ligne
            items.append(f'<GraphicLine Self="d{i}" {attrs} '
                         f'ItemTransform="1 0 0 1 0 0">'
                         + _frame("", x0, y0, max(x1, x0 + .01),
                                  max(y1, y0 + .01), dy) + '</GraphicLine>')
        else:
            items.append(f'<Rectangle Self="d{i}" {attrs} '
                         f'ItemTransform="1 0 0 1 0 0">'
                         + _frame("", x0, y0, x1, y1, dy) + '</Rectangle>')

    # Images, extraites dans <nom>_liens (IDML = images liées).
    for i, info in enumerate(page.get_image_info(xrefs=True)):
        if not info.get("xref"):
            continue
        os.makedirs(links, exist_ok=True)
        img = doc.extract_image(info["xref"])
        path = os.path.join(links, f"image_{i + 1}.{img['ext']}")
        with open(path, "wb") as f:
            f.write(img["image"])
        x0, y0, x1, y1 = info["bbox"]
        iw, ih = img["width"], img["height"]
        sx, sy = (x1 - x0) / iw, (y1 - y0) / ih
        uri = "file:" + path.replace("\\", "/").replace(" ", "%20")
        if not uri.startswith("file:/"):
            uri = "file:///" + uri[5:]
        items.append(
            f'<Rectangle Self="i{i}" FillColor="Swatch/None" '
            f'StrokeWeight="0" ItemTransform="1 0 0 1 0 0">'
            + _frame("", x0, y0, x1, y1, dy,
                     f'<Image Self="im{i}" ItemTransform="{sx} 0 0 {sy} '
                     f'{x0} {y0 - dy}"><Properties><GraphicBounds Left="0" '
                     f'Top="0" Right="{iw}" Bottom="{ih}"/></Properties>'
                     f'<Link Self="l{i}" LinkResourceURI="{escape(uri)}"/>'
                     f'</Image>') + '</Rectangle>')

    # Texte : un bloc par paragraphe, élargi pour ne pas déborder ; un
    # style de paragraphe par police + taille normalisée (retour user :
    # même interlignage partout, modifiable d'un coup dans Affinity).
    paras = group_paragraphs(_lines(page), w)
    roles = size_roles([(q["lines"][0]["size"], len(q["text"]))
                        for q in paras])
    # Police du style = la plus présente dans le rôle ; les autres blocs
    # du rôle gardent la leur en local.
    fonts = {}
    for q in paras:
        k = (roles[q["lines"][0]["size"]][0],
             _font(q["lines"][0]["font"]))
        fonts[k] = fonts.get(k, 0) + len(q["text"])
    pstyles = {}
    for (role, font), n in sorted(fonts.items(), key=lambda kv: kv[1]):
        size = next(v[1] for v in roles.values() if v[0] == role)
        pstyles[role] = (*font, size, round(size * 1.25 * 2) / 2)
    for i, p in enumerate(paras):
        ln = p["lines"][0]
        pname = roles[ln["size"]][0]
        sfam, sstyle, size, lead = pstyles[pname]
        fam, style = _font(ln["font"])
        local = "" if (fam, style) == (sfam, sstyle) else (
            f'FontStyle="{escape(style)}" ')
        local_font = "" if fam == sfam else (
            f'<Properties><AppliedFont type="string">{escape(fam)}'
            f'</AppliedFont></Properties>')
        x0, y0, x1, y1 = p["bbox"]
        pad = (x1 - x0) * 0.06 + 4
        x0, x1 = {"LeftAlign": (x0, x1 + 2 * pad),
                  "RightAlign": (x0 - 2 * pad, x1),
                  "CenterAlign": (x0 - pad, x1 + pad)}[p["align"]]
        # Le bloc garde de la marge si l'interlignage est plus large.
        y1 += lead * len(p["lines"]) - (y1 - y0) + size
        sid = f"u{i}"
        stories.append((sid, (
            f'<Story Self="{sid}"><ParagraphStyleRange AppliedParagraphStyle='
            f'"ParagraphStyle/{escape(pname)}" Justification='
            f'"{p["align"]}"><CharacterStyleRange AppliedCharacterStyle='
            f'"CharacterStyle/$ID/[No character style]" {local}'
            f'FillColor="{color(ln["color"])}">{local_font}<Content>'
            f'{escape(p["text"])}</Content></CharacterStyleRange>'
            f'</ParagraphStyleRange></Story>')))
        items.append(
            f'<TextFrame Self="t{i}" ParentStory="{sid}" '
            f'ContentType="TextType" ItemTransform="1 0 0 1 0 0">'
            + _frame("", x0, y0 - 1, x1, y1, dy,
                     '<TextFramePreference TextColumnCount="1" '
                     'FirstBaselineOffset="AscentOffset" '
                     'InsetSpacing="0 0 0 0"/>') + '</TextFrame>')

    color_xml = "".join(
        f'<Color Self="{cid}" Model="Process" Space="RGB" '
        f'ColorValue="{r} {g} {b}" Name="R={r} G={g} B={b}"/>'
        for cid, (r, g, b) in colors.items())
    files = {
        "Resources/Graphic.xml": _pkg("Graphic", (
            '<Color Self="Color/Black" Model="Process" Space="CMYK" '
            'ColorValue="0 0 0 100" Name="Black"/>'
            '<Color Self="Color/Paper" Model="Process" Space="CMYK" '
            'ColorValue="0 0 0 0" Name="Paper"/>' + color_xml +
            '<Swatch Self="Swatch/None" Name="None"/>')),
        "Resources/Fonts.xml": _pkg("Fonts", ""),
        "Resources/Styles.xml": _pkg("Styles", (
            '<RootCharacterStyleGroup Self="rcsg"><CharacterStyle '
            'Self="CharacterStyle/$ID/[No character style]" '
            'Name="$ID/[No character style]"/></RootCharacterStyleGroup>'
            '<RootParagraphStyleGroup Self="rpsg"><ParagraphStyle '
            'Self="ParagraphStyle/$ID/[No paragraph style]" '
            'Name="$ID/[No paragraph style]"/><ParagraphStyle '
            'Self="ParagraphStyle/$ID/NormalParagraphStyle" '
            'Name="$ID/NormalParagraphStyle"/>' + "".join(
                f'<ParagraphStyle Self="ParagraphStyle/{escape(n)}" '
                f'Name="{escape(n)}" PointSize="{sz:g}" '
                f'FontStyle="{escape(st)}" Tracking="0" LeftIndent="0" '
                f'FirstLineIndent="0" RightIndent="0" LastLineIndent="0" '
                f'SpaceBefore="0" SpaceAfter="0" BaselineShift="0" '
                f'KerningMethod="$ID/Metrics" HorizontalScale="100" '
                f'VerticalScale="100">'
                f'<Properties><AppliedFont type="string">{escape(fa)}'
                f'</AppliedFont><Leading type="unit">{ld:g}</Leading>'
                f'</Properties></ParagraphStyle>'
                for n, (fa, st, sz, ld) in sorted(pstyles.items()))
            + '</RootParagraphStyleGroup>')),
        "Resources/Preferences.xml": _pkg("Preferences", (
            f'<DocumentPreference PageHeight="{h}" PageWidth="{w}" '
            f'PagesPerDocument="1" FacingPages="false" '
            f'DocumentBleedTopOffset="{BLEED}" '
            f'DocumentBleedBottomOffset="{BLEED}" '
            f'DocumentBleedInsideOrLeftOffset="{BLEED}" '
            f'DocumentBleedOutsideOrRightOffset="{BLEED}" '
            f'DocumentBleedUniformSize="true"/>')),
        "Spreads/Spread_s1.xml": _pkg("Spread", (
            f'<Spread Self="s1" PageCount="1" BindingLocation="0" '
            f'ItemTransform="1 0 0 1 0 0"><Page Self="p1" Name="1" '
            f'GeometricBounds="0 0 {h} {w}" '
            f'ItemTransform="1 0 0 1 0 {-dy}"/>' + "".join(items)
            + '</Spread>')),
    }
    for sid, xml in stories:
        files[f"Stories/Story_{sid}.xml"] = _pkg("Story", xml)
    design = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<?aid style="50" type="document" readerVersion="6.0" '
        'featureSet="257" product="8.0(370)" ?>\n'
        f'<Document {_NS} DOMVersion="8.0" Self="d" '
        f'StoryList="{" ".join(s for s, _ in stories)}">'
        + "".join(f'<idPkg:{k.split("/")[1][:-4].split("_")[0]} '
                  f'src="{k}"/>' for k in files)
        + '</Document>')
    doc.close()
    out = base + ".idml"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"),
                   "application/vnd.adobe.indesign-idml-package",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("designmap.xml", design)
        z.writestr("META-INF/container.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument'
            ':xmlns:container"><rootfiles><rootfile full-path='
            '"designmap.xml" media-type="text/xml"/></rootfiles>'
            '</container>'))
        for k, v in files.items():
            z.writestr(k, v)
    pdf_dir = os.path.join(folder, "pdf")
    if os.path.basename(folder) != "pdf":
        os.makedirs(pdf_dir, exist_ok=True)
        dest = os.path.join(pdf_dir, os.path.basename(pdf_path))
        if not os.path.exists(dest):
            shutil.move(pdf_path, dest)
    return out


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for p in sys.argv[1:]:
            print(convert(p))
        sys.exit()
    assert _font("AAAAAA+DejaVuSerif-BoldItalic") == ("DejaVu Serif",
                                                      "Bold Italic")
    assert _font("helv") == ("Helvetica", "Regular")
    L = lambda y, t, x0=10, x1=100: {"bbox": (x0, y, x1, y + 8), "font": "F",
                                     "size": 8.0, "color": 0,
                                     "origin_y": y + 7, "text": t}
    ps = group_paragraphs([L(10, "Une ligne cou-"), L(19, "pée ici."),
                           L(60, "Autre bloc", 40, 60)], 200)
    assert [p["text"] for p in ps] == ["Une ligne coupée ici.", "Autre bloc"]
    assert ps[0]["leading"] == 9.0
    r = size_roles([(6.8, 90), (7.8, 200), (8.2, 150), (10.1, 40),
                    (11.2, 30), (15.5, 20), (24, 15)])
    assert r[8.2] == ("Texte", 8.0) and r[6.8] == ("Texte", 8.0)
    assert r[11.2] == ("Intertitre", 10.0) and r[24][0] == "Grand titre"
    print("ok")
