"""Minimal independent SDK v0/v1 server; no USB, sysfs or real engine access."""
import socket
import struct
import threading
import time


def word(value):
    return struct.pack("<I", value)


def string(value):
    encoded = value.encode() + b"\0"
    return struct.pack("<H", len(encoded)) + encoded


def packet(device, command, payload=b""):
    return b"ORGB" + struct.pack("<III", device, command, len(payload)) + payload


def controller(name="MSI RGB", location="USB:1462:7d98:port1", serial="unique", version=1,
               with_lighting=True):
    # [V] Independent fixture matching RGBController's legacy descriptor layout.
    body = word(0) + string(name)
    if version >= 1:
        body += string("MSI")
    body += string("USB lighting") + string("1.0") + string(serial) + string(location)
    body += struct.pack("<HI", 1, 0)  # One static mode; active mode index zero.
    body += string("Static") + struct.pack("<9I", 0, 0, 0, 0, 1, 1, 0, 0, 1)
    body += struct.pack("<HI", 1, 0x00332211)  # Mode color.
    body += struct.pack("<H", 1)  # One linear zone, no matrix.
    body += string("All") + struct.pack("<4IH", 1, 1, 1, 1, 0)
    count = 1 if with_lighting else 0
    body += struct.pack("<H", count)
    if count:
        body += string("LED") + word(0)
    body += struct.pack("<H", count)
    if count:
        body += word(0x00332211)
    return word(len(body) + 4) + body


class OpenRgbServer:
    def __init__(self, *, behavior="normal", descriptors=None, advertised=6, fragment=False):
        self.behavior = behavior
        self.descriptors = descriptors if descriptors is not None else [controller()]
        self.advertised = advertised
        self.fragment = fragment
        self.respond = threading.Event()
        self.respond.set()
        self.commands = []
        self.command_times = []
        self.accepted = 0
        self.disconnected = threading.Event()
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.client = None
        self.lock = threading.Lock()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Fail rather than contact or replace an existing engine on this fixed contract port.
        self.listener.bind(("127.0.0.1", 6742))
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def send(self, data):
        with self.lock:
            if self.client is None:
                return
            if self.fragment:
                for start in range(0, len(data), 3):
                    self.client.sendall(data[start:start + 3])
            else:
                self.client.sendall(data)

    def run(self):
        while not self.stop_event.is_set():
            try:
                client, _address = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self.client = client
            self.accepted += 1
            self.disconnected.clear()
            client.settimeout(0.1)
            data = b""
            try:
                while not self.stop_event.is_set():
                    try:
                        chunk = client.recv(4096)
                    except socket.timeout:
                        continue
                    if not chunk:
                        break
                    data += chunk
                    while len(data) >= 16:
                        magic, device, command, length = struct.unpack_from("<4sIII", data)
                        if magic != b"ORGB" or length > 1048576:
                            raise ValueError("Invalid client request")
                        if len(data) < 16 + length:
                            break
                        payload = data[16:16 + length]
                        data = data[16 + length:]
                        self.commands.append((device, command, payload))
                        self.command_times.append((command, time.monotonic()))
                        while not self.respond.wait(0.1) and not self.stop_event.is_set():
                            pass
                        if self.stop_event.is_set():
                            break
                        if self.behavior == "timeout":
                            continue
                        if self.behavior == "huge":
                            self.send(b"ORGB" + struct.pack("<III", 0, 40, 0xffffffff))
                        elif self.behavior == "magic":
                            self.send(b"NOPE" + struct.pack("<III", 0, 40, 4) + word(6))
                        elif self.behavior == "wrong_id":
                            self.send(packet(99, command, word(6)))
                        elif self.behavior == "wrong_command":
                            self.send(packet(0, 999, word(6)))
                        elif command == 40:
                            self.send(packet(0, 40, word(self.advertised)))
                        elif command == 0:
                            count = len(self.descriptors)
                            if self.behavior == "huge_count":
                                count = 0xffffffff
                            self.send(packet(0, 0, word(count)))
                        elif command == 1:
                            if payload != word(min(self.advertised, 1)):
                                raise ValueError("Wrong negotiated descriptor version")
                            self.send(packet(device, 1, self.descriptors[device]))
                            self.ready.set()
                        else:
                            raise ValueError("Unexpected write or engine command")
            except (OSError, ValueError):
                pass
            finally:
                client.close()
                self.client = None
                self.disconnected.set()

    def hotplug(self, descriptors):
        self.descriptors = descriptors
        self.send(packet(0, 100))

    def close(self):
        self.stop_event.set()
        self.listener.close()
        client = self.client
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(timeout=3)
