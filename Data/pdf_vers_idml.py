"""PDF (mise en page IA, souvent rapiécée) -> IDML ouvrable dans Affinity :
vrais blocs de texte (lignes regroupées en paragraphes, interlignage
réel, crénage 0), images et aplats/filets simples, bords perdus 3 mm.

Le PDF ne contient pas de paragraphes : le regroupement est déduit
(même police/taille/couleur, lignes proches). Texte passé par
nettoyer_texte au passage.

convert(path) -> chemin du .idml, rangé comme Conversion JPG :
<dossier>/idml/<nom>.idml + <nom>_liens/, original -> <dossier>/pdf/
(ou docx/, doc/). Word : cf. convert_docx.
"""

__version__ = "2.8.5"

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


def _uri(path):
    uri = "file:" + path.replace("\\", "/").replace(" ", "%20")
    return uri if uri.startswith("file:/") else "file:///" + uri[5:]


class _Idml:
    """Accumule couleurs, blocs et textes, puis écrit le .idml."""

    def __init__(self, w, h, base):
        self.w, self.h, self.dy, self.base = w, h, h / 2, base
        self.links = base + "_liens"
        self.colors, self.items, self.stories = {}, [], []
        self.pstyles, self.roles = {}, {}

    def color(self, c):
        r, g, b = _rgb(c)
        cid = f"Color/R{r}G{g}B{b}"
        self.colors[cid] = (r, g, b)
        return cid

    def shape(self, bbox, fill=None, stroke=None, width=1):
        x0, y0, x1, y1 = bbox
        if fill is not None:
            attrs = f'FillColor="{self.color(fill)}" StrokeWeight="0"'
        elif stroke is not None:
            attrs = (f'FillColor="Swatch/None" StrokeColor='
                     f'"{self.color(stroke)}" StrokeWeight="{width or 1}"')
        else:
            return
        n = len(self.items)
        tag = ("GraphicLine" if x1 - x0 < 0.5 or y1 - y0 < 0.5
               else "Rectangle")
        self.items.append(
            f'<{tag} Self="d{n}" {attrs} ItemTransform="1 0 0 1 0 0">'
            + _frame("", x0, y0, max(x1, x0 + .01), max(y1, y0 + .01),
                     self.dy) + f'</{tag}>')

    def image(self, data, ext, bbox, iw, ih, wrap=False):
        """Image enregistrée dans <nom>_liens puis placée (liée)."""
        os.makedirs(self.links, exist_ok=True)
        n = len(os.listdir(self.links)) + 1
        path = os.path.join(self.links, f"image_{n}.{ext}")
        with open(path, "wb") as f:
            f.write(data)
        x0, y0, x1, y1 = bbox
        sx, sy = (x1 - x0) / iw, (y1 - y0) / ih
        i = len(self.items)
        self.items.append(
            f'<Rectangle Self="i{i}" FillColor="Swatch/None" '
            f'StrokeWeight="0" ItemTransform="1 0 0 1 0 0">'
            + _frame("", x0, y0, x1, y1, self.dy,
                     # Habillage : le texte contourne l'image comme dans
                     # Word (retour user).
                     ('<TextWrapPreference TextWrapMode='
                      '"BoundingBoxTextWrap"><Properties><TextWrapOffset '
                      'Top="6" Left="6" Bottom="6" Right="6"/>'
                      '</Properties></TextWrapPreference>' if wrap else "")
                     + f'<Image Self="im{i}" ItemTransform="{sx} 0 0 {sy} '
                     f'{x0} {y0 - self.dy}"><Properties><GraphicBounds '
                     f'Left="0" Top="0" Right="{iw}" Bottom="{ih}"/>'
                     f'</Properties><Link Self="l{i}" LinkResourceURI='
                     f'"{escape(_uri(path))}"/></Image>') + '</Rectangle>')

    def styles(self, paras):
        """paras : dicts size/font(fam, style)/text -> 4 styles par rôle
        (retour user : mêmes réglages partout, remis à 0)."""
        self.roles = size_roles([(q["size"], len(q["text"]))
                                 for q in paras])
        fonts = {}
        for q in paras:
            k = (self.roles[q["size"]][0], q["font"])
            fonts[k] = fonts.get(k, 0) + len(q["text"])
        for (role, font), _n in sorted(fonts.items(), key=lambda kv: kv[1]):
            size = next(v[1] for v in self.roles.values() if v[0] == role)
            self.pstyles[role] = (*font, size, round(size * 1.25 * 2) / 2)

    def _range(self, q):
        role = self.roles[q["size"]][0]
        sfam, sstyle = self.pstyles[role][:2]
        fam, style = q["font"]
        local = "" if (fam, style) == (sfam, sstyle) else (
            f'FontStyle="{escape(style)}" ')
        local_font = "" if fam == sfam else (
            f'<Properties><AppliedFont type="string">{escape(fam)}'
            f'</AppliedFont></Properties>')
        return (f'<ParagraphStyleRange AppliedParagraphStyle='
                f'"ParagraphStyle/{escape(role)}" Justification='
                f'"{q["align"]}"><CharacterStyleRange AppliedCharacterStyle='
                f'"CharacterStyle/$ID/[No character style]" {local}'
                f'FillColor="{self.color(q["color"])}">{local_font}'
                f'<Content>{escape(q["text"])}</Content>')

    def text(self, bbox, paras):
        """Un bloc de texte contenant un ou plusieurs paragraphes."""
        sid = f"u{len(self.stories)}"
        end = "</CharacterStyleRange></ParagraphStyleRange>"
        body = ("<Br/>" + end).join(self._range(q) for q in paras) + end
        self.stories.append((sid, f'<Story Self="{sid}">{body}</Story>'))
        x0, y0, x1, y1 = bbox
        self.items.append(
            f'<TextFrame Self="t{sid}" ParentStory="{sid}" '
            f'ContentType="TextType" ItemTransform="1 0 0 1 0 0">'
            + _frame("", x0, y0, x1, y1, self.dy,
                     '<TextFramePreference TextColumnCount="1" '
                     'FirstBaselineOffset="AscentOffset" '
                     'InsetSpacing="0 0 0 0"/>') + '</TextFrame>')

    def save(self):
        w, h = self.w, self.h
        color_xml = "".join(
            f'<Color Self="{cid}" Model="Process" Space="RGB" '
            f'ColorValue="{r} {g} {b}" Name="R={r} G={g} B={b}"/>'
            for cid, (r, g, b) in self.colors.items())
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
                'Name="$ID/[No character style]"/>'
                '</RootCharacterStyleGroup>'
                '<RootParagraphStyleGroup Self="rpsg"><ParagraphStyle '
                'Self="ParagraphStyle/$ID/[No paragraph style]" '
                'Name="$ID/[No paragraph style]"/><ParagraphStyle '
                'Self="ParagraphStyle/$ID/NormalParagraphStyle" '
                'Name="$ID/NormalParagraphStyle"/>' + "".join(
                    f'<ParagraphStyle Self="ParagraphStyle/{escape(n)}" '
                    f'Name="{escape(n)}" PointSize="{sz:g}" '
                    f'FontStyle="{escape(st)}" Tracking="0" LeftIndent="0" '
                    f'FirstLineIndent="0" RightIndent="0" '
                    f'LastLineIndent="0" SpaceBefore="0" SpaceAfter="0" '
                    f'BaselineShift="0" KerningMethod="$ID/Metrics" '
                    f'HorizontalScale="100" VerticalScale="100">'
                    f'<Properties><AppliedFont type="string">{escape(fa)}'
                    f'</AppliedFont><Leading type="unit">{ld:g}</Leading>'
                    f'</Properties></ParagraphStyle>'
                    for n, (fa, st, sz, ld) in sorted(self.pstyles.items()))
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
                f'ItemTransform="1 0 0 1 0 {-self.dy}"/>'
                + "".join(self.items) + '</Spread>')),
        }
        for sid, xml in self.stories:
            files[f"Stories/Story_{sid}.xml"] = _pkg("Story", xml)
        design = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<?aid style="50" type="document" readerVersion="6.0" '
            'featureSet="257" product="8.0(370)" ?>\n'
            f'<Document {_NS} DOMVersion="8.0" Self="d" '
            f'StoryList="{" ".join(s for s, _ in self.stories)}">'
            + "".join(f'<idPkg:{k.split("/")[1][:-4].split("_")[0]} '
                      f'src="{k}"/>' for k in files)
            + '</Document>')
        out = self.base + ".idml"
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(zipfile.ZipInfo("mimetype"),
                       "application/vnd.adobe.indesign-idml-package",
                       compress_type=zipfile.ZIP_STORED)
            z.writestr("designmap.xml", design)
            z.writestr("META-INF/container.xml", (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<container version="1.0" xmlns="urn:oasis:names:tc:'
                'opendocument:xmlns:container"><rootfiles><rootfile '
                'full-path="designmap.xml" media-type="text/xml"/>'
                '</rootfiles></container>'))
            for k, v in files.items():
                z.writestr(k, v)
        return out


