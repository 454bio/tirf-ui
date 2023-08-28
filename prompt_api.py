import json
from pathlib import Path

from PySide2.QtCore import Slot, QObject
from PySide2.QtNetwork import QLocalServer
from PySide2.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

ENCODING = "utf-8"
MAX_REQUEST_SIZE = 1 << 10
MAX_READ_WAIT_MS = 100
PROMPT_PATH = Path("/454/hal-message")

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
    def __init__(self, parent, socketPath=PROMPT_PATH):
        super().__init__(parent)

        self.server = QLocalServer(self)
        self.server.newConnection.connect(self.handleConnection)
        socketPath.unlink(missing_ok=True)
        if not self.server.listen(str(socketPath)):
            raise Exception("Could not start prompt API server")
        socketPath.chmod(777)

    @Slot(None)
    def handleConnection(self):
        s = self.server.nextPendingConnection()
        if not s.waitForReadyRead(MAX_READ_WAIT_MS):
            raise TimeoutError

        request_str = s.readData(MAX_REQUEST_SIZE)
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
