import sys
import time
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional

from PySide2.QtCore import Slot, QThread, Qt
from PySide2.QtGui import QDoubleValidator, QIntValidator
from PySide2.QtWidgets import QApplication, QErrorMessage, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSlider, QVBoxLayout, QWidget

from hal import boost_bool, Hal
from preview_widget import PreviewWidget
from version import VERSION

WINDOW_TITLE = "454 Image Preview"
HAL_PATH: Optional[Path] = Path("/454/api")
PREVIEW_PATH: Optional[Path] = Path("/454/preview")
MOCK_WARNING_TEXT = f"No HAL at {HAL_PATH}, running in mock mode"

class HalThread(QThread):
    def __init__(self):
        super().__init__()
        self.command: Optional[Dict] = None
        self.hal: Optional[Hal] = None

        # Create the HAL iff there's a socket we can connect to.
        # Otherwise, run in mock mode.
        if HAL_PATH is not None and HAL_PATH.is_socket():
            self.hal = Hal(str(HAL_PATH))

    def runCommand(self, command: Dict):
        self.command = command
        if self.isRunning():
            raise Exception("Command is still running")

        self.start()

    @Slot(None)
    def run(self):
        command = self.command
        if command is None:
            raise Exception("run called without a command")

        self.command = None

        print(command)

        if self.hal is None:
            print("Mock mode, not running the command")
            time.sleep(1)
            return

        try:
            self.hal.run_command(command, self)
        except Exception as e:
            errorString = f"HAL error: {str(e)}"
            print(errorString)
            QErrorMessage.qtHandler().showMessage(errorString)

