from pathlib import Path
from typing import List
import math
import socket
import time
import traceback

import bitstruct

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QImage, QPixmap
from PySide2.QtWidgets import QGridLayout, QLabel, QWidget

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
    def __init__(self, rows: int = PREVIEW_ROWS, cols: int = PREVIEW_COLS):
        super().__init__()

        self.rows = rows
        self.cols = cols
        self.frame = 0

        # Set up UI...
        layout = QGridLayout()
        self.labels: List[QLabel] = []
        for i in range(self.rows * self.cols):
            label = QLabel()
            # TODO: Size?
            label.setMinimumSize(253, 190)
            self.labels.append(label)
            layout.addWidget(label, i // self.rows, i % self.cols)

        self.setLayout(layout)

    def connectToHal(self, previewAddress: str, previewPort: int):
        self.socketThread = PreviewThread(previewAddress, previewPort)
        self.socketThread.received_image.connect(self.showImage)
        self.socketThread.start()

    @Slot(QImage)
    def showImage(self, image: QImage):
        label = self.labels[self.frame % (self.rows * self.cols)]
        label.setPixmap(QPixmap.fromImage(image))
        self.frame += 1
