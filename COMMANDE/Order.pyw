# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
## --> GUI
from PySide2 import QtCore, QtGui, QtWidgets
from Order_data.ui_main import Ui_MainWindow

## --> GLOBAL IMPORTS
import os
import sys
import re
from time import sleep
from PIL import Image, ImageFile, ImageDraw, ImageChops, ImageFont
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
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

Y_OFFSET = 4 ## Amount of offset to get people faces on the combined images.
PIXEL_SIZE = 720 ## Maximum pixel width if image is reduced before processing (line 321).

## Size and position of each element with their mask then on the order sheet.
## For this to work, the background image MUST have a bit of transparency !
## Here each backgroun have at least 1px thick transparent border (generally at the bottom)
############################################
###### FICHE ######
FICHE = Image.open(f"{PATH}\\Order_data\\FICHE.png")
WATERMARK = Image.open(f"{PATH}\\Order_data\\watermark.png")
THUMB_SIZE = 155 #px
ORDER_X = int(FICHE.width * 0.016)
ORDER_Y = int(FICHE.height * 0.94)
ORDER_FONT_SIZE = 50
ORDER_START = 1

BIG_THUMB_LEFT = int(FICHE.width * 0.34)
BIG_THUMB_UP = int(FICHE.height * 0.69)
BIG_THUMB_RIGHT = int(FICHE.width * 0.66)
BIG_THUMB_DOWN = int(FICHE.height * 0.98)

####### MUG #######
MUG = Image.open(f"{PATH}\\Order_data\\MUG.png")
MUG_ALPHA = Image.open(f"{PATH}\\Order_data\\MUG_ALPHA.png")
MUG_LEFT = 100
MUG_UP = 420
MUG_RIGHT = 1510
MUG_DOWN = 2080
MUG_THUMB_UP = int(FICHE.height * 0.45)
MUG_THUMB_LEFT = int(FICHE.width * 0.35)

####### CALENDRIER #######
CALENDRIER = Image.open(f"{PATH}\\Order_data\\CALENDRIER.png")
CALENDRIER_ALPHA = Image.open(f"{PATH}\\Order_data\\CALENDRIER_ALPHA.png")
CALENDRIER_LEFT = int(CALENDRIER.width * 0.03)
CALENDRIER_UP = int(CALENDRIER.height * 0.02)
CALENDRIER_RIGHT = int(CALENDRIER.width * 0.96)
CALENDRIER_DOWN = int(CALENDRIER.height * 0.42)
CALENDRIER_THUMB_UP = int(FICHE.height * 0.18)
CALENDRIER_THUMB_LEFT = int(FICHE.width * 0.675)

####### MAGNET #######
MAGNET = Image.open(f"{PATH}\\Order_data\\MAGNET_ROND.png")
MAGNET_ALPHA = Image.open(f"{PATH}\\Order_data\\MAGNET_ROND_ALPHA.png")
MAGNET_LEFT = 78
MAGNET_UP = 157
MAGNET_RIGHT = 1708
MAGNET_DOWN = 1634
MAGNET_THUMB_UP = int(FICHE.height * 0.15)
MAGNET_THUMB_LEFT = int(FICHE.width * 0.35)

####### PORTE-CLEF #######
ID = Image.open(f"{PATH}\\Order_data\\PORTE-CLEF.png")
ID_ALPHA = Image.open(f"{PATH}\\Order_data\\PORTE-CLEF_ALPHA.png")
ID_LEFT = 467
ID_UP = 451
ID_RIGHT = 1310
ID_DOWN = 1498
ID_THUMB_UP = int(FICHE.height * 0.3)
ID_THUMB_LEFT = int(FICHE.width * 0.35)

####### PLUMIER #######
PLUMIER = Image.open(f"{PATH}\\Order_data\\PLUMIER.png")
PLUMIER_ALPHA = Image.open(f"{PATH}\\Order_data\\PLUMIER_ALPHA.png")
PLUMIER_LEFT = 153
PLUMIER_UP = 302
PLUMIER_RIGHT = 1980
PLUMIER_DOWN = 734

