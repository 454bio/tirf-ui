from pathlib import Path
from typing import List
import math
import socket
import time
import traceback

import bitstruct

from PySide2.QtCore import Slot, QThread
from PySide2.QtWidgets import QGridLayout, QLabel, QWidget

PREVIEW_ROWS = 2
PREVIEW_COLS = 2

PREVIEW_HEADER_FORMAT = "u4u12u12u6u26"
PREVIEW_HEADER_SIZE = math.ceil(bitstruct.calcsize(PREVIEW_HEADER_FORMAT) / 8)

class PreviewThread(QThread):
    def __init__(self, socket_path: Path):
        super().__init__()
        self.socket_path = socket_path

    @Slot(None)
    def run(self):
        while True:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.connect(str(self.socket_path))
                    while True:
                        self.read_preview_bytes(s)
            except InterruptedError:
                break
            except:
                # Something went wrong with the preview socket. Let me know and wait a bit before trying again.
                traceback.print_exc()
                time.sleep(5)

    def read_preview_bytes(self, s: socket.socket) -> bytes:
        header = s.recv(PREVIEW_HEADER_SIZE)
        assert len(header) == PREVIEW_HEADER_SIZE

        (version, width, height, imageFormat, image_size) = bitstruct.unpack(PREVIEW_HEADER_FORMAT, header)
        assert version == 0

        image_bytes = bytearray()
        while len(image_bytes) < image_size:
            image_bytes.extend(s.recv(image_size - len(image_bytes)))

        return image_bytes

class PreviewWidget(QWidget):
    def __init__(self, previewPath: Path):
        super().__init__()

        # Set up UI...
        layout = QGridLayout()
        labels: List[QLabel] = []
        for i in range(PREVIEW_ROWS * PREVIEW_COLS):
            label = QLabel()
            label.setMinimumSize(250, 250)
            labels.append(label)
            layout.addWidget(label, i // PREVIEW_ROWS, i % PREVIEW_ROWS)

        self.setLayout(layout)

        self.socketThread = PreviewThread(previewPath)
        self.socketThread.start()
        # TODO: Connect this to the image labels somehow
