# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import qrcode
import qrcode.image.svg

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                           MAIN                            #
#############################################################
os.system('cls' if os.name == 'nt' else 'clear')
print("Generateur de QR Code")
print("#" * 32)
url = input("Veuillez entrer une URL : ")

img = qrcode.make(url , image_factory=qrcode.image.svg.SvgImage)

with open('qr.svg', 'wb') as qr:
    img.save(qr)
    print(f"Image enregistrée dans {PATH}")