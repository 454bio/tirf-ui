import io
import math
import socket
import struct
import time
import traceback
import sys
from functools import partial
from typing import Optional, Tuple

import numpy as np
from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QImage, QPixmap
from PySide2.QtWidgets import QApplication, QHBoxLayout, QLabel, QScrollArea, QScrollBar, QSlider, QToolButton, QVBoxLayout, QWidget

from pil_wrapper import Image, ImageQt

def align_ceil_32(unaligned: int):
    return math.ceil(unaligned / 32) * 32

class PreviewThread(QThread):
    received_image = Signal(Image.Image)

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

    def read_preview_image(self, s: socket.socket) -> Image.Image:
        image_size_bytes = s.recv(4)  # 1 uint32_t
        (image_size,) = struct.unpack("I", image_size_bytes)

        image_bytes = bytearray()
        while len(image_bytes) < image_size:
            image_bytes.extend(s.recv(image_size - len(image_bytes)))

        return Image.open(io.BytesIO(image_bytes))

class PreviewWidget(QWidget):
    DEFAULT_MIN_LEVEL = 0
    DEFAULT_MAX_LEVEL = (1 << 16) - 1
    ZOOM_LEVELS = [10, 25, 50, 75, 100, 200, 300, 400]

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
        self.whiteLevelLabel = QLabel()
        levelLabelFont = self.whiteLevelLabel.font()
        levelLabelFont.setPointSize(6)
        self.whiteLevelLabel.setFont(levelLabelFont)
        self.blackLevelLabel = QLabel()
        self.blackLevelLabel.setFont(levelLabelFont)
        self.levelsLut = np.fromiter(map(lambda x: x >> 8, range(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL+1)), dtype=np.uint8)
        self.whiteLevelSlider = QSlider()
        self.whiteLevelSlider.setRange(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL)
        self.whiteLevelSlider.setValue(self.DEFAULT_MAX_LEVEL)
        self.blackLevelSlider = QSlider()
        self.blackLevelSlider.setRange(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL)
        self.blackLevelSlider.setValue(self.DEFAULT_MIN_LEVEL)
        self.whiteLevelSlider.sliderMoved.connect(self.adjustColors)
        self.blackLevelSlider.sliderMoved.connect(self.adjustColors)

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
        adjustmentsLayout.addWidget(self.whiteLevelLabel)
        adjustmentsLayout.addWidget(self.blackLevelLabel)
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
        self.socketThread = PreviewThread(previewAddress, previewPort)
        self.socketThread.received_image.connect(self.showImage)
        self.socketThread.start()

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

    @staticmethod
    def levelLogScale(x: int) -> int:
        # Chosen such that levelLogScale(65536) == 65536
        return int(2 ** (x / 4096))

    @Slot(None)
    def adjustColors(self):
        # PIL does not allow most types of basic arithmetic on anything other than 8-bit images.
        # For something as basic as thresholding, it requires lookup tables (?!)
        # `class _E` in PIL's Image.py describes the arithemtic supported inside `eval` or `point` on these supposedly "exotic" images.
        # `def point(` inside `class Image` in PIL's Image.py partially acknowledges this limitation with the following comment:
        # "I think this prevents us from ever doing a gamma function on > 8bit images."
        # This behavior is not documented, and should probably be patched upstream to something more reasonable.

        # This function creates such a lookup table using the values from the level sliders.
        blackLevel = self.levelLogScale(self.blackLevelSlider.value())
        self.blackLevelLabel.setText(str(blackLevel))
        whiteLevel = self.levelLogScale(self.whiteLevelSlider.value())
        self.whiteLevelLabel.setText(str(whiteLevel))
        colorScale = (self.DEFAULT_MAX_LEVEL - self.DEFAULT_MIN_LEVEL) / (whiteLevel - blackLevel)

        # Create the base lookup table...
        levelsLut16 = np.arange(self.DEFAULT_MIN_LEVEL, self.DEFAULT_MAX_LEVEL+1, dtype=np.uint16)
        # ... clamp within the set levels...
        levelsLut16[levelsLut16 < blackLevel] = blackLevel
        levelsLut16[levelsLut16 > whiteLevel] = whiteLevel
        # ... scale it...
        levelsLut16 = (levelsLut16 - blackLevel) * colorScale
        # ... and finally convert to the 8-bit output format.
        self.levelsLut = (levelsLut16 / (1 << 8)).astype(np.uint8)

        self.drawImage()

    def drawImage(self):
        if self.sourceImage is None:
            return
        
        # Apply recoloring.
        # PIL only allows us to use a 16-bit LUT by first converting to a 32-bit image (?!)
        # `_point(ImagingObject *self, PyObject *args)` in PIL's _imaging.c describes LUT behavior.
        # This behavior is not documented, and should probably be patched upstream to something more reasonable.
        image = self.sourceImage.convert("I").point(self.levelsLut, "L")

        currentZoomLevel = int(self.zoomLevelLabel.text().strip("%"))
        zoomedSize: Tuple[int, int] = tuple(int(currentZoomLevel / 100 * x) for x in image.size)
        image = image.resize(zoomedSize, Image.NEAREST)

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
