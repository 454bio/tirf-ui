import atexit
import json
from functools import partial

from PySide2.QtCore import Slot, QObject
from PySide2.QtNetwork import QHostAddress, QTcpServer, QTcpSocket
from PySide2.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

import ip_utils

ENCODING = "utf-8"
PROMPT_PORT = 45402

class ConfirmationPrompt(QDialog):
    def __init__(self, parent: QWidget, text: str):
        super().__init__(parent)
        label = QLabel()
        label.setText(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(label)
        layout.addWidget(buttons)
        self.setLayout(layout)

class PromptApi(QObject):
    def __init__(self, parent, port=PROMPT_PORT):
        super().__init__(parent)

        self.server = QTcpServer(self)
        self.server.newConnection.connect(self.handleConnection)
        if not self.server.listen(QHostAddress(ip_utils.LISTEN_ADDRESS), port):
            raise Exception("Could not start prompt API server")

    @Slot(None)
    def handleConnection(self):
        s = self.server.nextPendingConnection()
        s.readyRead.connect(partial(self.handleMessage, s))

    @Slot(QTcpSocket)
    def handleMessage(self, s: QTcpSocket):
        request_str = bytes(s.readAll()).decode(ENCODING)
        request = json.loads(request_str)
        command = request.get("command")

        success = True
        error = None
        try:
            # TODO: Command(s?) for local capture -- Andor Zyla camera via pylablib
            if command == "confirmation_prompt":
                text = request["text"]
                prompt = ConfirmationPrompt(self.parent(), text)
                success = bool(prompt.exec_())
            elif command == "camera_setup_and_start":
                if self.camera is None:
                    # This is slow, so only import when needed -- a HAL with its own camera will never call this.
                    from pylablib.devices import Andor
                    self.camera = Andor.AndorSDK3Camera()
                    atexit.register(self.camera.close)

                    # GPIO options.
                    self.camera.set_trigger_mode("ext")
                    self.camera.cav["AuxiliaryOutSource"] = "FireAll"
                    for io_name in self.camera.get_attribute("IOSelector").values:
                        # Setting IOSelector doesn't do anything by itself.
                        self.camera.cav["IOSelector"] = io_name
                        # Instead, it switches what the other IO* attributes are referencing.
                        # Changing these will only affect the IO at io_name.
                        self.camera.cav["IOInvert"] = True

                    # Image format settings.
                    # Available values are "100 MHz" and "270 MHz", which appear to be halved from the "200 MHz" and "540 MHz" options present in the GUI.
                    self.camera.cav["PixelReadoutRate"] = "100 MHz"
                    self.camera.cav["BitDepth"] = "16 Bit"

                    # The HAL should call `camera_stop_and_save` at the end of each image sequence.
                    # "sequence" corresponds to video mode. The camera will still only capture on the external trigger.
                    # A typical image sequence is only 4 images long, but let's leave lots of room for exceptional cases.
                    self.camera.setup_acquisition(mode="sequence", nframes=128)

                exposure_ms = int(request["camera_parameters"]["exposure_time_ms"])
                self.camera.set_exposure(exposure_ms / 1000)

                self.camera.start_acquisition()
            elif command == "camera_stop_and_save":
                if self.camera is None or not self.camera.cav["CameraAcquiring"]:
                    raise Exception("Camera not configured")

                # TODO: Wait until all of the images we care about are available?
                # Need to guess how long (not great) or have the HAL tell us how many images to expect
                # It may make more sense to just save after each capture, which will also enable immediate preview
                images = self.camera.read_multiple_images()
                # TODO: Save the images
                # TODO: Preview them?
                self.camera.stop_acquisition()
            else:
                raise ValueError(f"Unknown command {command}")
        except Exception as e:
            success = False
            error = str(e)

        response = {
            "success": success,
            "error": error
        }
        try:
            s.write(json.dumps(response).encode(ENCODING))
        except Exception as e:
            print(f"Unable to write prompt response")
            print(e)
