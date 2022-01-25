# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from time import monotonic

#############################################################
#                         CONSTANTS                         #
#############################################################
DPI = 300

#############################################################
#                         CONTENT                           #
#############################################################


def mm_to_pixels(mm, dpi):
    return round((float(mm) / 25.4) * dpi)


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def wait(delay=1):
    now = monotonic()
    while monotonic() <= now + delay:
        pass


#############################################################
#                           MAIN                            #
#############################################################
clear()
while True:
    wait()
    try:
        MM = int(
            input(f"\n=> Quelle largeur en mm faut-il calculer en pixels (en {DPI} dpi) ?\nAppuyez sur 'Entrée' pour quitter "))
    except Exception:
        clear()
        print("\nBelle journée !")
        wait()
        clear()
        sys.exit(1)

    clear()
    print("#" * 32)
    print(f"\n{MM} mm en {DPI} dpi :")
    print("-" * 32)
    print(f"{mm_to_pixels(MM, DPI)} pixels\n")
    print("#" * 32)
