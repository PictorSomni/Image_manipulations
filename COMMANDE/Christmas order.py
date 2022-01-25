# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from time import sleep
from PIL import Image, ImageOps, ImageChops
import numpy as np
from numpy import linalg


#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
# MODELS = ("MAGNET_ROND.png", "MAGNET_ROND_ALPHA.png", "MUG.png", "MUG_ALPHA.png", "SUPPORT_BOIS.png", "PORTE-CLEF.png", "PORTE-CLEF_ALPHA.png")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

Y_OFFSET = 4
PIXEL_SIZE = 720

###### FICHE ######
RECTO = Image.open(f"{PATH}\\Order_data\\NOEL RECTO.png")
VERSO = Image.open(f"{PATH}\\Order_data\\NOEL VERSO.png")
FICHE = [RECTO, VERSO]
THUMB_SIZE = 200    # px
BIG_THUMB_SIZE = 300# px
THUMB_LEFT = 653    # px
THUMB_UP = 2071     # px

####### MUG #######
MUG = Image.open("{}\\Order_data\\MUG.png".format(PATH))
MUG_ALPHA = Image.open("{}\\Order_data\\MUG_ALPHA.png".format(PATH))
MUG_LEFT = 100
MUG_UP = 420
MUG_RIGHT = 1510
MUG_DOWN = 2080
MUG_THUMB_UP = 1195

####### MAGNET #######
MAGNET = Image.open("{}\\Order_data\\MAGNET_ROND.png".format(PATH))
MAGNET_ALPHA = Image.open("{}\\Order_data\\MAGNET_ROND_ALPHA.png".format(PATH))
MAGNET_LEFT = 78
MAGNET_UP = 157
MAGNET_RIGHT = 1708
MAGNET_DOWN = 1634
MAGNET_THUMB_UP = 599

####### PORTE-CLEF #######
ID = Image.open("{}\\Order_data\\PORTE-CLEF.png".format(PATH))
ID_ALPHA = Image.open("{}\\Order_data\\PORTE-CLEF_ALPHA.png".format(PATH))
ID_LEFT = 467
ID_UP = 451
ID_RIGHT = 1310
ID_DOWN = 1498
ID_THUMB_UP = 897

####### BOITE A TARTINE #######
BOITE = Image.open("{}\\Order_data\\BOITE-TARTINE.png".format(PATH))
BOITE_ALPHA = Image.open("{}\\Order_data\\BOITE-TARTINE_ALPHA.png".format(PATH))
BOITE_LEFT = 313
BOITE_UP = 566
BOITE_RIGHT = 1842
BOITE_DOWN = 1311
BOITE_THUMB_UP = 302

####### PLUMIER #######
PLUMIER = Image.open("{}\\Order_data\\PLUMIER.png".format(PATH))
PLUMIER_ALPHA = Image.open("{}\\Order_data\\PLUMIER_ALPHA.png".format(PATH))
PLUMIER_LEFT = 153
PLUMIER_UP = 302
PLUMIER_RIGHT = 1980
PLUMIER_DOWN = 734

####### CADRE #######
CADRE = Image.open("{}\\Order_data\\CADRE.png".format(PATH))
CADRE_ALPHA = Image.open("{}\\Order_data\\CADRE_ALPHA.png".format(PATH))
CADRE_LEFT = 575
CADRE_UP = 390
CADRE_RIGHT = 1585
CADRE_DOWN = 1800
CADRE_THUMB_LEFT = 128

####### PASSE #######
PASSE = Image.open("{}\\Order_data\\PASSE.png".format(PATH))
PASSE_ALPHA = Image.open("{}\\Order_data\\PASSE_ALPHA.png".format(PATH))
PASSE_LEFT = 316
PASSE_UP = 541
PASSE_RIGHT = 1138
PASSE_DOWN = 1647
PASSE_THUMB_LEFT = 1090

