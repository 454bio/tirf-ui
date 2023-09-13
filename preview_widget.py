import math
import socket
import time
import traceback
import sys

import bitstruct

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QImage, QPixmap
from PySide2.QtWidgets import QApplication, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

PREVIEW_ROWS = 2
PREVIEW_COLS = 2

PREVIEW_HEADER_FORMAT = "u4u12u12u6u26"
PREVIEW_HEADER_SIZE = math.ceil(bitstruct.calcsize(PREVIEW_HEADER_FORMAT) / 8)

def align_ceil_32(unaligned: int):
    return math.ceil(unaligned / 32) * 32

class PreviewThread(QThread):
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
        header = s.recv(PREVIEW_HEADER_SIZE)
        assert len(header) == PREVIEW_HEADER_SIZE

        (version, width, height, imageFormat, image_size) = bitstruct.unpack(PREVIEW_HEADER_FORMAT, header)
        assert version == 0

        image_bytes = bytearray()
        while len(image_bytes) < image_size:
            image_bytes.extend(s.recv(image_size - len(image_bytes)))

        return QImage(image_bytes, width, height, align_ceil_32(width*3), QImage.Format(imageFormat))

class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()

        # The image itself
        self.label = QLabel()
        # TODO: Size? It will automatically be resized once some images come
        self.label.setMinimumSize(1014, 760)

        # Image adjustments
        whiteLevelSlider = QSlider()
        blackLevelSlider = QSlider()
        levelsLayout = QVBoxLayout()
        levelsLayout.addWidget(whiteLevelSlider)
        levelsLayout.addWidget(blackLevelSlider)
        levelsWidget = QWidget()
        levelsWidget.setLayout(levelsLayout)

        mainLayout = QHBoxLayout()
        mainLayout.addWidget(self.label)
        mainLayout.addWidget(levelsWidget)

        self.setLayout(mainLayout)

    def connectToHal(self, previewAddress: str, previewPort: int):
        self.socketThread = PreviewThread(previewAddress, previewPort)
        self.socketThread.received_image.connect(self.showImage)
        self.socketThread.start()

    @Slot(QImage)
    def showImage(self, image: QImage):
        self.label.setPixmap(QPixmap.fromImage(image))

if __name__ == "__main__":
    app = QApplication()
    previewWidget = PreviewWidget()
    # TODO: Load a QImage from somewhere (path from argv?) and pass it showImage
    previewWidget.show()
    sys.exit(app.exec_())
