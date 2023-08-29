import socket

# TODO: Make this configurable
CONNECT_ADDRESS = "127.0.0.1"
LISTEN_ADDRESS = "0.0.0.0"

def exists(address, port: int):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((address, port)) == 0
