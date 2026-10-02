"""Self-check du rangement Autocollants (Montage collage.py)."""

__version__ = "2.3.11"
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "montage", Path(__file__).with_name("Montage collage.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

placed, h = m.pack_stickers([(100, 50), (300, 40), (500, 90), (950, 950)],
                            400, 10)
assert {p[0] for p in placed} == {0, 1, 2}  # 950 ne passe pas
assert [p for p in placed if p[0] == 2][0][3]  # 500 pivoté
assert all(x + 10 <= 400 for _, x, _, _ in placed)
assert m.sticker_count("12X_a.png") == 12 and m.sticker_count("a.png") == 1
print("OK", h)
placed, _ = m.pack_stickers([(100, 50)], 400, 10)
assert placed[0][1] == 150  # centré : (400 - 120) // 2 + 10
