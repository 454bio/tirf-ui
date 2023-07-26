from dataclasses import dataclass
from typing import Dict
import json
import socket

ENCODING = "utf-8"
MAX_RESPONSE_SIZE = 1 << 10

class HalError(Exception):
    pass

@dataclass
class Hal:
    socket_path: str

    def run_command(self, command: Dict):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.socket_path)

            request_raw = json.dumps(command).encode(ENCODING)
            s.sendall(request_raw)

            response_raw = s.recv(MAX_RESPONSE_SIZE)
            response = json.loads(response_raw.decode(ENCODING))
            if not response["success"]:
                raise HalError(response["error_message"])
