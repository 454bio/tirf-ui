import math
import socket
import time
import traceback
import sys
from functools import partial
from typing import Optional, Tuple

import bitstruct

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QImage, QPixmap
from PySide2.QtWidgets import QApplication, QHBoxLayout, QLabel, QScrollArea, QScrollBar, QSlider, QStyle, QToolButton, QVBoxLayout, QWidget

from pil_wrapper import Image, ImageQt

PREVIEW_HEADER_FORMAT = "u4u12u12u6u26"
PREVIEW_HEADER_SIZE = math.ceil(bitstruct.calcsize(PREVIEW_HEADER_FORMAT) / 8)

def align_ceil_32(unaligned: int):
    return math.ceil(unaligned / 32) * 32

class PreviewThread(QThread):
    # TODO: This needs to emit a PIL image instead
    received_image = Signal(QImage)

    def __init__(self, address: str, port: int):
        super().__init__()
        self.address = address
        self.port = port

    @Slot(None)
    def run(self):
        while True:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.connect((self.address, self.port))
                    while True:
                        image = self.read_preview_image(s)
                        self.received_image.emit(image)

            except InterruptedError:
                break
            except:
                # Something went wrong with the preview socket. Let me know and wait a bit before trying again.
                traceback.print_exc()
                time.sleep(5)

    def read_preview_image(self, s: socket.socket) -> QImage:
        # TODO: This could be simplified if the HAL just outputs the TIFF format directly
        header = s.recv(PREVIEW_HEADER_SIZE)
        assert len(header) == PREVIEW_HEADER_SIZE

        (version, width, height, imageFormat, image_size) = bitstruct.unpack(PREVIEW_HEADER_FORMAT, header)
        assert version == 0

        image_bytes = bytearray()
        while len(image_bytes) < image_size:
            image_bytes.extend(s.recv(image_size - len(image_bytes)))

        # TODO: QImage segfaults here sometimes (?!)
        # TODO: Return a PIL image instead
        return QImage(image_bytes, width, height, align_ceil_32(width*3), QImage.Format(imageFormat))

