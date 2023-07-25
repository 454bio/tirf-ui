from typing import Dict
import socket
from dataclasses import dataclass

@dataclass
class Hal:
    socket_path: str

    def run_image_sequence(self, args: Dict):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.bind(self.socket_path)
            # TODO: Actually do this

    def cleave(self, args: Dict):
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.bind(self.socket_path)
            # TODO: Actually do this