####### SUPPORT_BOIS #######
BOIS = Image.open("{}\\Order_data\\SUPPORT_BOIS.png".format(PATH))
BOIS_ALPHA = Image.open("{}\\Order_data\\SUPPORT_BOIS_ALPHA.png".format(PATH))
BOIS_LEFT = 442
BOIS_UP = 442
BOIS_RIGHT = 1348
BOIS_DOWN = 1601
BOIS_THUMB_LEFT = 2033

####### BOULE A NEIGE #######
NEIGE = Image.open("{}\\Order_data\\NEIGE.png".format(PATH))
NEIGE_ALPHA = Image.open("{}\\Order_data\\NEIGE_ALPHA.png".format(PATH))
NEIGE_LEFT = 176
NEIGE_UP = 235
NEIGE_RIGHT = 1610
NEIGE_DOWN = 1483
NEIGE_THUMB_UP = 1712

####### CALENDRIER #######
CAL = Image.open("{}\\Order_data\\CALENDRIER.png".format(PATH))
CAL_ALPHA = Image.open("{}\\Order_data\\CALENDRIER_ALPHA.png".format(PATH))
CAL_LEFT = 192
CAL_UP = 266
CAL_RIGHT = 3316
CAL_DOWN = 2238
CAL_THUMB_UP = 1978

# ####### VOEUX #######
# VOEUX1 = Image.open("{}\\Order_data\\VOEUX_1.png".format(PATH))
# VOEUX2 = Image.open("{}\\Order_data\\VOEUX_2.png".format(PATH))
# VOEUX_ALPHA = Image.open("{}\\Order_data\\VOEUX_ALPHA.png".format(PATH))
# VOEUX_LEFT = 190
# VOEUX_UP = 148
# VOEUX_RIGHT = 1101
# VOEUX_DOWN = 1057
# VOEUX1_THUMB_UP = 701
# VOEUX1_THUMB_LEFT = 2440
# VOEUX2_THUMB_UP = 899
# VOEUX2_THUMB_LEFT = 2440


