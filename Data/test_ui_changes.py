# -*- coding: utf-8 -*-
"""
test_ui_changes.py — auto-contrôle des logiques ajoutées côté interface.

Couvre ce qui casse silencieusement : le dimensionnement HDPI des aperçus
et le nommage des préréglages de Retouche par lot (un nom saisi librement
devient un nom de fichier). Les parties Flet ne sont pas testées ici —
elles se vérifient à l'œil, ces calculs non.

Lancer :  python3 "Data/test_ui_changes.py"
"""

import importlib
import importlib.machinery
import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import CONSTANTS
import image_ops


def _load_retouche():
    """Importe « Retouche par lot.pyw » (extension non importable telle
    quelle) pour tester ses fonctions de préréglage.

    Les fonctions testées sont pures, mais elles vivent dans un fichier qui
    importe Flet au chargement : on neutralise cet import quand Flet est
    absent (machine sans interface graphique, intégration continue) plutôt
    que de renoncer au test.
    """
    try:
        importlib.import_module("flet")
    except ImportError:
        sys.modules["flet"] = MagicMock()

    path = Path(__file__).resolve().parent / "Retouche par lot.pyw"
    spec = importlib.util.spec_from_loader(
        "retouche_par_lot",
        importlib.machinery.SourceFileLoader("retouche_par_lot", str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_hub():
    """Importe Hub.pyw (racine du dépôt) pour tester sa persistance JSON."""
    try:
        importlib.import_module("flet")
    except ImportError:
        sys.modules["flet"] = MagicMock()

    path = Path(__file__).resolve().parent.parent / "Hub.pyw"
    spec = importlib.util.spec_from_loader(
        "hub", importlib.machinery.SourceFileLoader("hub", str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_save_json_is_atomic(mod):
    """Un .order.json tronqué = la commande client perdue : l'écriture doit
    remplacer le fichier d'un bloc, jamais le vider avant d'écrire."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target = os.path.join(tmpdir, "order.json")
        assert mod._save_json(target, {"a": {"10x15": 2}}) is True
        assert mod._load_json(target, None) == {"a": {"10x15": 2}}

        # Le temporaire ne survit pas à une écriture réussie.
        assert os.listdir(tmpdir) == ["order.json"]

        # Échec d'écriture : l'ancien contenu est INTACT (c'est tout
        # l'intérêt du passage par .tmp + os.replace), l'erreur est
        # signalée, et le temporaire est nettoyé.
        reported = []
        mod._save_error_hook["fn"] = reported.append
        try:
            # Un objet non sérialisable fait échouer json.dump en plein
            # milieu, après que le .tmp a déjà été ouvert en écriture.
            assert mod._save_json(target, {"a": object()}) is False
        finally:
            mod._save_error_hook["fn"] = None
        assert mod._load_json(target, None) == {"a": {"10x15": 2}}
        assert os.listdir(tmpdir) == ["order.json"]
        assert reported and "order.json" in reported[0]

        # Fichier absent ou illisible : valeur par défaut, pas d'exception.
        assert mod._load_json(os.path.join(tmpdir, "nope.json"), {}) == {}
    print("  _save_json (atomique + report d'erreur) : OK")


def test_preview_max_px():
    floor = CONSTANTS.PREVIEW_MAX_PIXELS
    ceiling = CONSTANTS.PREVIEW_MAX_PIXELS_CEILING

    # Petit widget : on ne descend jamais sous l'ancien comportement.
    assert image_ops.preview_max_px(200, floor, ceiling) == floor

    # Widget HDPI : c'est le cas que la correction visait — un aperçu de
    # 900 px logiques occupe 1800 px physiques sur un Retina, il doit être
    # rendu plus grand que le plancher, sinon il est étiré à l'affichage.
    assert image_ops.preview_max_px(900, floor, ceiling, 2.0) == 1800
    assert image_ops.preview_max_px(900, floor, ceiling, 2.0) > floor

    # Très grand écran : plafonné, sinon l'aperçu live décroche du geste.
    assert image_ops.preview_max_px(4000, floor, ceiling) == ceiling

    # Robustesse : taille de widget absente avant le premier rendu.
    assert image_ops.preview_max_px(0, floor, ceiling) == floor
    assert image_ops.preview_max_px(None, floor, ceiling) == floor

    # Bornes propres à Retouche par lot (proxy plus généreux : grain).
    assert (image_ops.preview_max_px(
        4000, CONSTANTS.RETOUCHE_LOT_PREVIEW_MAX_PIXELS,
        CONSTANTS.RETOUCHE_LOT_PREVIEW_CEILING)
        == CONSTANTS.RETOUCHE_LOT_PREVIEW_CEILING)
    print("  preview_max_px : OK")


def _scanned_print_image():
    """Imite un tirage argentique scanné : contrastes doux, grain, aucune
    arête franche à l'échelle du pixel. C'est ce matériau qui a disqualifié
    le flood fill en plage flottante — il y voyait l'image entière comme
    une seule zone lisse et passait de 0 % à 80 % de couverture entre les
    tolérances 2 et 4."""
    import numpy as np
    from PIL import Image
    import cv2
    rng = np.random.default_rng(42)
    h = w = 300
    arr = np.full((h, w, 3), 190.0)
    arr[:, :150] += [20, -15, -40]          # motif du papier peint
    arr[100:200, 100:200] = [150, 120, 100]  # zone visée, peu contrastée
    arr = cv2.GaussianBlur(arr, (0, 0), 2)   # optique douce + scan
    arr += rng.normal(0, 5, arr.shape)       # grain
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def test_flood_is_dosable():
    """La propriété qui compte à l'usage : la zone doit croître
    PROGRESSIVEMENT avec la tolérance. Un réglage qui bascule de « rien » à
    « toute l'image » est inutilisable à la main, a fortiori au doigt."""
    img = _scanned_print_image()
    seed = (150, 150)
    coverage = [image_ops.flood_background_mask(img, seed, tolerance=t).mean()
                for t in (10, 20, 40, 60, 100)]

    # Monotone : élargir la tolérance ne peut que retenir plus.
    for before, after in zip(coverage, coverage[1:]):
        assert after >= before - 1e-9, coverage

    # Et sans falaise : aucun palier ne doit avaler plus de la moitié de
    # l'image d'un coup, sinon le glissé redevient tout ou rien.
    for before, after in zip(coverage, coverage[1:]):
        assert after - before < 0.5, f"saut brutal : {coverage}"

    # À la tolérance par défaut, on reste sur la zone visée : pas de fuite
    # dans toute l'image (le symptôme rapporté avec la plage flottante).
    default = image_ops.flood_background_mask(img, seed, tolerance=40).mean()
    assert default < 0.5, f"{default:.1%} de l'image à la tolérance 40"

    # Une graine posée ailleurs ne doit pas ramener la zone visée : c'est
    # ce qui rend le retrait (sign = -1) et les picks successifs utiles.
    other = image_ops.flood_background_mask(img, (20, 20), tolerance=40)
    assert not other[150, 150]
    print("  flood fill (réglage dosable) : OK")


def _id_portrait_image():
    """Portrait d'identité de synthèse : fond clair avec chute de lumière,
    tête en tons chair, buste sombre COUPÉ PAR LE BAS du cadre — la
    géométrie qui piégeait la passe automatique."""
    import numpy as np
    import cv2
    from PIL import Image
    rng = np.random.default_rng(7)
    h, w = 900, 600
    yy, xx = np.mgrid[0:h, 0:w]
    falloff = 250 - 35 * (((xx - w/2)/(w/2))**2 + ((yy - h/3)/(h/1.5))**2)
    arr = np.dstack([falloff, falloff * 0.995, falloff * 0.99])
    subject = np.zeros((h, w), np.uint8)
    for centre, axes, colour in (((w//2, 310), (125, 155), (222, 178, 150)),
                                 ((w//2, 750), (215, 260), (55, 60, 75))):
        cv2.ellipse(arr, centre, axes, 0, 0, 360, colour, -1)
        cv2.ellipse(subject, centre, axes, 0, 0, 360, 1, -1)
    arr += rng.normal(0, 2.5, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img, subject.astype(bool)


def test_flood_auto_border_spares_subject():
    """Passe automatique (seed_xy=None) : elle doit prendre le fond sans
    toucher au sujet. Le bord inférieur est exclu des graines parce que le
    buste y est coupé par le cadre — une graine bas-centre emportait 70 %
    du sujet."""
    img, subject = _id_portrait_image()
    mask = image_ops.flood_background_mask(img, None, tolerance=40)

    background = mask[~subject].mean()
    eaten = mask[subject].mean()
    assert background > 0.95, f"fond capté à seulement {background:.1%}"
    assert eaten < 0.02, f"sujet rongé à {eaten:.1%}"

    # Le visage en particulier — le pire endroit où mordre.
    head = np.zeros(subject.shape, bool)
    head[160:460, 175:425] = True
    assert mask[head & subject].mean() < 0.01
    print("  flood fill (passe auto, sujet préservé) : OK")


def test_flood_seed_mapping():
    """La graine est donnée en pixels de l'image d'origine, mais le flood
    tourne sur une version réduite : si la mise à l'échelle du point est
    fausse, on remplit au mauvais endroit."""
    import numpy as np
    from PIL import Image
    arr = np.zeros((600, 800, 3), dtype=np.uint8)
    arr[:, :400] = [30, 30, 30]        # moitié gauche sombre
    arr[:, 400:] = [220, 220, 220]     # moitié droite claire
    img = Image.fromarray(arr)

    left = image_ops.flood_background_mask(img, (50, 300), tolerance=8,
                                           max_px=200)
    assert left[300, 50] and not left[300, 750], "graine gauche mal projetée"

    right = image_ops.flood_background_mask(img, (750, 300), tolerance=8,
                                            max_px=200)
    assert right[300, 750] and not right[300, 50], "graine droite mal projetée"
    print("  flood fill (projection de la graine) : OK")


def test_preset_names(mod):
    # Cas courant : le nom est conservé, accents compris.
    assert mod.sanitize_preset_name("Portrait été") == "Portrait été"
    assert mod.sanitize_preset_name("  N&B argentique  ") == "NB argentique"

    # Frontière de confiance : le nom vient d'un champ libre et devient un
    # chemin de fichier. Rien ne doit pouvoir sortir de PRESETS_DIR.
    for hostile in ("../../etc/passwd", "..\\..\\CONSTANTS", "a/b", "a\\b"):
        safe = mod.sanitize_preset_name(hostile)
        assert "/" not in safe and "\\" not in safe, hostile
        assert ".." not in safe, hostile

    # Noms qui ne laissent rien d'exploitable -> refus explicite.
    for empty in ("", "   ", "...", "/", None):
        assert mod.sanitize_preset_name(empty) == "", repr(empty)
    print("  sanitize_preset_name : OK")


def test_preset_roundtrip(mod):
    with tempfile.TemporaryDirectory() as tmp:
        mod.PRESETS_DIR = Path(tmp) / "presets_retouche"
        assert mod.list_presets() == []  # dossier absent : pas d'erreur

        params = mod.default_params()
        params["couleur"]["exposure"] = 42
        saved = mod.save_preset("Mon préréglage", params)

        assert saved == "Mon préréglage"
        assert mod.list_presets() == ["Mon préréglage"]
        assert mod.load_preset("Mon préréglage")["couleur"]["exposure"] == 42

        # Réenregistrer sous le même nom écrase sans créer de doublon.
        params["couleur"]["exposure"] = 7
        mod.save_preset("Mon préréglage", params)
        assert mod.list_presets() == ["Mon préréglage"]
        assert mod.load_preset("Mon préréglage")["couleur"]["exposure"] == 7

        # Un nom vide est refusé plutôt que d'écrire « .json ».
        try:
            mod.save_preset("   ", params)
        except ValueError:
            pass
        else:
            raise AssertionError("nom vide accepté")
    print("  préréglages (aller-retour) : OK")


def test_params_roundtrip_shape(mod):
    """Un préréglage doit rester rechargeable par _update_in_place, qui
    n'écrit que les clés déjà connues : si les deux structures divergent,
    un préréglage se charge en silence sans rien changer."""
    target = mod.default_params()
    source = mod.default_params()
    source["nettete"]["percent1"] = 133
    mod._update_in_place(target, source)
    assert target["nettete"]["percent1"] == 133

    # Les sous-dicts gardent leur identité : les contrôles Flet les
    # capturent par référence à la construction de l'UI, les remplacer
    # désynchroniserait l'affichage de l'état.
    nettete_before = target["nettete"]
    mod._update_in_place(target, mod.default_params())
    assert target["nettete"] is nettete_before

    # Clé inconnue (préréglage écrit par une version plus récente) :
    # recopiée telle quelle, sans exception. run_pipeline ne lit que les
    # clés qu'il connaît — l'important est qu'un vieux poste ne refuse pas
    # de charger le fichier.
    mod._update_in_place(target, {"section_inexistante": {"x": 1}})
    assert target["couleur"]["exposure"] == 0
    print("  _update_in_place : OK")


if __name__ == "__main__":
    print("Vérifications :")
    test_preview_max_px()
    test_flood_is_dosable()
    test_flood_auto_border_spares_subject()
    test_flood_seed_mapping()
    retouche = _load_retouche()
    test_preset_names(retouche)
    test_preset_roundtrip(retouche)
    test_params_roundtrip_shape(retouche)
    test_save_json_is_atomic(_load_hub())
    print("Tout est passé.")
