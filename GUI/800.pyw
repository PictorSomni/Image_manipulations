# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
## --> GUI
from PySide6 import QtCore, QtGui, QtWidgets
from data.main_gui import Ui_MainWindow

## --> GLOBAL IMPORTS
import os
import sys
import re
from PIL import Image, ImageFile, ImageOps

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

file_name = re.search(r"(\d+)\s?\w?.py", sys.argv[0])

try :
    MAXSIZE = (int(file_name.group(1)), int(file_name.group(1)))
except Exception :
    input("Erreur : Le nom de l'executable doit être un nombre.")
    sys.exit()
else :
    EXTENSION = (".jpg", ".jpeg", ".png")
    FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
    TOTAL = len(FOLDER)

#############################################################
#                        GUI CLASS                          #
#############################################################
class GUI(QtWidgets.QMainWindow):
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
        self.ui.label_description.setText(f"Recadrage en <strong>{MAXSIZE[0]}</strong>px")

        ## CHECKBOX
        # self.ui.checkBox.setVisible(False)
        self.ui.checkBox.setText("Carré")

        ## LABEL COUNTER
        self.ui.label_counter.setText(f"<strong>{TOTAL}</strong> FICHIERS TROUVES")

        ## PROGRESS BAR
        self.ui.progressBar.setVisible(False)
        self.ui.progressBar.setValue(0)
        self.ui.progressBar.setMaximum(TOTAL)

        ## BUTTON
        self.ui.pushButton.clicked.connect(lambda: self.scale())
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

        self.ui.checkBox.setVisible(False)
        self.ui.progressBar.setVisible(False)
        self.ui.pushButton.setVisible(True)


    def scale(self):
        self.ui.checkBox.setVisible(False)
        self.ui.progressBar.setVisible(True)
        self.ui.pushButton.setVisible(False)

        ## Create a folder to save the new images to
        if not os.path.exists(PATH + f"/{MAXSIZE[0]}px") :
            os.makedirs(PATH + f"/{MAXSIZE[0]}px")

        ## The ENUMERATE function create a number associated to each element of a list
        ## which can ben used to count the number of elements in this case.
        for i, file in enumerate(FOLDER):
            self.ui.label_counter.setText(f"IMAGE <strong>{i+1}</strong> sur <strong>{TOTAL}</strong>")
            self.ui.progressBar.setValue(i+1)

            try:
                base_image = Image.open(file)
            except Exception:
                continue
            else:
                ## Square resized images
                if self.ui.checkBox.isChecked() :
                    result = ImageOps.fit(base_image, MAXSIZE)
                    result = result.convert("RGB")
                    result.save(f"{PATH}/{MAXSIZE[0]}px/{file}", dpi=(72, 72), format='JPEG', subsampling=0, quality=100)

                else :
                    ## Proportional resized images
                    base_image.thumbnail(MAXSIZE, Image.LANCZOS)
                    base_image = base_image.convert("RGB")
                    # base_image.save(f"{PATH}/{MAXSIZE[0]}px/{i:03}.jpg", dpi=(72, 72), format='JPEG', subsampling=0, quality=100)
                    base_image.save(f"{PATH}/{MAXSIZE[0]}px/{file}", dpi=(72, 72), format='JPEG', subsampling=0, quality=100)
        
        self.no_files("Terminé")

#############################################################
#                           MAIN                            #
#############################################################
if __name__ == "__main__":
    # QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    app = QtWidgets.QApplication(sys.argv)
    ui = GUI()
    sys.exit(app.exec_())