class PreviewUi(QMainWindow):
    def __init__(self):
        super().__init__()

        self.halThread = HalThread()

        # Whether we can control the filter programmatically. Assume False until we can ask the HAL.
        filterServoControl = False
        maxLedFlashMs = 5000

        # Get the HAL and populate the status bar.
        statusBarText: List[str] = []
        permanentStatusBarText: List[str] = [f"GUI v{VERSION}"]
        if self.halThread.hal is not None:
            # We need this data to open the window, so it's okay that it's blocking.
            # If we can't talk to the HAL, nothing else will work, so it's okay that failure here is fatal.
            halMetadata = self.halThread.hal.run_command({
                "command": "get_metadata",
                "args": {}
            })
            permanentStatusBarText.append(f"Unit {halMetadata['serial_number'][-8:]}")
            permanentStatusBarText.append(f"HAL v{halMetadata['hal_version']}")
            filterServoControl = boost_bool(halMetadata["filter_servo_control"])
            cameraOptions = halMetadata.get("camera_options")
            if cameraOptions:
                maxLedFlashMs = int(cameraOptions["shutter_time_ms"])
                statusBarText.append(f"Shutter time {maxLedFlashMs} ms")
        else:
            permanentStatusBarText.append("Mock mode (no HAL)")
        statusBar = self.statusBar()
        for text in permanentStatusBarText:
            statusBar.addPermanentWidget(QLabel(text))
        for text in statusBarText:
            statusBar.addWidget(QLabel(text))

        previewWidget: Optional[PreviewWidget] = None
        if PREVIEW_PATH is not None and PREVIEW_PATH.is_socket():
            previewWidget = PreviewWidget(PREVIEW_PATH)

        self.startButtons: List[QPushButton] = []
        self.stopButton = QPushButton("Cancel")
        self.stopButton.clicked.connect(self.halThread.requestInterruption)
        statusBar.addWidget(self.stopButton)

        # Generate the controls for each LED.
        # This cannot be rolled into the `for` loop below because Python's late-binding will result in the connections being crossed.
        def make_led_controls(colorName: str, text: Optional[str] = None, maxTimeMs=maxLedFlashMs) -> List[QWidget]:
            # TODO: Make some part of this the corresponding color
            widgets: List[QWidget] = []
            widgets.append(QLabel(text if text is not None else colorName.capitalize()))

            durationSlider = QSlider(Qt.Horizontal)
            widgets.append(durationSlider)
            durationSlider.setRange(0, maxTimeMs)

            durationNumber = QLineEdit()
            widgets.append(durationNumber)
            durationNumber.setMaximumWidth(50)
            durationNumber.setValidator(QIntValidator())
            durationNumber.setAlignment(Qt.AlignRight)
            durationNumber.setText("0")

            widgets.append(QLabel("ms"))

            durationNumber.textChanged.connect(lambda x: durationSlider.setValue(int(x)))
            durationSlider.sliderMoved.connect(lambda x: durationNumber.setText(str(x)))

            return widgets

        # LED controls.
        ledControlsLayout = QGridLayout()
        self.durationNumbers: Dict[str, QLineEdit] = {}
        for colorIndex, colorName in enumerate(["red", "orange", "green", "blue"]):
            for widgetIndex, widget in enumerate(make_led_controls(colorName)):
                if isinstance(widget, QLineEdit):
                    # Hold on to the text inputs so we can retrieve their values on `capture()`.
                    # TODO: Will need a different way of doing this if there is ever another QLineEdit here
                    self.durationNumbers[colorName] = widget
                ledControlsLayout.addWidget(widget, colorIndex, widgetIndex)
        ledControlsWidget = QWidget()
        ledControlsWidget.setLayout(ledControlsLayout)

        # TODO: Type
        filterServoPicker: Optional[QWidget] = None
        if filterServoControl:
            # TODO: Filter controls
            pass

        captureNowButton = QPushButton("Capture")
        captureNowButton.clicked.connect(self.capture)
        self.startButtons.append(captureNowButton)

        # Temperature controls.
        temperatureNumber = QLineEdit()
        temperatureNumber.setMaximumWidth(50)
        temperatureNumber.setValidator(QDoubleValidator())
        temperatureNumber.setAlignment(Qt.AlignRight)
        heaterOnButton = QPushButton("Set")
        heaterOnButton.clicked.connect(self.setTemperature)
        heaterOffButton = QPushButton("Disable")
        heaterOffButton.clicked.connect(self.disableHeater)
        self.startButtons.append(heaterOnButton)
        self.startButtons.append(heaterOffButton)
        temperatureControlsLayout = QHBoxLayout()
        temperatureControlsLayout.addWidget(QLabel("Heater"))
        temperatureControlsLayout.addWidget(temperatureNumber)
        temperatureControlsLayout.addWidget(QLabel("ºC"))
        temperatureControlsLayout.addWidget(heaterOnButton)
        temperatureControlsLayout.addWidget(heaterOffButton)
        temperatureControlsWidget = QWidget()
        temperatureControlsWidget.setLayout(temperatureControlsLayout)

        # UV cleaving controls.
        uvCleavingControlsLayout = QHBoxLayout()
        for widget in make_led_controls("uv", text="UV", maxTimeMs=5000):
            if isinstance(widget, QLineEdit):
                # Hold on to the text input so we can retrieve their values on `cleave()`.
                # TODO: Will need a different way of doing this if there is ever another QLineEdit here
                self.cleavingNumber: QLineEdit = widget
            uvCleavingControlsLayout.addWidget(widget)
        cleaveButton = QPushButton("Cleave")
        cleaveButton.clicked.connect(self.cleave)
        self.startButtons.append(cleaveButton)
        uvCleavingControlsLayout.addWidget(cleaveButton)
        uvCleavingControlsWidget = QWidget()
        uvCleavingControlsWidget.setLayout(uvCleavingControlsLayout)

        # Lay them out.
        mainWidget = QWidget()
        mainLayout = QHBoxLayout()

        leftWidget = QWidget()
        leftLayout = QVBoxLayout()
        leftLayout.addWidget(ledControlsWidget)
        if filterServoPicker:
            leftWidget.addWidget(filterServoPicker)
        leftLayout.addWidget(captureNowButton)
        leftLayout.addWidget(temperatureControlsWidget)
        leftLayout.addWidget(uvCleavingControlsWidget)
        leftWidget.setLayout(leftLayout)
        mainLayout.addWidget(leftWidget)

        if previewWidget is not None:
            mainLayout.addWidget(previewWidget)

        mainWidget.setLayout(mainLayout)
        self.setCentralWidget(mainWidget)
        self.setWindowTitle(WINDOW_TITLE)

        self.halThread.started.connect(partial(self.setStartButtonsEnabled, False))
        self.halThread.finished.connect(partial(self.setStartButtonsEnabled, True))
        self.setStartButtonsEnabled(True)

        # TODO: Loop that actually talks to the HAL -- it can probably just be a QTimer connected to `capture`

    def setStartButtonsEnabled(self, running: bool):
        self.stopButton.setEnabled(not running)

        for button in self.startButtons:
            button.setEnabled(running)

    @Slot(None)
    def capture(self):
        flashes = []
        for colorName, widget in self.durationNumbers.items():
            duration_ms = int(widget.text())
            if duration_ms > 0:
                flashes.append({
                    "led": colorName,
                    "duration_ms": duration_ms
                })

        if not flashes:
            print("No flashes configured, not capturing")
            return

        # TODO: Request a larger preview (0.5x rather than 0.125x?) and no image saving
        self.halThread.runCommand({
            "command": "run_image_sequence",
            "args": {
                "sequence": {
                    "label": "Preview sequence",
                    "schema_version": 0,
                    "images": [
                        {
                            "label": "Preview image",
                            "flashes": flashes,
                            # TODO: Retrieve the selected filter from the UI
                            "filter": "any_filter"
                        }
                    ]
                }
            }
        })

    @Slot(None)
    def cleave(self):
        cleavingDurationMs = int(self.cleavingNumber.text())

        if not cleavingDurationMs:
            print("Cleaving duration == 0, not cleaving")
            return

        # TODO: Request a larger preview (0.5x rather than 0.125x?) and no image saving
        self.halThread.runCommand({
            "command": "cleave",
            "args": {
                "cleave_args": {
                    "schema_version": 0,
                    "capture_period_ms": 0,
                    "cleaving_duration_ms": cleavingDurationMs
                }
            }
        })

    @Slot(None)
    def setTemperature(self):
        # TODO: There's a lot of duplicated logic in these
        # Need to start using a QThread for these anyway to avoid hanging the UI -- maybe the boilerplate can go in there somehow
        pass

    @Slot(None)
    def disableHeater(self):
        pass

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = PreviewUi()
    ui.show()

    if ui.halThread.hal is None:
        # We're in mock mode. Make it obvious.
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
