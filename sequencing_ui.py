import enum
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide2.QtCore import Signal, Slot, QThread
from PySide2.QtGui import QTextBlock, QTextCursor, QTextBlockFormat, QTextCharFormat, QFont
from PySide2.QtNetwork import QLocalServer
from PySide2.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QAction, QFileDialog, QErrorMessage, QLabel

from preview_widget import PreviewWidget
from sequencing_protocol import load_protocol_json, validate_protocol_json, Event, RunContext, RunContextNode, Hal
from user_prompts import PromptApi
from version import VERSION

WINDOW_TITLE_BASE = "454 Sequencer"
PROTOCOLS_DIR = "protocols"
MARGIN_BETWEEN_EVENTS = 12

HAL_PATH: Optional[Path] = Path("/454/api")
PREVIEW_PATH: Optional[Path] = Path("/454/preview")
STATUS_PATH: Optional[Path] = Path("/454/hal-status")
OUTPUT_DIR_ROOT = Path.home() / "454" / "output"

MAX_STATUS_WAIT_MS = 100
MAX_STATUS_MESSAGE_SIZE = 1 << 10

MOCK_WARNING_TEXT = f"No HAL at {HAL_PATH}, running in mock mode"

class SequencingProtocolStatus(enum.Enum):
    NEED_PROTOCOL = "Open a protocol to begin"
    READY = "Ready to run"
    RUNNING = "Protocol running"
    STOPPED = "Protocol stopped"
    FAILED = "Protocol failed"
    COMPLETED = "Protocol completed"

class ProtocolThread(QThread):
    finished = Signal(SequencingProtocolStatus)
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
        result = SequencingProtocolStatus.COMPLETED
        if protocol is not None:
            try:
                protocol.event_run_callback = self.eventRunCallback
                protocol.run(RunContext([RunContextNode(protocol)], output_dir, self.hal, self))
            except Exception as e:
                traceback.print_exc()
                exctype, value = sys.exc_info()[:2]
                self.error.emit((exctype, value, traceback.format_exc()))
                if exctype is InterruptedError:
                    result = SequencingProtocolStatus.STOPPED
                else:
                    result = SequencingProtocolStatus.FAILED
            finally:
                protocol.event_run_callback = None
                self.finished.emit(result)

    def eventRunCallback(self, context: RunContext):
        self.progress.emit(context)

class ProtocolViewer(QTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setMinimumSize(500, 500)

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

        # Holder for dynamic status bar widgets (placed on the left)
        self.statusWidgets: Dict[str, QLabel] = {}
        self.updateStatusWidget("status", QLabel(SequencingProtocolStatus.NEED_PROTOCOL.value))

        # Server for dynamic status bar widgets
        self.statusServer = QLocalServer(self)
        if STATUS_PATH is not None and self.protocolThread.hal is not None:
            self.statusServer.newConnection.connect(self.handleStatusConnection)
            STATUS_PATH.unlink(missing_ok=True)
            if not self.statusServer.listen(str(STATUS_PATH)):
                raise Exception("Could not start status server")
            STATUS_PATH.chmod(777)

        # Holder for static status bar widgets (placed on the right)
        statusBarText = [f"GUI version {VERSION}"]
        if self.protocolThread.hal is not None:
            halMetadata = self.protocolThread.hal.run_command({
                "command": "get_metadata",
                "args": {}
            })
            statusBarText.append(f"Connected to unit {halMetadata['serial_number'][-8:]}")
            statusBarText.append(f"HAL version {halMetadata['hal_version']}")
        else:
            statusBarText.append("Mock mode (no HAL)")
        for text in statusBarText:
            self.statusBar().addPermanentWidget(QLabel(text))

        self.stop()
        self.startButton.setEnabled(False)

    def handleStatusConnection(self):
        s = self.statusServer.nextPendingConnection()
        if not s.waitForReadyRead(MAX_STATUS_WAIT_MS):
            raise TimeoutError
        
        status_message_str = s.readData(MAX_STATUS_MESSAGE_SIZE)
        status = json.loads(status_message_str)

        # Just feed it straight to the widgets -- neither we nor the HAL care about errors here.
        self.updateStatusWidget(**status)

    def updateStatusWidget(self, name: str, text: str):
        widget = self.statusWidgets.get(name)
        if widget:
            widget.setText(text)
        else:
            widget = QLabel(text)
            self.statusWidgets[name] = widget
            self.statusBar().addWidget(widget)

    def stop(self):
        self.stopButton.setEnabled(False)
        self.protocolThread.requestInterruption()

    def error(self, error: Tuple):
        exception_type, exception, text = error
        if exception_type is not InterruptedError:
            QErrorMessage.qtHandler().showMessage(f"{exception_type.__name__}: {str(exception)}")

    def finished(self, result: SequencingProtocolStatus):
        if self.protocolThread.hal is not None:
            try:
                self.protocolThread.hal.disable_heater(self.protocolThread)
            except Exception as e:
                self.error((type(e), e, ""))

        self.updateStatusWidget("status", result.value)
        self.stopButton.setEnabled(False)
        self.startButton.setEnabled(True)
        self.openAction.setEnabled(True)

    def start(self):
        self.stopButton.setEnabled(True)
        self.startButton.setEnabled(False)
        self.openAction.setEnabled(False)
        self.updateStatusWidget("status", SequencingProtocolStatus.RUNNING.value)
        self.protocolThread.start()

    def open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open sequencing protocol", PROTOCOLS_DIR, "Sequencing protocols (*.454sp.json)")
        if not path:
            # Dialog closed
            return
        
        try:
            with open(path) as protocol_file:
                protocol_json = json.load(protocol_file)
                validate_protocol_json(protocol_json)
                self.protocol, _ = load_protocol_json(protocol_json)
        except Exception as e:
            self.error((type(e), e, ""))
            return

        self.protocolViewer.clear()
        self.protocolViewer.loadProtocol(self.protocol)
        self.protocolThread.protocol = self.protocol

        self.startButton.setEnabled(True)
        self.setWindowTitle(f"{Path(path).name} - {WINDOW_TITLE_BASE}")

        self.updateStatusWidget("status", SequencingProtocolStatus.READY.value)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SequencingUi()
    ui.show()

    if HAL_PATH is not None and HAL_PATH.is_socket():
        # Only need the prompt API if we're connecting to a HAL.
        promptApi = PromptApi(ui)
        # TODO: PromptApi should emit something that can be connected to updateStatusWidget
        # Temperature, etc.
    else:
        # Otherwise, we're in mock mode. Make it obvious.
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
