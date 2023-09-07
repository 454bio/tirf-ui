import sys
import time
from functools import partial
from typing import Dict, List, Optional

from PySide2.QtCore import Slot, QThread, Qt
from PySide2.QtGui import QDoubleValidator, QIntValidator
from PySide2.QtWidgets import QApplication, QErrorMessage, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget

import ip_utils
from hal import boost_bool, Hal
from sequencing_protocol import MAX_TEMPERATURE_HOLD_S, MAX_TEMPERATURE_WAIT_S
from version import VERSION

WINDOW_TITLE = "454 Image Preview"
HAL_PORT = 45400
MOCK_WARNING_TEXT = f"No HAL on port {HAL_PORT}, running in mock mode"

class HalThread(QThread):
    def __init__(self, halAddress):
        super().__init__()
        self.command: Optional[Dict] = None
        self.hal: Optional[Hal] = None

        # Create the HAL iff there's a socket we can connect to.
        # Otherwise, run in mock mode.
        if HAL_PORT is not None and ip_utils.exists(halAddress, HAL_PORT):
            self.hal = Hal(halAddress, HAL_PORT)

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

class ManualControlsWidget(QWidget):
    def __init__(self, halAddress):
        super().__init__()

        self.halThread = HalThread(halAddress)

        # Whether we can control the filter programmatically. Assume False until we can ask the HAL.
        filterServoControl = False
        maxLedFlashMs = 5000

        if self.halThread.hal is not None:
            # We need this data to open the window, so it's okay that it's blocking.
            # If we can't talk to the HAL, nothing else will work, so it's okay that failure here is fatal.
            # TODO: Get these from the caller if possible rather than calling the HAL ourselves
            halMetadata = self.halThread.hal.run_command({
                "command": "get_metadata",
                "args": {}
            })
            filterServoControl = boost_bool(halMetadata["filter_servo_control"])
            cameraOptions = halMetadata.get("camera_options")
            if cameraOptions:
                maxLedFlashMs = int(cameraOptions["shutter_time_ms"])

        self.startButtons: List[QPushButton] = []
        self.stopButton = QPushButton("Cancel manual operation")
        self.stopButton.clicked.connect(self.halThread.requestInterruption)

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

        flashButton = QPushButton("Flash")
        flashButton.clicked.connect(partial(self.flash, False))
        captureNowButton = QPushButton("Capture")
        captureNowButton.clicked.connect(partial(self.flash, True))
        self.startButtons.append(flashButton)
        self.startButtons.append(captureNowButton)
        ledStartButtonsLayout = QHBoxLayout()
        ledStartButtonsLayout.addWidget(flashButton)
        ledStartButtonsLayout.addWidget(captureNowButton)
        ledStartButtonsWidget = QWidget()
        ledStartButtonsWidget.setLayout(ledStartButtonsLayout)

        # Temperature controls.
        self.temperatureNumber = QLineEdit()
        self.temperatureNumber.setMaximumWidth(50)
        self.temperatureNumber.setValidator(QDoubleValidator())
        self.temperatureNumber.setAlignment(Qt.AlignRight)
        heaterOnButton = QPushButton("Set")
        heaterOnButton.clicked.connect(self.setTemperature)
        heaterOffButton = QPushButton("Disable")
        heaterOffButton.clicked.connect(self.disableHeater)
        self.startButtons.append(heaterOnButton)
        self.startButtons.append(heaterOffButton)
        temperatureControlsLayout = QHBoxLayout()
        temperatureControlsLayout.addWidget(QLabel("Heater"))
        temperatureControlsLayout.addWidget(self.temperatureNumber)
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
        mainLayout = QVBoxLayout()
        mainLayout.addWidget(ledControlsWidget)
        if filterServoPicker:
            mainLayout.addWidget(filterServoPicker)
        mainLayout.addWidget(ledStartButtonsWidget)
        mainLayout.addWidget(temperatureControlsWidget)
        mainLayout.addWidget(uvCleavingControlsWidget)
        mainLayout.addWidget(self.stopButton)

        self.setLayout(mainLayout)

        self.halThread.started.connect(partial(self.setStartButtonsEnabled, False))
        self.halThread.finished.connect(partial(self.setStartButtonsEnabled, True))
        self.setStartButtonsEnabled(True)

        # TODO: Loop that actually talks to the HAL -- it can probably just be a QTimer connected to `capture`

    def setStartButtonsEnabled(self, running: bool):
        self.stopButton.setEnabled(not running)

        for button in self.startButtons:
            button.setEnabled(running)

    @Slot(None)
    def flash(self, capture: bool):
        flashes = []
        for colorName, widget in self.durationNumbers.items():
            duration_ms = int(widget.text())
            if duration_ms > 0:
                flashes.append({
                    "led": colorName,
                    "duration_ms": duration_ms
                })

        if not flashes:
            print("No flashes configured, not flashing")
            return

        # TODO: Request a larger preview (0.5x rather than 0.125x?)
        if capture:
            # TODO: Should save the images somewhere by default
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
        else:
            self.halThread.runCommand({
                "command": "flash_leds",
                "args": {
                    "flashes": flashes
                }
            })

    @Slot(None)
    def cleave(self):
        cleavingDurationMs = int(self.cleavingNumber.text())

        if not cleavingDurationMs:
            print("Cleaving duration == 0, not cleaving")
            return

        # TODO: Request a larger preview (0.5x rather than 0.125x?)
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
        temperatureString = self.temperatureNumber.text()
        if not temperatureString:
            print("Temperature not specified, not setting")
            return

        temperatureKelvin = float(temperatureString) + 273.15

        self.halThread.runCommand({
            "command": "wait_for_temperature",
            "args": {
                "temperature_args": {
                    "target_temperature_kelvin": temperatureKelvin,
                    "wait_time_s": MAX_TEMPERATURE_WAIT_S,
                    "hold_time_s": MAX_TEMPERATURE_HOLD_S
                }
            }
        })

    @Slot(None)
    def disableHeater(self):
        self.halThread.runCommand({
            "command": "disable_heater",
            "args": {}
        })

if __name__ == "__main__":
    app = QApplication(sys.argv)
    halAddress = ip_utils.CONNECT_ADDRESS if len(sys.argv) == 1 else sys.argv[1]
    ui = ManualControlsWidget(halAddress)
    ui.show()

    if ui.halThread.hal is None:
        # We're in mock mode. Make it obvious.
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
