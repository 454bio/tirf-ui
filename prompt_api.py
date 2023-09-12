import atexit
import json
import time
from functools import partial

from PySide2.QtCore import Signal, Slot, QObject
from PySide2.QtGui import QImage
from PySide2.QtNetwork import QHostAddress, QTcpServer, QTcpSocket
from PySide2.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

import ip_utils
from pil_wrapper import Image, ImageQt

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
    received_image = Signal(QImage)

    def __init__(self, parent, port=PROMPT_PORT):
        super().__init__(parent)

        self.server = QTcpServer(self)
        self.server.newConnection.connect(self.handleConnection)
        if not self.server.listen(QHostAddress(ip_utils.LISTEN_ADDRESS), port):
            raise Exception("Could not start prompt API server")

        # Placeholder for a GUI-controlled camera.
        self.camera = None

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
            if command == "confirmation_prompt":
                text = request["text"]
                prompt = ConfirmationPrompt(self.parent(), text)
                success = bool(prompt.exec_())
            elif command == "camera_setup_and_start":
                # Start local camera control.
                # If configured, this is typically called at the beginning of an image sequence.
                # This enables usage of cameras that are unsupported directly on the Pi.
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
                    self.camera.cav["PixelEncoding"] = "Mono16"

                    # "sequence" corresponds to video mode. The camera will still only capture on the external trigger but we will not have to arm before each capture.
                    # A typical image sequence is only 4 images long, but let's leave lots of room for exceptional cases.
                    self.camera.setup_acquisition(mode="sequence", nframes=32)

                exposure_ms = int(request["camera_parameters"]["exposure_time_ms"])
                self.camera.set_exposure(exposure_ms / 1000)

                self.camera.start_acquisition()

                # Acquisition is not immediately running after start_acquisition, and there doesn't appear to be a good way to wait for it to be ready.
                # If we proceed without waiting, the GPIO trigger will fire before the camera is ready, causing the protocol to fail.
                time.sleep(0.5)
            elif command == "camera_wait":
                # Expect and process an image from the local camera.
                # This is optional, but calling this during a sequence enables image preview.
                if self.camera is None or not self.camera.acquisition_in_progress():
                    raise Exception("Camera not configured")

                path = request.get("path")

                # TODO: This hangs the UI until the frame arrives
                self.camera.wait_for_frame()
                image = Image.fromarray(self.camera.read_oldest_image())
                if path:
                    image.save(path)
                self.received_image.emit(ImageQt.ImageQt(image.resize((512, 512), Image.Resampling.NEAREST)))
            elif command == "camera_stop_and_save":
                # Stop the local camera, saving any remaining images.
                # If configured, this is typically called at the end of an image sequence.
                if self.camera is None or not self.camera.acquisition_in_progress():
                    raise Exception("Camera not configured")

                path = request.get("path")

                # There *shouldn't* be any images left, but try to retrieve them just in case.
                # This is nonblocking.
                for image_index, image_arr in enumerate(self.camera.read_multiple_images()):
                    image = Image.fromarray(image_arr)
                    if path:
                        image.save(f"{path}-{image_index}.tif")
                    self.received_image.emit(ImageQt.ImageQt(image.resize((512, 512), Image.Resampling.NEAREST)))
                self.camera.stop_acquisition()
            else:
                raise ValueError(f"Unknown command {command}")
        except Exception as e:
            success = False
            error = str(e)
            print(e)

        response = {
            "success": success,
            "error": error
        }
        try:
            s.write(json.dumps(response).encode(ENCODING))
        except Exception as e:
            print(f"Unable to write prompt response")
            print(e)