def _prepare(src, sub):
    """-> (base de sortie dans idml/, fonction qui range src dans sub/)."""
    folder = os.path.dirname(os.path.abspath(src))
    name = os.path.splitext(os.path.basename(src))[0]
    # Déjà rangé (dossier pdf/) : idml/ à côté de pdf/, pas dedans.
    root = os.path.dirname(folder) if os.path.basename(folder) == sub \
        else folder
    os.makedirs(os.path.join(root, "idml"), exist_ok=True)

    def tidy():
        if os.path.basename(folder) == sub:
            return
        dest = os.path.join(folder, sub, os.path.basename(src))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not os.path.exists(dest):
            shutil.move(src, dest)
    return os.path.join(root, "idml", name), tidy


def convert(path):
    """PDF ou Word -> .idml (cf. en-tête), selon l'extension."""
    if path.lower().endswith((".docx", ".doc")):
        return convert_docx(path)
    import pymupdf
    base, tidy = _prepare(path, "pdf")
    doc = pymupdf.open(path)
    page = doc[0]  # ponytail: 1re page seulement, multi-pages si besoin
    w, h = page.rect.width, page.rect.height
    out = _Idml(w, h, base)
    # Aplats et filets (rectangles englobants : coins arrondis perdus).
    for d in page.get_drawings():
        out.shape(d["rect"], d.get("fill"), d.get("color"), d.get("width"))
    for info in page.get_image_info(xrefs=True):
        if info.get("xref"):
            img = doc.extract_image(info["xref"])
            out.image(img["image"], img["ext"], info["bbox"],
                      img["width"], img["height"])
    # Texte : un bloc par paragraphe, élargi pour ne pas déborder.
    paras = group_paragraphs(_lines(page), w)
    for q in paras:
        ln = q["lines"][0]
        q.update(size=ln["size"], font=_font(ln["font"]), color=ln["color"])
    out.styles(paras)
    for q in paras:
        size, lead = out.pstyles[out.roles[q["size"]][0]][2:]
        x0, y0, x1, y1 = q["bbox"]
        pad = (x1 - x0) * 0.06 + 4
        x0, x1 = {"LeftAlign": (x0, x1 + 2 * pad),
                  "RightAlign": (x0 - 2 * pad, x1),
                  "CenterAlign": (x0 - pad, x1 + pad)}[q["align"]]
        # Le bloc garde de la marge si l'interlignage est plus large.
        out.text((x0, y0 - 1, x1, y0 + lead * len(q["lines"]) + size), [q])
    doc.close()
    result = out.save()
    tidy()
    return result