class PreviewWidget(QWidget):
    DEFAULT_MIN_LEVEL = 0
    DEFAULT_MAX_LEVEL = 1 << 8
    ZOOM_LEVELS = [10, 25, 50, 100, 200, 300, 400]

    def __init__(self):
        super().__init__()

        self.sourceImage: Optional[Image.Image] = None

        # The image itself
        self.label = QLabel()
        self.scrollArea = QScrollArea()
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setWidget(self.label)

        # Keep scroll relative position across resizes
        self.lastRanges = [(0,0), [0,0]]  # [(horizontal min and max), (vertical min and max)]
        horizontalScrollBar = self.scrollArea.horizontalScrollBar()
        horizontalScrollBar.rangeChanged.connect(partial(self.keepRelativeScrollPosition, horizontalScrollBar, 0))
        verticalScrollBar = self.scrollArea.verticalScrollBar()
        horizontalScrollBar.rangeChanged.connect(partial(self.keepRelativeScrollPosition, verticalScrollBar, 1))

        # Levels adjustment
        self.whiteLevelSlider = QSlider()
        self.whiteLevelSlider.setRange(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL)
        self.whiteLevelSlider.setValue(self.DEFAULT_MAX_LEVEL)
        self.blackLevelSlider = QSlider()
        self.blackLevelSlider.setRange(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL)
        self.blackLevelSlider.setValue(self.DEFAULT_MIN_LEVEL)
        self.whiteLevelSlider.sliderMoved.connect(self.drawImage)
        self.blackLevelSlider.sliderMoved.connect(self.drawImage)

        # Zoom controls
        # TODO: Keyboard shortcuts?
        self.zoomInButton = QToolButton()
        self.zoomInButton.setText("+")
        self.zoomInButton.clicked.connect(partial(self.adjustZoom, True))
        self.zoomOutButton = QToolButton()
        self.zoomOutButton.setText("-")
        self.zoomOutButton.clicked.connect(partial(self.adjustZoom, False))
        self.zoomLevelLabel = QLabel("50%")
        zoomLabelFont = self.zoomLevelLabel.font()
        zoomLabelFont.setPointSize(8)
        self.zoomLevelLabel.setFont(zoomLabelFont)

        adjustmentsLayout = QVBoxLayout()
        adjustmentsLayout.addWidget(self.whiteLevelSlider)
        adjustmentsLayout.addWidget(self.blackLevelSlider)
        adjustmentsLayout.addWidget(self.zoomInButton)
        adjustmentsLayout.addWidget(self.zoomOutButton)
        adjustmentsLayout.addWidget(self.zoomLevelLabel)
        adjustmentsWidget = QWidget()
        adjustmentsWidget.setLayout(adjustmentsLayout)

        mainLayout = QHBoxLayout()
        mainLayout.addWidget(self.scrollArea)
        mainLayout.addWidget(adjustmentsWidget)

        self.setLayout(mainLayout)

    def connectToHal(self, previewAddress: str, previewPort: int):
        # self.socketThread.received_image needs to emit PIL image instead first
        # self.socketThread = PreviewThread(previewAddress, previewPort)
        # self.socketThread.received_image.connect(self.showImage)
        # self.socketThread.start()
        raise NotImplementedError

    @Slot(Image.Image)
    def showImage(self, image: Image.Image):
        self.sourceImage = image
        self.drawImage()

    def keepRelativeScrollPosition(self, scrollBar: QScrollBar, whichRange: int, newMin: int, newMax: int):
        oldMin = self.lastRanges[whichRange][0]
        oldMax = self.lastRanges[whichRange][1]
        oldSize = oldMax - oldMin

        try:
            relativePosition = (scrollBar.value() - oldMin) / oldSize

            newSize = newMax - newMin
            scrollBar.setValue(int(relativePosition * newSize + newMin))
        except ZeroDivisionError:
            # On initialization everything is zero. That's okay.
            pass
        finally:
            self.lastRanges[whichRange] = (newMin, newMax)

    @Slot(bool)
    def adjustZoom(self, zoomIn: bool):
        currentZoomLevel = int(self.zoomLevelLabel.text().strip("%"))
        currentZoomIndex = self.ZOOM_LEVELS.index(currentZoomLevel)
        targetZoomIndex = currentZoomIndex + (1 if zoomIn else -1)

        if targetZoomIndex+1 >= len(self.ZOOM_LEVELS):
            self.zoomInButton.setEnabled(False)
            self.zoomOutButton.setEnabled(True)
        elif targetZoomIndex-1 < 0:
            self.zoomInButton.setEnabled(True)
            self.zoomOutButton.setEnabled(False)
        else:
            self.zoomInButton.setEnabled(True)
            self.zoomOutButton.setEnabled(True)

        targetZoomLevel = self.ZOOM_LEVELS[targetZoomIndex]
        self.zoomLevelLabel.setText(f"{targetZoomLevel}%")

        self.drawImage()

    def drawImage(self):
        if self.sourceImage is None:
            return
        
        # PIL doesn't let us threshold anything other than 8-bit images, so we have to convert *first*.
        # This unfortunately results in a poorer quality preview and makes it so limit values that don't directly map to the output images.
        # We also need to do our own 16 to 8 bit scaling.
        image = Image.eval(self.sourceImage, lambda x: x / self.DEFAULT_MAX_LEVEL).convert("L")

        # Apply recoloring
        blackLevel = self.blackLevelSlider.value()
        whiteLevel = self.whiteLevelSlider.value()
        colorScale = (self.DEFAULT_MAX_LEVEL - self.DEFAULT_MIN_LEVEL) / (whiteLevel - blackLevel)
        def recolor(val: int) -> int:
            val = max(val, blackLevel)
            val = min(val, whiteLevel)
            val = int((val - blackLevel) * colorScale)
            return val
        image = Image.eval(image, recolor)

        currentZoomLevel = int(self.zoomLevelLabel.text().strip("%"))
        zoomedSize: Tuple[int, int] = tuple(int(currentZoomLevel / 100 * x) for x in image.size)
        image = image.resize(zoomedSize)

        # The image will have to be converted to 8-bit for Qt as well.
        # No need to do it again though.
        self.label.setPixmap(QPixmap.fromImage(ImageQt.ImageQt(image)))

if __name__ == "__main__":
    app = QApplication()
    previewWidget = PreviewWidget()

    if len(sys.argv) == 2:
        image = Image.open(sys.argv[1])
        previewWidget.showImage(image)

    previewWidget.show()
    sys.exit(app.exec_())
