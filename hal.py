from dataclasses import dataclass
from typing import Dict, Union
import json
import socket
import time

ENCODING = "utf-8"
MAX_RESPONSE_SIZE = 1 << 10
SOCKET_POLL_PERIOD = 1  # second

def boost_bool(value_raw: Union[str, bool]):
    """
    Boost.PropertyTree converts all values to strings, so we need to massage it into a bool.
    TODO: Remove this once we have Boost.JSON
    """
    return value_raw if type(value_raw) == bool else value_raw == "true"

class HalError(Exception):
    pass

@dataclass
class Hal:
    """Simple wrapper to send commands to the HAL."""
    socket_path: str

    def run_command(self, command: Dict, thread=None) -> Dict:
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
                    return {}
            else:
                response_raw = s.recv(MAX_RESPONSE_SIZE)
            response = json.loads(response_raw.decode(ENCODING))
            if not boost_bool(response["success"]):
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
            raise HalError(f"lp0 on fire: failed to turn off the heater after {tries} tries. RESTART SYSTEM.")