def _emf_bitmap(data):
    """Bitmap embarquée dans un EMF (Word enveloppe souvent une simple
    photo collée dans un EMF) -> PNG, sinon None.
    ponytail: seul EMR_STRETCHDIBITS (81), le cas courant ; les EMF
    vraiment vectoriels passent par LibreOffice (_emf_convert)."""
    import io
    import struct
    from PIL import Image
    best, pos = None, 0
    while pos + 8 <= len(data):
        rtype, size = struct.unpack_from("<II", data, pos)
        if size < 8:
            break
        if rtype == 81 and size >= 80:
            off_bmi, cb_bmi, off_bits, cb_bits = struct.unpack_from(
                "<IIII", data, pos + 48)
            if cb_bmi and cb_bits and (best is None or cb_bits > best[3]):
                best = (pos + off_bmi, cb_bmi, pos + off_bits, cb_bits)
        pos += size
    if best is None:
        return None
    bmi = data[best[0]:best[0] + best[1]]
    bits = data[best[2]:best[2] + best[3]]
    head = b"BM" + struct.pack("<IHHI", 14 + len(bmi) + len(bits), 0, 0,
                               14 + len(bmi))
    buf = io.BytesIO()
    Image.open(io.BytesIO(head + bmi + bits)).save(buf, "PNG")
    return buf.getvalue()


