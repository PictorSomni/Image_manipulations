"""Self-check du rangement Autocollants (Montage collage.py)."""

__version__ = "2.3.13"

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "montage", Path(__file__).with_name("Montage collage.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

placed, h = m.pack_stickers([(100, 50), (300, 40), (500, 90), (950, 950)],
                            400, 10, 20)
assert {p[0] for p in placed} == {0, 1, 2}  # 950 ne passe pas
assert [p for p in placed if p[0] == 2][0][3]  # 500 pivoté
assert all(20 <= x and y >= 20 for _, x, y, _ in placed)
placed, h = m.pack_stickers([(100, 50)] * 2, 400, 0, 10)
assert [p[1] for p in placed] == [100, 200] and h == 70  # centré, collés
assert m.sticker_count("12X_a.png") == 12 and m.sticker_count("a.png") == 1
print("OK")
