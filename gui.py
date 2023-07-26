import sys

from PySide2.QtWidgets import QMainWindow, QApplication, QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton, QAction, QFileDialog


PROTOCOLS_DIR = "protocols"

# TODO: Configuration: HAL path, output directory

class SequencingUi(QMainWindow):
    def __init__(self):
        super().__init__()

        # Create the main elements...
        self.stepPreview = QTextEdit()
        self.startButton = QPushButton()
        self.stopButton = QPushButton()
        self.openAction = QAction("&Open")
        self.settingsAction = QAction("S&ettings")
        # TODO: Menu bar: open file, configuration window

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
        mainLayout.addWidget(self.stepPreview)
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
        # TODO
        pass

    def open(self):
        path = QFileDialog.getOpenFileName(self, "Open sequencing protocol", PROTOCOLS_DIR, "Sequencing protocols (*.454sp.json)")
        if not path:
            # Dialog closed
            return
        
        # TODO: Actually load the file

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = SequencingUi()
    ui.show()
    sys.exit(app.exec_())
