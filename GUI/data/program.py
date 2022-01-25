# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
## --> GUI
from PySide2 import QtCore, QtGui, QtWidgets
from data.main_gui import Ui_MainWindow

## --> GLOBAL IMPORTS
import os
import sys
import re

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################


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
        self.shadow.setBlurRadius(20)
        self.shadow.setXOffset(0)
        self.shadow.setYOffset(0)
        self.shadow.setColor(QtGui.QColor(0, 0, 0, 60))
        self.ui.drop_shadow_frame.setGraphicsEffect(self.shadow)

        ## LABEL DESCRIPTION


        ## LABEL COUNTER


        ## PROGRESS BAR


        ## CHECKBOX


        ## BUTTON


        ## SHOW --> MAIN WINDOW
        ############################################
        self.show()
        ## --> END

    ## --> APP FUNCTIONS
    ############################################
    

#############################################################
#                           MAIN                            #
#############################################################
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    ui = GUI()
    sys.exit(app.exec_())