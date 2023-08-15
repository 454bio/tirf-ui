import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QTextBlock, QTextCursor, QTextBlockFormat, QTextCharFormat, QFont
from PySide2.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QAction, QFileDialog, QErrorMessage

from preview import PreviewWidget
from sequencing_protocol import load_protocol_json, Event, RunContext, RunContextNode, Hal

WINDOW_TITLE_BASE = "454 Sequencer"
PROTOCOLS_DIR = "protocols"
MARGIN_BETWEEN_EVENTS = 12

# TODO: Make these configurable
HAL_PATH: Optional[Path] = Path().home() / "454" / "socket"
PREVIEW_PATH: Optional[Path] = Path().home() / "454" / "preview"
OUTPUT_DIR_ROOT = Path.home() / "454"/ "output"

MOCK_WARNING_TEXT = f"No HAL at {HAL_PATH}, running in mock mode"

class ProtocolThread(QThread):
    finished = Signal()
    error = Signal(tuple)
    progress = Signal(RunContext)

    def __init__(self):
        super().__init__()
        self.protocol: Optional[Event] = None
        self.hal: Optional[Hal] = None

        # Create the HAL iff there's a socket we can connect to.
        # Otherwise, run in mock mode.
        if HAL_PATH is not None and HAL_PATH.is_socket():
            self.hal = Hal(str(HAL_PATH))

    @Slot(None)
    def run(self):
        protocol = self.protocol
        output_dir = OUTPUT_DIR_ROOT / datetime.now().isoformat()
        if protocol is not None:
            try:
                protocol.event_run_callback = self.eventRunCallback
                protocol.run(RunContext([RunContextNode(protocol)], output_dir, self.hal, self))
            except:
                traceback.print_exc()
                exctype, value = sys.exc_info()[:2]
                self.error.emit((exctype, value, traceback.format_exc()))
            finally:
                if self.hal is not None:
                    try:
                        self.hal.disable_heater()
                    except:
                        traceback.print_exc()
                        exctype, value = sys.exc_info()[:2]
                        self.error.emit((exctype, value, traceback.format_exc()))
                protocol.event_run_callback = None
                self.finished.emit()

    def eventRunCallback(self, context: RunContext):
        self.progress.emit(context)

