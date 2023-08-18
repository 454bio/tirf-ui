import sys
from pathlib import Path
from typing import List, Optional

from PySide2.QtCore import Qt
from PySide2.QtGui import QIntValidator
from PySide2.QtWidgets import QApplication, QErrorMessage, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QSlider, QVBoxLayout, QWidget

from hal import boost_bool, Hal
from preview_widget import PreviewWidget
from user_prompts import PromptApi
from version import VERSION

WINDOW_TITLE_BASE = "454 Image Preview"
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
        permanentStatusBarText: List[str] = [f"GUI version {VERSION}"]
        if HAL_PATH is not None and HAL_PATH.is_socket():
            self.hal = Hal(str(HAL_PATH))
            halMetadata = self.hal.run_command({
                "command": "get_metadata",
                "args": {}
            })
            permanentStatusBarText.append(f"Connected to unit {halMetadata['serial_number']}")
            permanentStatusBarText.append(f"HAL version {halMetadata['hal_version']}")
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

        # Generate the controls for each LED.
        # This cannot be rolled into the `for` loop below because Python's late-binding will result in the connections being crossed.
        def make_led_controls(colorName: str) -> List[QWidget]:
            # TODO: Make some part of this the corresponding color
            widgets: List[QWidget] = []
            widgets.append(QLabel(colorName.capitalize()))

            durationSlider = QSlider(Qt.Horizontal)
            widgets.append(durationSlider)
            durationSlider.setRange(0, cameraShutterTimeMs)

            durationNumber = QLineEdit()
            widgets.append(durationNumber)
            durationNumber.setMaximumWidth(50)
            durationNumber.setValidator(QIntValidator())
            durationNumber.setAlignment(Qt.AlignRight)

            widgets.append(QLabel("ms"))

            durationNumber.textChanged.connect(lambda x: durationSlider.setValue(int(x)))
            durationSlider.sliderMoved.connect(lambda x: durationNumber.setText(str(x)))

            return widgets

        # LED controls.
        ledControlsLayout = QGridLayout()
        for colorIndex, colorName in enumerate(["red", "orange", "green", "blue"]):
            for widgetIndex, widget in enumerate(make_led_controls(colorName)):
                ledControlsLayout.addWidget(widget, colorIndex, widgetIndex)
        ledControlsWidget = QWidget()
        ledControlsWidget.setLayout(ledControlsLayout)

        # TODO: Type
        filterServoPicker: Optional[QWidget] = None
        if filterServoControl:
            # TODO: Filter controls
            pass

        # Lay them out.
        mainWidget = QWidget()
        mainLayout = QHBoxLayout()

        leftWidget = QWidget()
        leftLayout = QVBoxLayout()
        leftLayout.addWidget(ledControlsWidget)
        if filterServoPicker:
            leftWidget.addWidget(filterServoPicker)
        leftWidget.setLayout(leftLayout)
        mainLayout.addWidget(leftWidget)

        if previewWidget is not None:
            mainLayout.addWidget(previewWidget)

        mainWidget.setLayout(mainLayout)
        self.setCentralWidget(mainWidget)

        # TODO: Loop that actually talks to the HAL -- it can probably just be a QTimer
        # TODO: Request a larger preview (0.5x rather than 0.125x?) and no image saving

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ui = PreviewUi()
    ui.show()

    if ui.hal is not None:
        # Only need the prompt API if we're connecting to a HAL.
        promptApi = PromptApi(ui)
    else:
        # Otherwise, we're in mock mode. Make it obvious.
        print(MOCK_WARNING_TEXT)
        QErrorMessage.qtHandler().showMessage(MOCK_WARNING_TEXT)

    sys.exit(app.exec_())
