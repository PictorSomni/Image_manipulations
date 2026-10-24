# -*- coding: utf-8 -*-
"""Lance les auto-contrôles historiques Data/test_*.py (scripts autonomes)
pour que `python -m unittest discover tests` couvre tout."""

import subprocess
import sys
import unittest
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "Data"


class TestScripts(unittest.TestCase):
    def test_scripts(self):
        for script in sorted(DATA.glob("test_*.py")):
            with self.subTest(script=script.name):
                run = subprocess.run([sys.executable, str(script)],
                                     capture_output=True, text=True,
                                     timeout=600, cwd=str(DATA))
                self.assertEqual(run.returncode, 0,
                                 run.stdout[-1500:] + run.stderr[-1500:])


if __name__ == "__main__":
    unittest.main()
