import json
import sys
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QTextBlock, QTextCursor, QTextBlockFormat
from PySide2.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QAction, QFileDialog

from sequencing_protocol import load_protocol_json, Event, RunContext, RunContextNode


PROTOCOLS_DIR = "protocols"
MARGIN_BETWEEN_EVENTS = 12

# TODO: Configuration: HAL path, output directory

class ProtocolThread(QThread):
    finished = Signal()
    error = Signal(tuple)
    progress = Signal(RunContext)

    def __init__(self):
        super().__init__()
        self.protocol: Optional[Event] = None

    @Slot(None)
    def run(self):
        try:
            # TODO: output dir and hal
            self.protocol.event_run_callback = self.eventRunCallback
            self.protocol.run(RunContext([RunContextNode(self.protocol)], Path("/tmp/foo"), None))
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.error.emit((exctype, value, traceback.format_exc()))
        finally:
            self.protocol.event_run_callback = None
            self.finished.emit()

    def eventRunCallback(self, context: RunContext):
        self.progress.emit(context)

class ProtocolViewer(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)

        self.eventTextBlocks: List[Tuple[QTextBlock, Optional[QTextBlock]]] = []

    def loadProtocol(self, protocol: Event):
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

    def progress(self, context: RunContext):
        print("Received context")
        # TODO: Display the context somehow
        # Can set a marker on the currently running block(s? maybe all of its parents too) with format.setMarker
        # Also need to mention iterations for each event that supports them
        pass

class SequencingUi(QMainWindow):
    def __init__(self):
        super().__init__()

        # Create the main elements...
        self.protocolThread = ProtocolThread()
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
        self.protocolThread.progress.connect(self.protocolViewer.progress)
        self.protocolThread.finished.connect(self.finished)
        # TODO: error
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
        self.protocolThread.terminate()

    def finished(self):
        self.startButton.setEnabled(True)

    def start(self):
        self.stopButton.setEnabled(True)
        self.startButton.setEnabled(False)
        self.protocolThread.start()

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open sequencing protocol", PROTOCOLS_DIR, "Sequencing protocols (*.454sp.json)")
        if not path:
            # Dialog closed
            return
        
        with open(path) as protocol_file:
            self.protocol, _ = load_protocol_json(json.load(protocol_file))

        self.protocolViewer.loadProtocol(self.protocol)
        self.protocolThread.protocol = self.protocol
        self.startButton.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SequencingUi()
    ui.show()
    sys.exit(app.exec_())