def _emf_convert(data, ext):
    """EMF/WMF (illisibles par Affinity) -> (données, extension)."""
    png = None
    try:
        png = _emf_bitmap(data) if ext == "emf" else None
    except Exception:
        pass
    if png:
        return png, "png"
    import subprocess
    import tempfile
    soffice = shutil.which("soffice") or next(
        (p for p in ("/Applications/LibreOffice.app/Contents/MacOS/soffice",
                     r"C:\Program Files\LibreOffice\program\soffice.exe")
         if os.path.exists(p)), None)
    if soffice:
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, "image." + ext)
        with open(src, "wb") as f:
            f.write(data)
        subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                        "--outdir", tmp, src], capture_output=True)
        pdf = os.path.join(tmp, "image.pdf")
        if os.path.exists(pdf):
            with open(pdf, "rb") as f:
                return f.read(), "pdf"
    return data, ext


def _docx_from_doc(path):
    """Ancien .doc -> .docx temporaire (textutil intégré à macOS,
    LibreOffice ailleurs)."""
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0]
                       + ".docx")
    if sys.platform == "darwin":
        subprocess.run(["textutil", "-convert", "docx", "-output", out,
                        path], check=True, capture_output=True)
    else:
        # Windows : LibreOffice (Word pas installé, retour user).
        soffice = shutil.which("soffice") or next(
            (p for p in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                         r"C:\Program Files (x86)\LibreOffice\program"
                         r"\soffice.exe") if os.path.exists(p)), None)
        if not soffice:
            raise RuntimeError("ancien .doc : installe LibreOffice ou "
                               "enregistre-le en .docx")
        subprocess.run([soffice, "--headless", "--convert-to", "docx",
                        "--outdir", tmp, path], check=True,
                       capture_output=True)
    return out


_WP = ("{http://schemas.openxmlformats.org/drawingml/2006/"
       "wordprocessingDrawing}")
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
EMU = 12700  # EMU par point


