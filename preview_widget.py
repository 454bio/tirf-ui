import io
import math
import socket
import struct
import time
import traceback
import sys
from functools import partial
from typing import Optional

import numpy as np
from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QPixmap
from PySide2.QtWidgets import QApplication, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout, QLabel, QSlider, QToolButton, QVBoxLayout, QWidget

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

    def __init__(self):
        super().__init__()

        self.sourceImage: Optional[Image.Image] = None

        self.graphicsScene = QGraphicsScene()
        self.graphicsView = QGraphicsView(self.graphicsScene)
        self.lastGraphicsPixmapItem: Optional[QGraphicsPixmapItem] = None

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
        self.zoomInButton.clicked.connect(partial(self.graphicsView.scale, 2.0, 2.0))
        self.zoomOutButton = QToolButton()
        self.zoomOutButton.setText("-")
        self.zoomOutButton.clicked.connect(partial(self.graphicsView.scale, 0.5, 0.5))

        adjustmentsLayout = QVBoxLayout()
        adjustmentsLayout.addWidget(self.whiteLevelSlider)
        adjustmentsLayout.addWidget(self.blackLevelSlider)
        adjustmentsLayout.addWidget(self.whiteLevelLabel)
        adjustmentsLayout.addWidget(self.blackLevelLabel)
        adjustmentsLayout.addWidget(self.zoomInButton)
        adjustmentsLayout.addWidget(self.zoomOutButton)
        adjustmentsWidget = QWidget()
        adjustmentsWidget.setLayout(adjustmentsLayout)

        mainLayout = QHBoxLayout()
        mainLayout.addWidget(self.graphicsView)
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

    @staticmethod
    def levelLogScale(x: int) -> int:
        # Chosen such that levelLogScale(65536) == 65536
        # TODO: Adjust the range based on the bit depth of the image
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
        # PIL only allows us to use a 16-bit LUT on 32-bit images.
        # It is sufficient to trick PIL into thinking this is 32-bit without actually doing the conversion, which can take up to 500ms.
        # `_point(ImagingObject *self, PyObject *args)` in PIL's _imaging.c describes LUT behavior.
        # This behavior is not documented, and should probably be patched upstream to something more reasonable.
        self.sourceImage.mode = "I"
        image = self.sourceImage.point(self.levelsLut, "L")

        # The image will have to be converted to 8-bit for Qt as well.
        # No need to do it again though.
        if self.lastGraphicsPixmapItem:
            self.graphicsScene.removeItem(self.lastGraphicsPixmapItem)
        self.lastGraphicsPixmapItem = self.graphicsScene.addPixmap(QPixmap.fromImage(ImageQt.ImageQt(image)))

if __name__ == "__main__":
    app = QApplication()
    previewWidget = PreviewWidget()

    if len(sys.argv) == 2:
        image = Image.open(sys.argv[1])
        previewWidget.showImage(image)

    previewWidget.show()
    sys.exit(app.exec_())
