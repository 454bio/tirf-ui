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
