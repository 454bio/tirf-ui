from dataclasses import dataclass
from typing import Dict
import json
import socket

ENCODING = "utf-8"
MAX_RESPONSE_SIZE = 1 << 10

@dataclass
class Hal:
    socket_path: str

    def run_command(self, command: Dict):
        print(command) # XXX
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.socket_path)

            request = json.dumps(command).encode(ENCODING)
            s.sendall(request)

            response = s.recv(MAX_RESPONSE_SIZE).decode(ENCODING)
            print(response) # XXX
