from functools import partial
from pathlib import Path
from typing import List

import bitstruct

from PySide2.QtCore import QByteArray
from PySide2.QtNetwork import QLocalSocket
from PySide2.QtWidgets import QGridLayout, QLabel, QWidget

PREVIEW_ROWS = 2
PREVIEW_COLS = 2

# 1 MB. The header format supports up to 48 MB, but with the current settings each message will be around 200 KB.
MAX_MESSAGE_SIZE = 1 << 20

PREVIEW_HEADER_FORMAT = "u4u12u12u6u26"

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

        # ... set up socket events....
        self.socket = QLocalSocket(self)
        # TODO: This is not letting me set this correctly
        self.socket.setReadBufferSize(MAX_MESSAGE_SIZE)
        self.socket.readyRead.connect(self.readPreviewMessage)
        self.socket.disconnected.connect(partial(self.connectSocket, previewPath))

        # ... and actually connect to the socket.
        self.connectSocket(previewPath)

    def connectSocket(self, socketPath):
        self.socket.connectToServer(str(socketPath))

    def readPreviewMessage(self):
        # TODO: Why are we only getting 8192 bytes?
        # Try to figure out how to get the whole thing at once.
        message: QByteArray = self.socket.readAll()
        print(len(message))  # XXX

        (version, width, height, imageFormat, bufferSize) = bitstruct.unpack(PREVIEW_HEADER_FORMAT, message.data())
        print(version, width, height, imageFormat, bufferSize)  # XXX

        # TODO: Create the QImage
        # TODO: Paint it on one of the labels (which one?)
