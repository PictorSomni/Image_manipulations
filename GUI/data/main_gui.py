# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'main_gui modernCajVzT.ui'
##
## Created by: Qt User Interface Compiler version 5.15.1
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        if not MainWindow.objectName():
            MainWindow.setObjectName(u"MainWindow")
        MainWindow.resize(640, 643)
        self.centralwidget = QWidget(MainWindow)
        self.centralwidget.setObjectName(u"centralwidget")
        self.verticalLayout = QVBoxLayout(self.centralwidget)
        self.verticalLayout.setSpacing(0)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(13, 13, 13, 13)
        self.drop_shadow_frame = QFrame(self.centralwidget)
        self.drop_shadow_frame.setObjectName(u"drop_shadow_frame")
        font = QFont()
        font.setFamily(u"Montserrat SemiBold")
        self.drop_shadow_frame.setFont(font)
        self.drop_shadow_frame.setStyleSheet(u"QFrame {\n"
"	background-color: #D1D8E0;\n"
"	border-radius: 307px;\n"
"}")
        self.drop_shadow_frame.setFrameShape(QFrame.NoFrame)
        self.drop_shadow_frame.setFrameShadow(QFrame.Raised)
        self.label_description = QLabel(self.drop_shadow_frame)
        self.label_description.setObjectName(u"label_description")
        self.label_description.setGeometry(QRect(30, 230, 551, 61))
        font1 = QFont()
        font1.setFamily(u"Equinox Regular")
        font1.setPointSize(16)
        font1.setBold(False)
        self.label_description.setFont(font1)
        self.label_description.setStyleSheet(u"color:  #4B6584;\n"
"background-color: rgba(255, 255, 255, 0);")
        self.label_description.setText(u"<span >Recadrage en <strong>800</strong>PX</span>")
        self.label_description.setAlignment(Qt.AlignCenter)
        self.progressBar = QProgressBar(self.drop_shadow_frame)
        self.progressBar.setObjectName(u"progressBar")
        self.progressBar.setGeometry(QRect(130, 410, 351, 61))
        font2 = QFont()
        font2.setFamily(u"Equinox Bold")
        font2.setPointSize(13)
        self.progressBar.setFont(font2)
        self.progressBar.setStyleSheet(u"QProgressBar {\n"
"	height: 32px;\n"
"	background-color: #4B6584;\n"
"	color: #D1D8E0;\n"
"	border-style: none;\n"
"	border-radius: 30px;\n"
"	text-align: center;\n"
"}\n"
"QProgressBar::chunk {\n"
"	background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0  #A05CFC, stop:1 #D65CFC);\n"
"	border-radius: 30px;\n"
"}")
        self.progressBar.setValue(64)
        self.label_counter = QLabel(self.drop_shadow_frame)
        self.label_counter.setObjectName(u"label_counter")
        self.label_counter.setGeometry(QRect(100, 490, 411, 41))
        self.label_counter.setFont(font1)
        self.label_counter.setStyleSheet(u"color: #a254f2;")
        self.label_counter.setText(u"En cours...")
        self.label_counter.setAlignment(Qt.AlignCenter)
        self.pushButton = QPushButton(self.drop_shadow_frame)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(130, 410, 351, 61))
        font3 = QFont()
        font3.setFamily(u"Equinox Bold")
        font3.setPointSize(16)
        self.pushButton.setFont(font3)
        self.pushButton.setStyleSheet(u"QPushButton {\n"
"	border-radius: 30px;\n"
"	background-color: #D1D8E0;\n"
"	border: 2px solid #00c3ff;\n"
"	color: #4B6584;\n"
"	text-align: center;\n"
"}\n"
"QPushButton:hover {\n"
"	border: 2px solid #a254f2;\n"
"}\n"
"QPushButton:pressed {\n"
"	color: #F50B9A;\n"
"	border: 2px solid #F50B9A;\n"
"}")
        self.pushButton.setText(u"D\u00e9marrer")
        self.checkBox = QCheckBox(self.drop_shadow_frame)
        self.checkBox.setObjectName(u"checkBox")
        self.checkBox.setGeometry(QRect(210, 340, 181, 41))
        font4 = QFont()
        font4.setFamily(u"Equinox Regular")
        font4.setPointSize(16)
        self.checkBox.setFont(font4)
        self.checkBox.setStyleSheet(u"QCheckBox {\n"
"    border-radius: 20px;\n"
"    padding-left: 13px;\n"
"    min-width: 6em;\n"
"	background-color: #D1D8E0;\n"
"	border: 2px solid #778CA3;\n"
"	color: #4B6584;\n"
"	text-align: center;\n"
"}\n"
"QCheckBox:hover {\n"
"	border: 2px solid #00c3ff;\n"
"}\n"
"QCheckBox:checked {\n"
"	border: 2px solid #a254f2;\n"
"	color: #a254f2;\n"
"}")
        self.label_description_2 = QLabel(self.drop_shadow_frame)
        self.label_description_2.setObjectName(u"label_description_2")
        self.label_description_2.setGeometry(QRect(70, 170, 471, 91))
        font5 = QFont()
        font5.setFamily(u"Equinox Regular")
        font5.setPointSize(42)
        font5.setBold(False)
        self.label_description_2.setFont(font5)
        self.label_description_2.setStyleSheet(u"color:  #00c3ff;\n"
"background-color: rgba(255, 255, 255, 0);")
        self.label_description_2.setText(u"Studio <strong>C</strong>")
        self.label_description_2.setAlignment(Qt.AlignCenter)

        self.verticalLayout.addWidget(self.drop_shadow_frame)

        MainWindow.setCentralWidget(self.centralwidget)

        self.retranslateUi(MainWindow)

        QMetaObject.connectSlotsByName(MainWindow)
    # setupUi

    def retranslateUi(self, MainWindow):
        MainWindow.setWindowTitle(QCoreApplication.translate("MainWindow", u"MainWindow", None))
        self.checkBox.setText(QCoreApplication.translate("MainWindow", u"CheckBox", None))
    # retranslateUi