class ProtocolViewer(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumSize(400, 400)

        self.eventTextBlocks: List[Tuple[QTextBlock, Optional[QTextBlock]]] = []
        self.lastContext: Optional[RunContext] = None
    
    @staticmethod
    def makeBlockFormats(depth: int) -> Tuple[QTextBlockFormat, QTextBlockFormat]:
        eventFormat = QTextBlockFormat()
        eventFormat.setTopMargin(MARGIN_BETWEEN_EVENTS)
        eventFormat.setIndent(depth)

        detailsFormat = QTextBlockFormat()
        detailsFormat.setIndent(depth)

        return eventFormat, detailsFormat

    @staticmethod
    def makeCharFormats(active: bool = False, on_path: bool = False) -> Tuple[QTextCharFormat, QTextCharFormat]:
        eventFormat = QTextCharFormat()
        if active:
            eventFormat.setFontWeight(QFont.Bold)
        if on_path:
            eventFormat.setFontUnderline(True)

        detailsFormat = QTextCharFormat()

        return eventFormat, detailsFormat

    def loadProtocol(self, protocol: Event):
        cursor = QTextCursor(self.document())
        self.eventTextBlocks = []
        for event in protocol:
            eventBlockFormat, detailsBlockFormat = self.makeBlockFormats(event.protocol_depth)
            eventCharFormat, detailsCharFormat = self.makeCharFormats()

            cursor.insertBlock(eventBlockFormat)
            cursor.setCharFormat(eventCharFormat)
            cursor.insertText(f"({event.readable_type}) {event.label}")
            eventBlock = cursor.block()

            detailsBlock: Optional[QTextBlock] = None
            details = event.gui_details()
            cursor.insertBlock(detailsBlockFormat)
            cursor.setCharFormat(detailsCharFormat)
            if details:
                cursor.insertText(details)
            detailsBlock = cursor.block()

            self.eventTextBlocks.append((eventBlock, detailsBlock))

    def formatLine(self, context: RunContext, active):
        for node_index, node in enumerate(context.path):
            event = node.event
            node_active = active and (node_index == len(context.path) - 1)
            lines = self.eventTextBlocks[event.protocol_line]

            blockFormats = self.makeBlockFormats(event.protocol_depth)
            charFormats = self.makeCharFormats(node_active, on_path=active)
            for line_index, (line, blockFormat, charFormat) in enumerate(zip(lines, blockFormats, charFormats)):
                newText: Optional[str] = None
                if line_index == 1:
                    # Details line may change to indicate things like what iteration is running.
                    newText = event.gui_details(context)

                cursor = QTextCursor(line)
                cursor.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
                cursor.setCharFormat(charFormat)
                cursor.setBlockFormat(blockFormat)
                if newText:
                    cursor.insertText(newText)

    def progress(self, context: RunContext):
        if self.lastContext is not None:
            self.formatLine(self.lastContext, active=False)

        self.formatLine(context, active=True)
        self.lastContext = context

class SequencingUi(QMainWindow):
    def __init__(self):
        super().__init__()

        previewWidget: Optional[PreviewWidget] = None
        if PREVIEW_PATH is not None and PREVIEW_PATH.is_socket():
            previewWidget = PreviewWidget(PREVIEW_PATH)

        # Create the main elements...
        self.protocolThread = ProtocolThread()
        self.protocolViewer = ProtocolViewer()
        self.startButton = QPushButton()
        self.stopButton = QPushButton()
        self.openAction = QAction("&Open")
        # self.settingsAction = QAction("S&ettings")

        # TODO: Estimated total time and estimated time remaining -- status bar

        # ...populate them ...
        self.startButton.setText("Start")
        self.stopButton.setText("Stop")

        # ... make them do stuff...
        self.protocolThread.progress.connect(self.protocolViewer.progress)
        self.protocolThread.finished.connect(self.finished)
        self.protocolThread.error.connect(self.error)
        self.openAction.triggered.connect(self.open)
        # self.settingsAction.triggered.connect()
        self.startButton.clicked.connect(self.start)
        self.stopButton.clicked.connect(self.stop)

        # ... and lay them out.
        # TODO: mainLayout that holds leftLayout and rightLayout
        mainWidget = QWidget()
        mainLayout = QHBoxLayout()
        mainWidget.setLayout(mainLayout)

        leftWidget = QWidget()
        leftLayout = QVBoxLayout()
        leftWidget.setLayout(leftLayout)
        leftLayout.addWidget(self.protocolViewer)
        startStopWidget = QWidget()
        startStopLayout = QHBoxLayout()
        startStopWidget.setLayout(startStopLayout)
        startStopLayout.addWidget(self.startButton)
        startStopLayout.addWidget(self.stopButton)
        leftLayout.addWidget(startStopWidget)
        mainLayout.addWidget(leftWidget)

        if previewWidget is not None:
            mainLayout.addWidget(previewWidget)

        fileMenu = self.menuBar().addMenu("&File")
        fileMenu.addAction(self.openAction)
        # fileMenu.addAction(self.settingsAction)

        self.setCentralWidget(mainWidget)
        self.setWindowTitle(WINDOW_TITLE_BASE)

        self.stop()
        self.startButton.setEnabled(False)

    def stop(self):
        self.stopButton.setEnabled(False)
        self.protocolThread.requestInterruption()

    def error(self, error: Tuple):
        exception_type, exception, text = error
        if exception_type is not InterruptedError:
            QErrorMessage.qtHandler().showMessage(f"{exception_type.__name__}: {str(exception)}")

    def finished(self):
        self.stopButton.setEnabled(False)
        self.startButton.setEnabled(True)
        self.openAction.setEnabled(True)

    def start(self):
        self.stopButton.setEnabled(True)
        self.startButton.setEnabled(False)
        self.openAction.setEnabled(False)
        self.protocolThread.start()

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open sequencing protocol", PROTOCOLS_DIR, "Sequencing protocols (*.454sp.json)")
        if not path:
            # Dialog closed
            return
        
        with open(path) as protocol_file:
            self.protocol, _ = load_protocol_json(json.load(protocol_file))

        self.protocolViewer.clear()
        self.protocolViewer.loadProtocol(self.protocol)
        self.protocolThread.protocol = self.protocol

        self.startButton.setEnabled(True)
        self.setWindowTitle(f"{Path(path).name} - {WINDOW_TITLE_BASE}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SequencingUi()
    ui.show()

    if HAL_PATH is None or not HAL_PATH.is_socket():
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
