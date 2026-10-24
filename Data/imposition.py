# -*- coding: utf-8 -*-
"""Imposition piqûre à cheval (Livret.py), isolée pour être testée."""


def saddle_stitch(n):
    """Pour un livret de n pages (multiple de 4), la liste des feuilles
    recto-verso : ((recto gauche, recto droite), (verso gauche, verso
    droite)), pages numérotées à partir de 1. La 1re feuille porte les
    couvertures (dernière à gauche, première à droite), puis on avance
    vers le centre — algorithme standard des logiciels de « booklet
    printing » (ex. psbook)."""
    if n <= 0 or n % 4:
        raise ValueError(f"{n} pages : il faut un multiple de 4")
    return [((n - 2 * s, 2 * s + 1), (2 * s + 2, n - 2 * s - 1))
            for s in range(n // 4)]