def _docx_para(p, default_size, default_font):
    """Paragraphe python-docx -> dict size/font/color/align/text (ou None
    si vide)."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH as A
    text = nettoyer_texte.clean(p.text)[0].strip()
    if not text:
        return None
    runs = [r for r in p.runs if r.text.strip()] or [None]
    r = max(runs, key=lambda r: len(r.text) if r else 0)
    f, sf = (r.font if r else None), p.style.font

    def pick(attr, default):
        for src in (f, sf):
            v = getattr(src, attr, None) if src is not None else None
            if v is not None:
                return v
        return default
    size = pick("size", None)
    bold, italic = pick("bold", False), pick("italic", False)
    rgb = None
    if f is not None and f.color is not None and f.color.type is not None:
        rgb = f.color.rgb
    return {"text": text,
            "size": round(size.pt if size else default_size, 1),
            "font": (pick("name", default_font),
                     "Bold Italic" if bold and italic else "Bold" if bold
                     else "Italic" if italic else "Regular"),
            "color": tuple(c / 255 for c in rgb) if rgb else (0, 0, 0),
            "align": {A.CENTER: "CenterAlign", A.RIGHT: "RightAlign",
                      A.JUSTIFY: "LeftJustified"}.get(p.alignment,
                                                       "LeftAlign")}


def _anchor_box(anchor, w, h, margins):
    """Position d'un objet flottant Word (wp:anchor) en points.
    ponytail: relatif au paragraphe/ligne = approximé par la marge haute,
    Word ne stocke pas la position réelle du paragraphe."""
    ext = anchor.find(_WP + "extent")
    cw, ch = int(ext.get("cx")) / EMU, int(ext.get("cy")) / EMU
    left, top, right, bottom = margins
    pos = []
    for axis, size, full, lo, hi in (("H", cw, w, left, right),
                                     ("V", ch, h, top, bottom)):
        el = anchor.find(_WP + "position" + axis)
        rel = el.get("relativeFrom") if el is not None else "margin"
        start, span = ((0, full) if rel == "page" else (lo, hi - lo))
        off = el.find(_WP + "posOffset") if el is not None else None
        al = el.find(_WP + "align") if el is not None else None
        if off is not None:
            pos.append(start + int(off.text) / EMU)
        elif al is not None and al.text in ("center",):
            pos.append(start + (span - size) / 2)
        elif al is not None and al.text in ("right", "bottom", "outside"):
            pos.append(start + span - size)
        else:
            pos.append(start)
    return (pos[0], pos[1], pos[0] + cw, pos[1] + ch)


def convert_docx(path):
    """Word -> .idml. Texte courant dans un bloc aux marges ; images et
    zones de texte flottantes à leur position Word (faire-part,
    remerciements : mise en page faite par le client dans Word) ; images
    alignées sur le texte posées à droite de la page, sur la table de
    montage (leur place dans le flux n'a pas d'équivalent fiable)."""
    import io
    import docx
    from docx.text.paragraph import Paragraph
    from PIL import Image
    base, tidy = _prepare(path, "doc" if path.lower().endswith(".doc")
                          else "docx")
    src = _docx_from_doc(path) if path.lower().endswith(".doc") else path
    d = docx.Document(src)
    sec = d.sections[0]
    w, h = sec.page_width.pt, sec.page_height.pt
    margins = (sec.left_margin.pt, sec.top_margin.pt,
               w - sec.right_margin.pt, h - sec.bottom_margin.pt)
    normal = d.styles["Normal"].font
    dsize = normal.size.pt if normal.size else 11
    dfont = normal.name or "Calibri"
    out = _Idml(w, h, base)

    def para(p_el):
        return _docx_para(Paragraph(p_el, d._body), dsize, dfont)

    flow = [q for q in (_docx_para(p, dsize, dfont) for p in d.paragraphs)
            if q]
    boxes, pics, pasteboard = [], [], []
    for anchor in d.element.body.iter(_WP + "anchor"):
        box = _anchor_box(anchor, w, h, margins)
        txbx = [q for q in (para(p) for p in anchor.iter(_W + "p")) if q]
        blip = next(anchor.iter(_A + "blip"), None)
        if txbx:
            boxes.append((box, txbx))
        elif blip is not None:
            # wrapNone / derrière le texte : pas d'habillage.
            wrap = any(anchor.find(_WP + t) is not None for t in (
                "wrapSquare", "wrapTight", "wrapThrough",
                "wrapTopAndBottom"))
            pics.append((box, blip.get(_R + "embed"), wrap))
    for inline in d.element.body.iter(_WP + "inline"):
        blip = next(inline.iter(_A + "blip"), None)
        if blip is not None:
            pasteboard.append(blip.get(_R + "embed"))

    out.styles(flow + [q for _, ps in boxes for q in ps])

    def picture(rid, box=None, y=0, wrap=False):
        part = d.part.related_parts.get(rid)
        if part is None:
            return 0
        try:
            iw, ih = Image.open(io.BytesIO(part.blob)).size
        except Exception:
            return 0
        ext = (os.path.splitext(part.partname)[1][1:] or "png").lower()
        data = part.blob
        if ext in ("emf", "wmf"):
            data, ext = _emf_convert(data, ext)
            if ext == "png":
                iw, ih = Image.open(io.BytesIO(data)).size
        if box is None:  # table de montage, à droite de la page
            box = (w + 40, y, w + 240, y + 200 * ih / iw)
        out.image(data, ext, box, iw, ih, wrap)
        return box[3] - box[1]

    for box, rid, wrap in pics:
        picture(rid, box, wrap=wrap)
    if flow:
        out.text(margins, flow)
    for box, ps in boxes:
        out.text(box, ps)
    y = 0
    for rid in pasteboard:
        y += picture(rid, y=y) + 20
    result = out.save()
    tidy()
    return result


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
    import io
    import struct
    from PIL import Image
    bmp = io.BytesIO()
    Image.new("RGB", (3, 2), (200, 10, 10)).save(bmp, "BMP")
    bmi, bits = bmp.getvalue()[14:54], bmp.getvalue()[54:]
    rec = struct.pack("<II16s6iIIII", 81, 80 + len(bmi) + len(bits),
                      b"\0" * 16, 0, 0, 0, 0, 3, 2, 80, len(bmi),
                      80 + len(bmi), len(bits)) + b"\0" * 16 + bmi + bits
    emf = struct.pack("<II", 1, 8) + rec
    png = _emf_bitmap(emf)
    assert Image.open(io.BytesIO(png)).getpixel((0, 0)) == (200, 10, 10)
    from xml.etree import ElementTree as ET
    anc = ET.fromstring(
        f'<a xmlns:wp="{_WP[1:-1]}"><wp:positionH relativeFrom="page">'
        '<wp:posOffset>1270000</wp:posOffset></wp:positionH>'
        '<wp:positionV relativeFrom="margin"><wp:align>center</wp:align>'
        '</wp:positionV><wp:extent cx="2540000" cy="1270000"/></a>')
    assert _anchor_box(anc, 600, 800, (50, 60, 550, 740)) == (
        100.0, 350.0, 300.0, 450.0)
    print("ok")
