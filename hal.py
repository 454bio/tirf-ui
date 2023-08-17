from dataclasses import dataclass
from typing import Dict
import json
import socket
import time

ENCODING = "utf-8"
MAX_RESPONSE_SIZE = 1 << 10
SOCKET_POLL_PERIOD = 1  # second

class HalError(Exception):
    pass

@dataclass
class Hal:
    socket_path: str

    def run_command(self, command: Dict, thread) -> Dict:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(self.socket_path)

            request_raw = json.dumps(command).encode(ENCODING)
            s.sendall(request_raw)

            response_raw = bytes()

            # If we're in a QThread, periodically check if we need to stop
            # TODO: There's probably a better way to do this
            if thread is not None:
                s.settimeout(SOCKET_POLL_PERIOD)
                while not thread.isInterruptionRequested():
                    try:
                        response_raw = s.recv(MAX_RESPONSE_SIZE)
                        break
                    except socket.timeout:
                        pass
                else:
                    # Interrupted, don't bother trying to parse
                    return
            else:
                response_raw = s.recv(MAX_RESPONSE_SIZE)
            response = json.loads(response_raw.decode(ENCODING))
            if not response["success"]:
                raise HalError(response["error_message"])

            return response["response"]

    def disable_heater(self, thread, tries=5):
        for _ in range(tries):
            try:
                self.run_command({
                    "command": "disable_heater",
                    "args": {}
                }, thread)
                break
            except Exception as e:
                print(e)
                time.sleep(1)
        else:
            raise RuntimeError(f"lp0 on fire: failed to turn off the heater after {tries} tries. RESTART SYSTEM.")