class Order () :
    #############################################################
    #                         METHODS                           #
    #############################################################
    def __init__(self):
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"{TOTAL} images trouvées !")
        print("#" * 32 + "\n")
        self.main()


    def fit_in(self, max_size, primary_size, secondary_size):

        primary_ratio = (max_size/float(primary_size))
        secondary_ratio = int((float(secondary_size)*float(primary_ratio)))
        return secondary_ratio


    def perspective_transform(self,
        xyA1, xyA2, xyA3, xyA4,
        xyB1, xyB2, xyB3, xyB4):

        A = np.array([
                [xyA1[0], xyA1[1], 1, 0, 0, 0, -xyB1[0] * xyA1[0], -xyB1[0] * xyA1[1]],
                [0, 0, 0, xyA1[0], xyA1[1], 1, -xyB1[1] * xyA1[0], -xyB1[1] * xyA1[1]],
                [xyA2[0], xyA2[1], 1, 0, 0, 0, -xyB2[0] * xyA2[0], -xyB2[0] * xyA2[1]],
                [0, 0, 0, xyA2[0], xyA2[1], 1, -xyB2[1] * xyA2[0], -xyB2[1] * xyA2[1]],
                [xyA3[0], xyA3[1], 1, 0, 0, 0, -xyB3[0] * xyA3[0], -xyB3[0] * xyA3[1]],
                [0, 0, 0, xyA3[0], xyA3[1], 1, -xyB3[1] * xyA3[0], -xyB3[1] * xyA3[1]],
                [xyA4[0], xyA4[1], 1, 0, 0, 0, -xyB4[0] * xyA4[0], -xyB4[0] * xyA4[1]],
                [0, 0, 0, xyA4[0], xyA4[1], 1, -xyB4[1] * xyA4[0], -xyB4[1] * xyA4[1]],
                ], dtype=np.float32)
        B = np.array([
                xyB1[0],
                xyB1[1],
                xyB2[0],
                xyB2[1],
                xyB3[0],
                xyB3[1],
                xyB4[0],
                xyB4[1],
                ], dtype=np.float32)
        return linalg.solve(A, B)


    def combine_images(self, IMAGE, LEFT, UP, RIGHT, DOWN, BG, ALPHA=None, perspective = False, perspective_coefficient = 60, FIT = False, height_multiplier = 1.0, orientation = False):

        # ORIENTATION
        ###########
        if orientation == True :
            if IMAGE.width > IMAGE.height :
                    BG = BG.rotate(90, expand=True)
                    ALPHA = ALPHA.rotate(90, expand=True)

                    temp_left = LEFT
                    temp_right = RIGHT
                    temp_up = UP
                    temp_down = DOWN
                    LEFT = temp_up
                    UP = temp_left
                    RIGHT = temp_down
                    DOWN = temp_right
                    
        ###########

        WIDTH = RIGHT - LEFT
        HEIGHT = DOWN - UP        
        
        result = Image.new('RGBA', (WIDTH, HEIGHT), (255, 255, 255, 0))

        # FIT -IN
        ###########
        if FIT == True :

            cropped_image = IMAGE.resize((WIDTH, self.fit_in(WIDTH, IMAGE.width, IMAGE.height)), Image.LANCZOS)
            if cropped_image.height > HEIGHT :
                cropped_image = IMAGE.resize((self.fit_in(HEIGHT, IMAGE.height, IMAGE.width), HEIGHT), Image.LANCZOS)
        ###########

        # FILL-IN
        ###########
        else :

            cropped_image = IMAGE.resize((self.fit_in(HEIGHT, IMAGE.height, IMAGE.width), HEIGHT), Image.LANCZOS)
            if cropped_image.width < WIDTH :
                cropped_image = IMAGE.resize((WIDTH, self.fit_in(WIDTH, IMAGE.width, IMAGE.height)), Image.LANCZOS)
        ###########

        # PERSPECTIVE
        ###########
        if perspective == True :

            coeff = self.perspective_transform(
            (0, 0),
            (WIDTH, 0),
            (WIDTH,HEIGHT),
            (0, HEIGHT),
            # =>
            (- perspective_coefficient, 0),
            (WIDTH + perspective_coefficient, 0),
            (WIDTH, HEIGHT),
            (0, HEIGHT),
            )
            cropped_image = cropped_image.transform((cropped_image.width, cropped_image.height), method=Image.PERSPECTIVE, data=coeff)
            cropped_image = IMAGE.resize((self.fit_in(HEIGHT, IMAGE.height, IMAGE.width), int(HEIGHT * height_multiplier)), Image.LANCZOS)
            
            if cropped_image.width < WIDTH :
                cropped_image = IMAGE.resize((WIDTH, int(self.fit_in(WIDTH, IMAGE.width, IMAGE.height)  * height_multiplier)), Image.LANCZOS)
            
            # if cropped_image.height > HEIGHT :
            #     cropped_image = IMAGE.resize((int(self.fit_in(HEIGHT, IMAGE.height, IMAGE.width)  * height_multiplier), HEIGHT), Image.LANCZOS)
        ###########


        offset = (result.width - cropped_image.width) // 2, (result.height - cropped_image.height) // Y_OFFSET
        result.paste(cropped_image, offset)

        sized_result = Image.new("RGBA", BG.size, (255, 255, 255, 0))
        sized_result.paste(result, (LEFT, UP, RIGHT, DOWN), result)

        if ALPHA :

            alpha_blend = ImageChops.darker(sized_result, ALPHA)
            out = Image.alpha_composite(BG, alpha_blend)

        else :

            out = Image.alpha_composite(BG, sized_result)

        return out

    
    def main(self) :

        for i, file in enumerate(FOLDER):

            base_image = Image.open(file)

            ### COMMENT THESE LINES FOR FULL QUALITY (BUT SLOWER) RESULTS
            # current_thumb.thumbnail((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)
            # base_image = current_thumb.convert("RGBA")
            ###

            if not os.path.exists(PATH + "\\Fiches") :
                os.makedirs(PATH + "\\Fiches")
            
            print(f"{i+1} / {TOTAL} : Création du porte-clef")
            current_ID = self.combine_images(base_image, ID_LEFT, ID_UP, ID_RIGHT, ID_DOWN, ID, ID_ALPHA)
        
            print(f"{i+1} / {TOTAL} : Création de la boîte à tartine")
            current_boite = self.combine_images(base_image, BOITE_LEFT, BOITE_UP, BOITE_RIGHT, BOITE_DOWN, BOITE, BOITE_ALPHA, perspective=True, height_multiplier = 0.8)
        
            print(f"{i+1} / {TOTAL} : Création du cadre")
            current_cadre = self.combine_images(base_image, CADRE_LEFT, CADRE_UP, CADRE_RIGHT, CADRE_DOWN, CADRE, CADRE_ALPHA, orientation=True)
        
            print(f"{i+1} / {TOTAL} : Création du magnet")
            current_magnet = self.combine_images(base_image, MAGNET_LEFT, MAGNET_UP, MAGNET_RIGHT, MAGNET_DOWN, MAGNET, MAGNET_ALPHA)
        
            print(f"{i+1} / {TOTAL} : Création du mug")
            current_mug = self.combine_images(base_image, MUG_LEFT, MUG_UP, MUG_RIGHT, MUG_DOWN, MUG, MUG_ALPHA)
        
            print(f"{i+1} / {TOTAL} : Création du passe en carton")
            current_passe = self.combine_images(base_image, PASSE_LEFT, PASSE_UP, PASSE_RIGHT, PASSE_DOWN, PASSE, PASSE_ALPHA, orientation=True)
        
            print(f"{i+1} / {TOTAL} : Création du support en bois")
            current_bois = self.combine_images(base_image, BOIS_LEFT, BOIS_UP, BOIS_RIGHT, BOIS_DOWN, BOIS, BOIS_ALPHA, orientation=True)
        
            print(f"{i+1} / {TOTAL} : Création de la boule a neige")
            current_neige = self.combine_images(base_image, NEIGE_LEFT, NEIGE_UP, NEIGE_RIGHT, NEIGE_DOWN, NEIGE, NEIGE_ALPHA)
        
            # print(f"{i+1} / {TOTAL} : Création de la première carte de voeux")
            # current_voeux1 = self.combine_images(base_image, VOEUX_LEFT, VOEUX_UP, VOEUX_RIGHT, VOEUX_DOWN, VOEUX1, VOEUX_ALPHA, FIT=True)
        
            # print(f"{i+1} / {TOTAL} : Création de la seconde carte de voeux")
            # current_voeux2 = self.combine_images(base_image, VOEUX_LEFT, VOEUX_UP, VOEUX_RIGHT, VOEUX_DOWN, VOEUX2, VOEUX_ALPHA, FIT=True)
        
            print(f"{i+1} / {TOTAL} : Création du calendrier")
            current_calendrier = self.combine_images(base_image, CAL_LEFT, CAL_UP, CAL_RIGHT, CAL_DOWN, CAL, CAL_ALPHA, FIT=True)
            
            #######

            for side in FICHE :
                current_fiche = side

                if side == RECTO :
                    print("\nRECTO")
                    print(f"{i+1} / {TOTAL} : Placement du cadre")
                    current_fiche = self.combine_images(current_cadre, CADRE_THUMB_LEFT, THUMB_UP, CADRE_THUMB_LEFT+BIG_THUMB_SIZE, THUMB_UP+BIG_THUMB_SIZE, current_fiche, FIT=True)
                    
                    print(f"{i+1} / {TOTAL} : Placement du support en bois")
                    current_fiche = self.combine_images(current_bois, BOIS_THUMB_LEFT, THUMB_UP, BOIS_THUMB_LEFT+BIG_THUMB_SIZE, THUMB_UP+BIG_THUMB_SIZE, current_fiche, FIT=True)
                    
                    print(f"{i+1} / {TOTAL} : Placement du passe en carton")
                    current_fiche = self.combine_images(current_passe, PASSE_THUMB_LEFT, THUMB_UP, PASSE_THUMB_LEFT+BIG_THUMB_SIZE, THUMB_UP+BIG_THUMB_SIZE, current_fiche, FIT=True)
                    current_fiche = current_fiche.convert("RGB")
                    print("\n" + "-" * 32 + "\n")
                    print(f"{i+1} / {TOTAL} : Recto enregistré !")
                    print("-" * 32 + "\n")
                    current_fiche.save(f"{PATH}\\Fiches\\F_{os.path.splitext(file)[0]}_recto.jpg", format='JPEG', subsampling=0, quality=100)

                elif side == VERSO :
                    print("\nVERSO")
                    print(f"{i+1} / {TOTAL} : Placement de la boîte à tartines")
                    current_fiche = self.combine_images(current_boite, THUMB_LEFT, BOITE_THUMB_UP, THUMB_LEFT+THUMB_SIZE, BOITE_THUMB_UP+THUMB_SIZE, current_fiche)
                    
                    print(f"{i+1} / {TOTAL} : Placement du magnet")
                    current_fiche = self.combine_images(current_magnet, THUMB_LEFT, MAGNET_THUMB_UP, THUMB_LEFT+THUMB_SIZE, MAGNET_THUMB_UP+THUMB_SIZE, current_fiche)
                    
                    print(f"{i+1} / {TOTAL} : Placement du porte-clef")
                    current_fiche = self.combine_images(current_ID, THUMB_LEFT, ID_THUMB_UP, THUMB_LEFT+THUMB_SIZE, ID_THUMB_UP+THUMB_SIZE, current_fiche)
                    
                    print(f"{i+1} / {TOTAL} : Placement du mug")
                    current_fiche = self.combine_images(current_mug, THUMB_LEFT, MUG_THUMB_UP, THUMB_LEFT+THUMB_SIZE, MUG_THUMB_UP+THUMB_SIZE, current_fiche)
                    
                    print(f"{i+1} / {TOTAL} : Placement de la boule à neige")
                    current_fiche = self.combine_images(current_neige, THUMB_LEFT, NEIGE_THUMB_UP, THUMB_LEFT+THUMB_SIZE, NEIGE_THUMB_UP+THUMB_SIZE, current_fiche)
                    
                    print(f"{i+1} / {TOTAL} : Placement du calendrier")
                    current_fiche = self.combine_images(current_calendrier, THUMB_LEFT, CAL_THUMB_UP, THUMB_LEFT+THUMB_SIZE, CAL_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
                    
                    # print(f"{i+1} / {TOTAL} : Placement de la première carte de voeux")
                    # current_fiche = self.combine_images(current_voeux1, VOEUX1_THUMB_LEFT, VOEUX1_THUMB_UP, VOEUX1_THUMB_LEFT+THUMB_SIZE, VOEUX1_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
                    
                    # print(f"{i+1} / {TOTAL} : Placement de la seconde carte de voeux")
                    # current_fiche = self.combine_images(current_voeux2, VOEUX2_THUMB_LEFT, VOEUX2_THUMB_UP, VOEUX2_THUMB_LEFT+THUMB_SIZE, VOEUX2_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
                    current_fiche = current_fiche.convert("RGB")
                    print("\n" + "-" * 32 + "\n")
                    print(f"{i+1} / {TOTAL} : Verso enregistré !")
                    print("-" * 32 + "\n")
                    current_fiche.save(f"{PATH}\\Fiches\\F_{os.path.splitext(file)[0]}_verso.jpg", format='JPEG', subsampling=0, quality=100)
                
        print("Terminé !")
            

#############################################################
#                           MAIN                            #
#############################################################
if __name__ == '__main__':
    order = Order()