####### CADRE #######
CADRE = Image.open(f"{PATH}\\Order_data\\CADRE.png")
CADRE_ALPHA = Image.open(f"{PATH}\\Order_data\\CADRE_ALPHA.png")
CADRE_LEFT = 575
CADRE_UP = 390
CADRE_RIGHT = 1585
CADRE_DOWN = 1800
CADRE_THUMB_UP = 1105
CADRE_THUMB_LEFT = 107

####### PASSE #######
PASSE = Image.open(f"{PATH}\\Order_data\\PASSE.png")
PASSE_ALPHA = Image.open(f"{PATH}\\Order_data\\PASSE_ALPHA.png")
PASSE_LEFT = 316
PASSE_UP = 541
PASSE_RIGHT = 1138
PASSE_DOWN = 1647
PASSE_THUMB_UP = 1916
PASSE_THUMB_LEFT = 107

####### SUPPORT_BOIS #######
BOIS = Image.open(f"{PATH}\\Order_data\\SUPPORT_BOIS.png")
BOIS_ALPHA = Image.open(f"{PATH}\\Order_data\\SUPPORT_BOIS_ALPHA.png")
BOIS_LEFT = 442
BOIS_UP = 442
BOIS_RIGHT = 1348
BOIS_DOWN = 1601
BOIS_THUMB_UP = 1510
BOIS_THUMB_LEFT = 107

####### BOULE A NEIGE #######
NEIGE = Image.open(f"{PATH}\\Order_data\\NEIGE.png")
NEIGE_ALPHA = Image.open(f"{PATH}\\Order_data\\NEIGE_ALPHA.png")
NEIGE_LEFT = 176
NEIGE_UP = 235
NEIGE_RIGHT = 1610
NEIGE_DOWN = 1483
NEIGE_THUMB_UP = int(FICHE.height * 0.1)
NEIGE_THUMB_LEFT = int(FICHE.width * 0.675)

####### VOEUX 01 #######
VOEUX01 = Image.open(f"{PATH}\\Order_data\\VOEUX01.png")
VOEUX01_ALPHA = Image.open(f"{PATH}\\Order_data\\VOEUX01_ALPHA.png")
VOEUX01_LEFT = 130
VOEUX01_UP = 118
VOEUX01_RIGHT = 1075
VOEUX01_DOWN = 1064
VOEUX01_THUMB_UP = int(FICHE.height * 0.25)
VOEUX01_THUMB_LEFT = int(FICHE.width * 0.675)

###### VOEUX 02 #######
VOEUX02 = Image.open(f"{PATH}\\Order_data\\VOEUX02.png")
VOEUX02_ALPHA = Image.open(f"{PATH}\\Order_data\\VOEUX02_ALPHA.png")
VOEUX02_LEFT = int(VOEUX02.width * 0.06)
VOEUX02_UP = int(VOEUX02.height * 0.09)
VOEUX02_RIGHT = int(VOEUX02.width * 0.94)
VOEUX02_DOWN = int(VOEUX02.height * 0.91)
VOEUX02_THUMB_UP = int(FICHE.height * 0.32)
VOEUX02_THUMB_LEFT = int(FICHE.width * 0.675)

# ####### GOURDE #######
# GOURDE = Image.open(f"{PATH}\\Order_data\\GOURDE.png")
# GOURDE_ALPHA = Image.open(f"{PATH}\\Order_data\\GOURDE_ALPHA.png")
# GOURDE_LEFT = 613
# GOURDE_UP = 910
# GOURDE_RIGHT = 1538
# GOURDE_DOWN = 2106
# GOURDE_THUMB_UP = int(FICHE.height * 0.2)
# GOURDE_THUMB_LEFT = int(FICHE.width * 0.675)

# ####### PORTEFEUILLE #######
# PORTEFEUILLE = Image.open(f"{PATH}\\Order_data\\PORTEFEUILLE.png")
# PORTEFEUILLE_ALPHA = Image.open(f"{PATH}\\Order_data\\PORTEFEUILLE_ALPHA.png")
# PORTEFEUILLE_LEFT = 280
# PORTEFEUILLE_UP = 534
# PORTEFEUILLE_RIGHT = 2023
# PORTEFEUILLE_DOWN = 1574
# PORTEFEUILLE_THUMB_UP = int(FICHE.height * 0.3)
# PORTEFEUILLE_THUMB_LEFT = int(FICHE.width * 0.675)


