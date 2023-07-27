import json
import sys
from typing import List, Optional, Tuple

from PySide2.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QAction, QFileDialog
from PySide2.QtGui import QTextBlock, QTextCursor, QTextBlockFormat

from sequencing_protocol import load_protocol_json, Event


PROTOCOLS_DIR = "protocols"
MARGIN_BETWEEN_EVENTS = 12

# TODO: Configuration: HAL path, output directory

class ProtocolViewer(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)

        self.eventTextBlocks: List[Tuple[QTextBlock, Optional[QTextBlock]]] = []

    def attachProtocol(self, protocol: Event):
        eventFormat = QTextBlockFormat()
        eventFormat.setTopMargin(MARGIN_BETWEEN_EVENTS)
        cursor = QTextCursor(self.document())
        self.eventTextBlocks = []
        for event in protocol:
            eventFormat.setIndent(event.protocol_depth)
            cursor.insertBlock(eventFormat)
            cursor.insertText(f"({event.readable_type}) {event.label}")
            eventBlock = cursor.block()

            detailsBlock: Optional[QTextBlock] = None
            details = event.gui_details()
            if details:
                detailsFormat = QTextBlockFormat()
                detailsFormat.setIndent(event.protocol_depth)
                cursor.insertBlock(detailsFormat)
                cursor.insertText(details)
                detailsBlock = cursor.block()

            self.eventTextBlocks.append((eventBlock, detailsBlock))

        # TODO: Register callbacks on the protocol to notify the viewer when it starts a new step
        # Can set a marker on the currently running block(s? maybe all of its parents too) with format.setMarker
        # Also need to mention iterations for each event that supports them

class SequencingUi(QMainWindow):
    def __init__(self):
        super().__init__()

        # Create the main elements...
        self.protocolViewer = ProtocolViewer()
        self.startButton = QPushButton()
        self.stopButton = QPushButton()
        self.openAction = QAction("&Open")
        self.settingsAction = QAction("S&ettings")

        # TODO: Estimated total time and estimated time remaining -- status bar

        # ...populate them ...
        self.startButton.setText("Start")
        self.stopButton.setText("Stop")

        # ... make them do stuff...
        self.openAction.triggered.connect(self.open)
        self.startButton.clicked.connect(self.start)
        self.stopButton.clicked.connect(self.stop)

        # ... and lay them out.
        mainWidget = QWidget()
        mainLayout = QVBoxLayout()
        mainWidget.setLayout(mainLayout)
        mainLayout.addWidget(self.protocolViewer)
        startStopWidget = QWidget()
        startStopLayout = QHBoxLayout()
        startStopWidget.setLayout(startStopLayout)
        startStopLayout.addWidget(self.startButton)
        startStopLayout.addWidget(self.stopButton)
        mainLayout.addWidget(startStopWidget)

        fileMenu = self.menuBar().addMenu("&File")
        fileMenu.addAction(self.openAction)
        fileMenu.addAction(self.settingsAction)

        self.setCentralWidget(mainWidget)

        self.setMinimumSize(550, 550)
        self.setWindowTitle("454 Sequencer")

        self.stop()
        self.startButton.setEnabled(False)

    def stop(self):
        self.stopButton.setEnabled(False)

        # TODO: If necessary, stop the currently running protocol

        self.startButton.setEnabled(True)

    def start(self):
        # TODO: Run the protocol
        # Do this in a new thread because it will block for a long time
        pass

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open sequencing protocol", PROTOCOLS_DIR, "Sequencing protocols (*.454sp.json)")
        if not path:
            # Dialog closed
            return
        
        with open(path) as protocol_file:
            self.protocol, _ = load_protocol_json(json.load(protocol_file))

        self.protocolViewer.attachProtocol(self.protocol)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SequencingUi()
    ui.show()
    sys.exit(app.exec_())
