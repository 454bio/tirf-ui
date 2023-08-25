import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from PySide2.QtCore import Qt, Slot
from PySide2.QtGui import QGuiApplication, QCursor, QIntValidator
from PySide2.QtWidgets import QApplication, QErrorMessage, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QSlider, QVBoxLayout, QWidget

from hal import boost_bool, Hal
from preview_widget import PreviewWidget
from version import VERSION

WINDOW_TITLE = "454 Image Preview"
HAL_PATH: Optional[Path] = Path("/454/api")
PREVIEW_PATH: Optional[Path] = Path("/454/preview")
MOCK_WARNING_TEXT = f"No HAL at {HAL_PATH}, running in mock mode"

class PreviewUi(QMainWindow):
    def __init__(self):
        super().__init__()

        self.hal: Optional[Hal] = None

        # Whether we can control the filter programmatically. Assume False until we can ask the HAL.
        filterServoControl = False
        # This is only used to place an upper limit on the LED flash duration, so pick a default in case we can't get one from the HAL.
        cameraShutterTimeMs = 15000

        # Get the HAL and populate the status bar.
        statusBarText: List[str] = []
        permanentStatusBarText: List[str] = [f"GUI v{VERSION}"]
        if HAL_PATH is not None and HAL_PATH.is_socket():
            self.hal = Hal(str(HAL_PATH))
            halMetadata = self.hal.run_command({
                "command": "get_metadata",
                "args": {}
            })
            permanentStatusBarText.append(f"Unit {halMetadata['serial_number']}")
            permanentStatusBarText.append(f"HAL v{halMetadata['hal_version']}")
            filterServoControl = boost_bool(halMetadata["filter_servo_control"])
            cameraOptions = halMetadata.get("camera_options")
            if cameraOptions:
                cameraShutterTimeMs = int(cameraOptions["shutter_time_ms"])
                statusBarText.append(f"Shutter time {cameraShutterTimeMs} ms")
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

        # Generate the controls for each LED.
        # This cannot be rolled into the `for` loop below because Python's late-binding will result in the connections being crossed.
        def make_led_controls(colorName: str, text: Optional[str] = None, maxTimeMs=cameraShutterTimeMs) -> List[QWidget]:
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

        uvCleavingControlsLayout = QGridLayout()
        for widgetIndex, widget in enumerate(make_led_controls("uv", text="UV Cleaving", maxTimeMs=10000)):
            if isinstance(widget, QLineEdit):
                # Hold on to the text input so we can retrieve their values on `cleave()`.
                # TODO: Will need a different way of doing this if there is ever another QLineEdit here
                self.cleavingNumber: QLineEdit = widget
            uvCleavingControlsLayout.addWidget(widget, 0, widgetIndex)
        uvCleavingControlsWidget = QWidget()
        uvCleavingControlsWidget.setLayout(uvCleavingControlsLayout)

        cleaveButton = QPushButton("Cleave")
        cleaveButton.clicked.connect(self.cleave)
        self.startButtons.append(cleaveButton)

        # Lay them out.
        mainWidget = QWidget()
        mainLayout = QHBoxLayout()

        leftWidget = QWidget()
        leftLayout = QVBoxLayout()
        leftLayout.addWidget(ledControlsWidget)
        if filterServoPicker:
            leftWidget.addWidget(filterServoPicker)
        leftLayout.addWidget(captureNowButton)
        leftLayout.addWidget(uvCleavingControlsWidget)
        leftLayout.addWidget(cleaveButton)
        leftWidget.setLayout(leftLayout)
        mainLayout.addWidget(leftWidget)

        if previewWidget is not None:
            mainLayout.addWidget(previewWidget)

        mainWidget.setLayout(mainLayout)
        self.setCentralWidget(mainWidget)
        self.setWindowTitle(WINDOW_TITLE)

        # TODO: Loop that actually talks to the HAL -- it can probably just be a QTimer connected to `capture`

    def setStartButtonsEnabled(self, enable: bool):
        if enable:
            QGuiApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
        else:
            QGuiApplication.restoreOverrideCursor()

        for button in self.startButtons:
            button.setEnabled(enable)

    @Slot(None)
    def capture(self):
        try:
            self.setStartButtonsEnabled(False)

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

            if not self.hal:
                print("Mock mode, not capturing an image")
                print("Flashes would have contained:", flashes)
                print("Delay to test UI")
                time.sleep(1)
                return

            # TODO: Request a larger preview (0.5x rather than 0.125x?) and no image saving
            self.hal.run_command({
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
        except Exception as e:
            print(e)
        finally:
            self.setStartButtonsEnabled(True)

    @Slot(None)
    def cleave(self):
        try:
            self.setStartButtonsEnabled(False)

            cleavingDurationMs = int(self.cleavingNumber.text())

            if not cleavingDurationMs:
                print("Cleaving duration == 0, not cleaving")
                return

            if not self.hal:
                print("Mock mode, not cleaving")
                print("Would have cleaved for:", cleavingDurationMs)
                print("Delay to test UI")
                time.sleep(1)
                return

            # TODO: Request a larger preview (0.5x rather than 0.125x?) and no image saving
            self.hal.run_command({
                "command": "cleave",
                "args": {
                    "cleave_args": {
                        "schema_version": 0,
                        "capture_period_ms": 0,
                        "cleaving_duration_ms": cleavingDurationMs
                    }
                }
            })
        except Exception as e:
            print(e)
        finally:
            self.setStartButtonsEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = PreviewUi()
    ui.show()

    if ui.hal is None:
        # We're in mock mode. Make it obvious.
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