#############################################################
#                        GUI CLASS                          #
#############################################################
class Order(QtWidgets.QMainWindow):
    def __init__(self):
        QtWidgets.QMainWindow.__init__(self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        ## UI --> INTERFACE CODE
        ############################################

        ## REMOVE TITLE BAR
        self.setWindowFlag(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        ## DROP SHADOW EFFECT
        self.shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(21)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(0)
        self.shadow.setColor(QtGui.QColor(0, 0, 0, 64))
        self.ui.drop_shadow_frame.setGraphicsEffect(self.shadow)

        ## LABEL DESCRIPTION
        # self.ui.label_description.setText(f"Recadrage en <strong>{MAXSIZE[0]}</strong>px")

        ## LABEL COUNTER
        self.ui.label_counter.setText(f"<strong>{TOTAL}</strong> FICHIERS TROUVES")

        ## PROGRESS BAR
        self.ui.progressBar.setVisible(False)
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setMaximum(20)

        ## BUTTON
        # self.ui.pushButton.clicked.connect(lambda: self.main())
        self.ui.pushButton.clicked.connect(lambda: self.debug())
        self.ui.pushButton.setGraphicsEffect(self.shadow)

        ## NO FILES ?
        if TOTAL == 0 :
            self.no_files("Aucun fichier trouvé")
        
        ## SHOW --> MAIN WINDOW
        ############################################
        self.show()
        ## --> END

    ## --> APP FUNCTIONS
    ############################################
    def no_files(self, message):
        self.ui.pushButton.clicked.disconnect()

        self.ui.label_counter.setText(message)
        self.ui.pushButton.setText("Fermer")
        self.ui.pushButton.clicked.connect(lambda: self.close())

        self.ui.progressBar.setVisible(False)
        self.ui.pushButton.setVisible(True)


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
        ## ORIENTATION
        ##############
        if orientation == True :
            if IMAGE.width > IMAGE.height :
                    BG = BG.rotate(90, expand=True)
                    ALPHA = ALPHA.rotate(90, expand=True)

                    # There is probably a more efficient way to do this but it works. :D
                    temp_left = LEFT
                    temp_right = RIGHT
                    temp_up = UP
                    temp_down = DOWN
                    LEFT = temp_up
                    UP = temp_left
                    RIGHT = temp_down
                    DOWN = temp_right

        WIDTH = RIGHT - LEFT
        HEIGHT = DOWN - UP        
        
        result = Image.new('RGBA', (WIDTH, HEIGHT), (255, 255, 255, 0))

        ## FIT -IN
        ##############
        if FIT == True :
            cropped_image = IMAGE.resize((WIDTH, self.fit_in(WIDTH, IMAGE.width, IMAGE.height)), Image.LANCZOS)
            if cropped_image.height > HEIGHT :
                cropped_image = IMAGE.resize((self.fit_in(HEIGHT, IMAGE.height, IMAGE.width), HEIGHT), Image.LANCZOS)

        ## FILL-IN
        ##############
        else :
            cropped_image = IMAGE.resize((self.fit_in(HEIGHT, IMAGE.height, IMAGE.width), HEIGHT), Image.LANCZOS)
            if cropped_image.width < WIDTH :
                cropped_image = IMAGE.resize((WIDTH, self.fit_in(WIDTH, IMAGE.width, IMAGE.height)), Image.LANCZOS)

        ## PERSPECTIVE
        ##############
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

    def order_number(self, image, filename) :
        number_to_draw = ImageDraw.Draw(image)
        myFont = ImageFont.truetype(f"{PATH}\\Order_data\\Montserrat-Regular.ttf", ORDER_FONT_SIZE)
        number_to_draw.text((ORDER_X, ORDER_Y), filename, font=myFont, fill=(0, 0, 0))
        return image


    ## MAIN FUNCTION
    ############################################
    def main(self) :
        self.ui.progressBar.setVisible(True)
        self.ui.pushButton.setVisible(False)

        ## Create a new folder for the order sheets to be saved on.
        if not os.path.exists(PATH + "\\Fiches") :
                os.makedirs(PATH + "\\Fiches")

        for i, file in enumerate(FOLDER):
            base_image = Image.open(file)

            current_thumb = base_image

            ## --> COMMENT THIS LINE FOR FULL QUALITY (BUT SLOWER) RESULTS
            current_thumb.thumbnail((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)

            base_image = current_thumb.convert("RGBA")

            self.ui.progressBar.setValue(0)

            current_fiche = FICHE

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création miniature")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            if WATERMARK :
                current_thumb.paste(WATERMARK, WATERMARK)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création porte-clef")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_ID = self.combine_images(base_image, ID_LEFT, ID_UP, ID_RIGHT, ID_DOWN, ID, ID_ALPHA)
        
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création cadre")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_cadre = self.combine_images(base_image, CADRE_LEFT, CADRE_UP, CADRE_RIGHT, CADRE_DOWN, CADRE, CADRE_ALPHA, orientation=True)
        
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création magnet")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_magnet = self.combine_images(base_image, MAGNET_LEFT, MAGNET_UP, MAGNET_RIGHT, MAGNET_DOWN, MAGNET, MAGNET_ALPHA)
        
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création mug")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_mug = self.combine_images(base_image, MUG_LEFT, MUG_UP, MUG_RIGHT, MUG_DOWN, MUG, MUG_ALPHA)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création calendrier")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_cal = self.combine_images(base_image, CALENDRIER_LEFT, CALENDRIER_UP, CALENDRIER_RIGHT, CALENDRIER_DOWN, CALENDRIER, CALENDRIER_ALPHA, FIT=True)
        
            # self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création gourde") 
            # self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            # QtWidgets.QApplication.processEvents()
            # current_gourde = self.combine_images(base_image, GOURDE_LEFT, GOURDE_UP, GOURDE_RIGHT, GOURDE_DOWN, GOURDE, GOURDE_ALPHA, FIT=True)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création passe partout")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_passe = self.combine_images(base_image, PASSE_LEFT, PASSE_UP, PASSE_RIGHT, PASSE_DOWN, PASSE, PASSE_ALPHA, orientation=True)
        
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création support bois")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_bois = self.combine_images(base_image, BOIS_LEFT, BOIS_UP, BOIS_RIGHT, BOIS_DOWN, BOIS, BOIS_ALPHA, orientation=True)
        
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création boule a neige")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_neige = self.combine_images(base_image, NEIGE_LEFT, NEIGE_UP, NEIGE_RIGHT, NEIGE_DOWN, NEIGE, NEIGE_ALPHA)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création carte de voeux 01")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_voeux01 = self.combine_images(base_image, VOEUX01_LEFT, VOEUX01_UP, VOEUX01_RIGHT, VOEUX01_DOWN, VOEUX01, VOEUX01_ALPHA)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création carte de voeux 02")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_voeux02 = self.combine_images(base_image, VOEUX02_LEFT, VOEUX02_UP, VOEUX02_RIGHT, VOEUX02_DOWN, VOEUX02, VOEUX02_ALPHA)
        
            # self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création portefeuille")
            # self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            # QtWidgets.QApplication.processEvents()
            # current_portefeuille = self.combine_images(base_image, PORTEFEUILLE_LEFT, PORTEFEUILLE_UP, PORTEFEUILLE_RIGHT, PORTEFEUILLE_DOWN, PORTEFEUILLE, PORTEFEUILLE_ALPHA, FIT=True) 
        
            #######

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement cadre")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_cadre, CADRE_THUMB_LEFT, CADRE_THUMB_UP, CADRE_THUMB_LEFT+THUMB_SIZE, CADRE_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement support bois")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_bois, BOIS_THUMB_LEFT, BOIS_THUMB_UP, BOIS_THUMB_LEFT+THUMB_SIZE, BOIS_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement passe partout")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_passe, PASSE_THUMB_LEFT, PASSE_THUMB_UP, PASSE_THUMB_LEFT+THUMB_SIZE, PASSE_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement magnet")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_magnet, MAGNET_THUMB_LEFT, MAGNET_THUMB_UP, MAGNET_THUMB_LEFT+THUMB_SIZE, MAGNET_THUMB_UP+THUMB_SIZE, current_fiche)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement porte-clef")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_ID, ID_THUMB_LEFT, ID_THUMB_UP, ID_THUMB_LEFT+THUMB_SIZE, ID_THUMB_UP+THUMB_SIZE, current_fiche)
            
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement mug")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_mug, MUG_THUMB_LEFT, MUG_THUMB_UP, MUG_THUMB_LEFT+THUMB_SIZE, MUG_THUMB_UP+THUMB_SIZE, current_fiche)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement calendrier")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_cal, CALENDRIER_THUMB_LEFT, CALENDRIER_THUMB_UP, CALENDRIER_THUMB_LEFT+THUMB_SIZE, CALENDRIER_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
            
            # self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement gourde")
            # self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            # QtWidgets.QApplication.processEvents()
            # current_fiche = self.combine_images(current_gourde, GOURDE_THUMB_LEFT, GOURDE_THUMB_UP, GOURDE_THUMB_LEFT+THUMB_SIZE, GOURDE_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement boule à neige")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_neige, NEIGE_THUMB_LEFT, NEIGE_THUMB_UP, NEIGE_THUMB_LEFT+THUMB_SIZE, NEIGE_THUMB_UP+THUMB_SIZE, current_fiche)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement carte voeux 01")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_voeux01, VOEUX01_THUMB_LEFT, VOEUX01_THUMB_UP, VOEUX01_THUMB_LEFT+THUMB_SIZE, VOEUX01_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement carte voeux 02")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_voeux02, VOEUX02_THUMB_LEFT, VOEUX02_THUMB_UP, VOEUX02_THUMB_LEFT+THUMB_SIZE, VOEUX02_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)
            
            # self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement portefeuille")
            # self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            # QtWidgets.QApplication.processEvents()
            # current_fiche = self.combine_images(current_portefeuille, PORTEFEUILLE_THUMB_LEFT, PORTEFEUILLE_THUMB_UP, PORTEFEUILLE_THUMB_LEFT+THUMB_SIZE, PORTEFEUILLE_THUMB_UP+THUMB_SIZE, current_fiche, FIT=True)

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Placement miniature")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            current_fiche = self.combine_images(current_thumb, BIG_THUMB_LEFT, BIG_THUMB_UP, BIG_THUMB_RIGHT, BIG_THUMB_DOWN, current_fiche, FIT=True)
            
            current_fiche = current_fiche.convert("RGB")
            filename = os.path.splitext(file)[0]
            current_fiche = self.order_number(current_fiche, filename)
            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Enregistré !")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            QtWidgets.QApplication.processEvents()
            # current_fiche.show()
            current_fiche.save(f"{PATH}\\Fiches\\{filename}.jpg", format='JPEG', subsampling=0, quality=100)
            ORDER_START + 1

        self.no_files("Terminé")
    

    def debug(self):
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setMaximum(TOTAL)

        self.ui.progressBar.setVisible(True)
        self.ui.pushButton.setVisible(False)

        for i, file in enumerate(FOLDER):
            base_image = Image.open(file)

            current_thumb = base_image

            ### COMMENT THIS LINE FOR FULL QUALITY (BUT SLOWER) RESULTS
            # current_thumb.thumbnail((PIXEL_SIZE, PIXEL_SIZE), Image.LANCZOS)

            base_image = current_thumb.convert("RGBA")

            self.ui.label_counter.setText(f"{i+1} / {TOTAL} : Création en cours...")
            self.ui.progressBar.setValue(self.ui.progressBar.value() + 1)
            combined = self.combine_images(base_image, VOEUX02_LEFT, VOEUX02_UP, VOEUX02_RIGHT, VOEUX02_DOWN, VOEUX02, VOEUX02_ALPHA)
            combined = combined.convert("RGB")
            combined.save(f"{PATH}\\V_{os.path.splitext(file)[0]}.jpg", format='JPEG', subsampling=0, quality=100)
            # combined.show()

        self.no_files("Terminé")

#############################################################
#                           MAIN                            #
#############################################################
if __name__ == '__main__':
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication(sys.argv)
    order = Order()
    order.show() 
    sys.exit(app.exec_())
