# -*- coding: utf-8 -*-
#############################################################
#                          IMPORT                           #
#############################################################
from PyQt5 import QtCore, QtGui, QtWidgets
from itertools import cycle
from glob import glob
import os
import io
from PIL.ImageQt import ImageQt, Image, QImage
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

if not os.path.exists(PATH + f"\\CROPPED") :
    os.makedirs(PATH + f"\\CROPPED")

#############################################################
#                         CONTENT                           #
#############################################################
WIDTH_RATIO = 3
HEIGHT_RATIO = 2

DPI = 300

WIDTH = 0
HEIGHT = 0
WIDTH_DPI = 0
HEIGHT_DPI = 0

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)
ImageFile.LOAD_TRUNCATED_IMAGES = True

class ResizableRubberBand(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super(ResizableRubberBand, self).__init__(parent)
        self.draggable = True
        self.dragging_threshold = 5
        self.mousePressPos = None
        self.mouseMovePos = None
        self.borderRadius = 5

        self.setWindowFlags(QtCore.Qt.SubWindow)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(
            QtWidgets.QSizeGrip(self), 0,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        layout.addWidget(QtWidgets.QSizeGrip(self), 0,
                         QtCore.Qt.AlignRight | QtCore.Qt.AlignBottom)
        self.rubberband = QtWidgets.QRubberBand(
            QtWidgets.QRubberBand.Rectangle, self)

        self.rubberband.show()
        self.show()

    def resizeEvent(self, event):
        size = QtCore.QSize(WIDTH_RATIO, HEIGHT_RATIO)
        size.scale(self.size(), QtCore.Qt.KeepAspectRatio)
        self.resize(size)
        self.rubberband.resize(self.size())

    def paintEvent(self, event):
        # Get current window size
        window_size = self.size()
        qp = QtGui.QPainter()
        qp.begin(self)
        qp.setRenderHint(QtGui.QPainter.Antialiasing, True)
        qp.drawRoundedRect(0, 0, window_size.width(), window_size.height(),
                           self.borderRadius, self.borderRadius)
        qp.end()

    def mousePressEvent(self, event):
        if self.draggable and event.button() == QtCore.Qt.LeftButton:
            self.mousePressPos = event.globalPos()                # global
            self.mouseMovePos = event.globalPos() - self.pos()    # local
        super(ResizableRubberBand, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.draggable and event.buttons() & QtCore.Qt.LeftButton:
            globalPos = event.globalPos()
            moved = globalPos - self.mousePressPos
            if moved.manhattanLength() > self.dragging_threshold:
                # Move when user drag window more than dragging_threshold
                diff = globalPos - self.mouseMovePos
                self.move(diff)
                self.mouseMovePos = globalPos - self.pos()
        super(ResizableRubberBand, self).mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.mousePressPos is not None:
            if event.button() == QtCore.Qt.LeftButton:
                moved = event.globalPos() - self.mousePressPos
                if moved.manhattanLength() > self.dragging_threshold:
                    # Do not call click event or so on
                    event.ignore()
                self.mousePressPos = None
        super(ResizableRubberBand, self).mouseReleaseEvent(event)

    def getCoverage(self):
        localCoords = self.contentsRect()
        print("localCoords: ", localCoords)
        TL = self.mapToGlobal(localCoords.topLeft())
        BR = localCoords.bottomRight()
        # TL+BR to get width & height
        widgetCoords = QtCore.QRect(TL, TL+BR)
        print("widgetCoords: ", widgetCoords)
        return widgetCoords

class Label(QtWidgets.QLabel):
    def resizeEvent(self, event):
        if not hasattr(self, 'maximum_size'):
            self.maximum_size = self.size()
        else:
            self.maximum_size = QtCore.QSize(
                max(self.maximum_size.width(), self.width()),
                max(self.maximum_size.height(), self.height()),
            )
        super(Label, self).resizeEvent(event)

    def setPixmap(self, pixmap):
        scaled = pixmap.scaled(self.maximum_size, QtCore.Qt.KeepAspectRatio)
        super(Label, self).setPixmap(scaled)

class ImageManipulation():
    def __init__(self, x, y, w_r, h_r):
        WIDTH = x
        HEIGHT = y

    def correct_round(number) :
        if number  == 89 :
            number = 9
        
        elif number  == 127 :
            number = 13
        
        elif number  == 178 :
            number = 18

        else :
            number = int(number /10)

        return number

    def mm_to_pixels(mm) :
        return round((float(mm) / 25.4) * DPI)

    def fit_in(max_size, primary_size, secondary_size):
        primary_ratio = (max_size/float(primary_size))
        secondary_ratio = int((float(secondary_size)*float(primary_ratio)))
        return secondary_ratio

    WIDTH_DPI = mm_to_pixels(WIDTH)
    HEIGHT_DPI = mm_to_pixels(HEIGHT)
    WIDTH = correct_round(WIDTH)
    HEIGHT = correct_round(HEIGHT)

    NAME_SIZE = f"{HEIGHT}x{WIDTH}"

class Window(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowState(QtCore.Qt.WindowMaximized)
        layout = QtWidgets.QVBoxLayout(self)
        self.button_next = QtWidgets.QPushButton("Next image")
        self.button_crop = QtWidgets.QPushButton("Crop !")
        # self.button_10x15 = QtWidgets.QPushButton("10x15")
        self.label = Label()
        # self.label.setStyleSheet("QLabel { background-color : red; }")
        layout.addWidget(self.label)
        self.band = ResizableRubberBand(self.label)
        self.band.setGeometry(300, 300, 300, 200)
        layout.addWidget(self.button_next)
        layout.addWidget(self.button_crop)
        # layout.addWidget(self.button_10x15)
        self.button_next.clicked.connect(self.showImage)
        self.button_crop.clicked.connect(self.cropImage)
        # self.button_10x15.clicked.connect(lambda : self.band.resizeEvent(self, w=3, h=2))
        self.show()

    def showImage(self):
        try :
            self.filename = FOLDER.pop()
        except Exception :
            msg = QtWidgets.QMessageBox()
            msg.setIcon(QtWidgets.QMessageBox.Information)
            msg.setText("Terminé !")
            # msg.setInformativeText("Placez les images dans le même dossier.")
            msg.setWindowTitle("Studio C")
            msg.exec_()
            sys.exit(app.exec_())
        else :
            self.label.setPixmap(QtGui.QPixmap(self.filename))
            sp = self.label.sizePolicy()
            sp.setHorizontalPolicy(QtWidgets.QSizePolicy.Maximum)
            self.label.setSizePolicy(sp)
            self.layout().setAlignment(self.label, QtCore.Qt.AlignCenter)

    def cropImage(self):
        rect = self.band.getCoverage()
        r = QtCore.QRect(self.label.mapFromGlobal(rect.topLeft()), rect.size())
        px = self.label.pixmap()
        tr = QtGui.QTransform()
        tr.scale(px.size().width()*1.0/self.label.size().width(),
                 px.size().height()*1.0/self.label.size().height())
        r = tr.mapRect(r)
        self.label.setPixmap(px.copy(r))

        cropQPixmap = self.label.pixmap().copy()

        img = QtGui.QImage(cropQPixmap)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QBuffer.ReadWrite)
        img.save(buffer, "JPEG")
        pil_im = Image.open(io.BytesIO(buffer.data()))
        # result = ImageOps.fit(pil_im, WIDTH_DPI, HEIGHT_DPI))
        # result.save(f"{PATH}\\CROPPED\\{self.filename}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
        pil_im.save(f"{PATH}\\CROPPED\\{self.filename}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
        self.showImage()
        

if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    ex = Window()
    sys.exit(app.exec_())