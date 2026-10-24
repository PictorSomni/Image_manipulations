# -*- coding: utf-8 -*-
"""
Tests des parties critiques (prix, imposition du livret, LUT, pipeline de
Retouche photo). Bibliothèque standard uniquement :

    python -m unittest discover tests
"""

import importlib.machinery
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "Data"
sys.path.insert(0, str(DATA))

import CONSTANTS  # noqa: E402
import hub_sync  # noqa: E402
import imposition  # noqa: E402


def _load(filename, name):
    spec = importlib.util.spec_from_loader(
        name, importlib.machinery.SourceFileLoader(name, str(DATA / filename)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPrix(unittest.TestCase):
    def test_paliers_prints(self):
        tiers = CONSTANTS.PRINTS["10x15"]
        for count, idx in ((1, 0), (10, 0), (11, 1), (50, 1), (51, 2),
                           (100, 2), (101, 3), (200, 3), (201, 4),
                           (5000, 4)):
            self.assertEqual(CONSTANTS.unit_price("10x15", count), tiers[idx],
                             count)

    def test_studios_fixe(self):
        self.assertEqual(CONSTANTS.unit_price("20x30", 500, "STUDIOS"),
                         CONSTANTS.STUDIOS["20x30"])

    def test_carres_prix_meme_largeur(self):
        for square, ref in CONSTANTS.PRICE_ALIASES.items():
            for mode in ("PRINTS", "STUDIOS"):
                self.assertEqual(CONSTANTS.unit_price(square, 30, mode),
                                 CONSTANTS.unit_price(ref, 30, mode),
                                 (square, mode))

    def test_format_inconnu(self):
        self.assertIsNone(CONSTANTS.unit_price("Retouche", 3))
        self.assertIsNone(CONSTANTS.unit_price("Retouche", 3, "STUDIOS"))


class TestImposition(unittest.TestCase):
    def test_chaque_page_une_fois(self):
        for n in range(4, 65, 4):
            sheets = imposition.saddle_stitch(n)
            pages = [p for sheet in sheets for side in sheet for p in side]
            self.assertEqual(sorted(pages), list(range(1, n + 1)), n)
            self.assertEqual(len(sheets), n // 4)

    def test_couverture_premiere_feuille(self):
        (front, back), *_ = imposition.saddle_stitch(8)
        self.assertEqual(front, (8, 1))   # 4e de couv. | 1re de couv.
        self.assertEqual(back, (2, 7))

    def test_pages_en_vis_a_vis(self):
        # Une fois plié, chaque côté de feuille somme à n + 1.
        n = 16
        for front, back in imposition.saddle_stitch(n):
            self.assertEqual(sum(front), n + 1)
            self.assertEqual(sum(back), n + 1)

    def test_pas_multiple_de_4(self):
        with self.assertRaises(ValueError):
            imposition.saddle_stitch(6)


class TestFusionListes(unittest.TestCase):
    """hub_sync.merge3 : deux appareils modifient la même liste."""
    A, B, C = {"t": "a"}, {"t": "b"}, {"t": "c"}

    def test_ajouts_des_deux_cotes(self):
        base = [self.A]
        mine = [self.A, {"t": "moi"}]
        theirs = [self.A, {"t": "autre"}]
        merged = hub_sync.merge3(base, mine, theirs)
        self.assertIn({"t": "moi"}, merged)
        self.assertIn({"t": "autre"}, merged)

    def test_modif_garde_sa_place(self):
        base = [self.A, self.B, self.C]
        mine = [self.A, {"t": "b", "fait": "True"}, self.C]
        theirs = [self.A, self.B, self.C, {"t": "d"}]
        self.assertEqual(hub_sync.merge3(base, mine, theirs),
                         [self.A, {"t": "b", "fait": "True"}, self.C,
                          {"t": "d"}])

    def test_suppression_appliquee(self):
        base = [self.A, self.B]
        theirs = [self.A, self.B, self.C]
        self.assertEqual(hub_sync.merge3(base, [self.A], theirs),
                         [self.A, self.C])

    def test_reordonner_sans_conflit(self):
        base = [self.A, self.B, self.C]
        mine = [self.C, self.A, self.B]
        self.assertEqual(hub_sync.merge3(base, mine, base), mine)

    def test_doublons(self):
        base = [self.A, self.A]
        self.assertEqual(hub_sync.merge3(base, [self.A], base + [self.B]),
                         [self.A, self.B])


class TestLut(unittest.TestCase):
    """Le chemin rapide (Pillow, domaine 0..1) doit donner le même résultat
    que le calcul numpy (domaine différent de 0..1)."""

    @staticmethod
    def _cube(path, size, transform, domain_max=1.0):
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"LUT_3D_SIZE {size}\n")
            if domain_max != 1.0:
                f.write(f"DOMAIN_MAX {domain_max} {domain_max} "
                        f"{domain_max}\n")
            for b in range(size):
                for g in range(size):
                    for r in range(size):
                        v = [x / (size - 1) * domain_max for x in (r, g, b)]
                        f.write(" ".join(f"{c:.6f}" for c in transform(v))
                                + "\n")

    def test_identite_et_parite(self):
        import numpy as np
        from PIL import Image
        import image_ops
        rng = np.random.default_rng(0)
        img = Image.fromarray(rng.integers(0, 256, (40, 60, 3),
                                           dtype=np.uint8))
        with tempfile.TemporaryDirectory() as tmp:
            ident = os.path.join(tmp, "ident_test.cube")
            self._cube(ident, 17, lambda v: v)
            out = image_ops.apply_cube_lut(img, ident, 100)
            diff = np.abs(np.asarray(out, dtype=int)
                          - np.asarray(img, dtype=int)).max()
            self.assertLessEqual(diff, 1)

            warm = lambda v: [min(1, v[0] * 1.1), v[1], v[2] * 0.9]  # noqa
            fast = os.path.join(tmp, "warm_fast.cube")
            slow = os.path.join(tmp, "warm_slow.cube")
            self._cube(fast, 17, warm)
            # Domaine 0..1.0001 : force le chemin numpy, résultat ≈ égal.
            self._cube(slow, 17, lambda v: warm([x / 1.0001 for x in v]),
                       domain_max=1.0001)
            a = np.asarray(image_ops.apply_cube_lut(img, fast, 100), int)
            b = np.asarray(image_ops.apply_cube_lut(img, slow, 100), int)
            self.assertLessEqual(np.abs(a - b).max(), 2)


class TestPipelineRetouche(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.mod = _load("Retouche photo.pyw", "retouche_photo")
        except Exception as exc:  # flet absent, etc.
            raise unittest.SkipTest(f"Retouche photo non chargeable : {exc}")

    def test_parametres_par_defaut_neutres(self):
        from PIL import Image
        img = Image.new("RGB", (120, 80), (120, 140, 160))
        out = self.mod.run_pipeline(img, self.mod.default_params())
        self.assertEqual(out.size, img.size)

    def test_ne_mute_pas_la_source(self):
        import numpy as np
        from PIL import Image
        img = Image.fromarray(np.random.default_rng(1).integers(
            0, 256, (64, 64, 3), dtype=np.uint8))
        before = img.tobytes()
        self.mod.run_pipeline(img, self.mod.default_params())
        self.assertEqual(img.tobytes(), before)

    def test_cache_resultat_identique(self):
        from PIL import Image
        img = Image.new("RGB", (100, 100), (90, 100, 110))
        params = self.mod.default_params()
        cache = {}
        a = self.mod.run_pipeline(img, params, cache=cache)
        b = self.mod.run_pipeline(img, params, cache=cache)
        self.assertEqual(a.tobytes(), b.tobytes())


if __name__ == "__main__":
    unittest.main()
