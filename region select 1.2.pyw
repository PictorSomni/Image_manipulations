# -*- coding: utf-8 -*-
#############################################################
#                          IMPORT                           #
#############################################################
from PyQt5 import QtCore, QtGui, QtWidgets
import os
import io
from PIL.ImageQt import ImageQt, Image, QImage
from PIL import ImageOps

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

if not os.path.exists(PATH + f"\\WEB") :
    os.makedirs(PATH + f"\\WEB")

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]

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
        size = QtCore.QSize(1, 1)
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

class Window(QtWidgets.QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowState(QtCore.Qt.WindowMaximized)
        layout = QtWidgets.QVBoxLayout(self)
        self.next_button = QtWidgets.QPushButton("Next image")
        self.crop_button = QtWidgets.QPushButton("Crop !")
        self.label = Label()
        # self.label.setStyleSheet("QLabel { background-color : red; }")
        layout.addWidget(self.label)
        self.band = ResizableRubberBand(self.label)
        self.band.setGeometry(150, 150, 150, 150)
        layout.addWidget(self.next_button)
        layout.addWidget(self.crop_button)
        self.next_button.clicked.connect(self.showImage)
        self.crop_button.clicked.connect(self.cropImage)
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
        result = ImageOps.fit(pil_im, (800, 800))
        result.save(f"{PATH}\\WEB\\{self.filename}", dpi=(72, 72), format='JPEG', subsampling=0, quality=100)

        self.showImage()
        

if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    ex = Window()
    sys.exit(app.exec_())