"""Minimal independent SDK v0/v1/v4/v6 server; no USB, sysfs or real engine access."""
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


def signal_update(device, reason, description):
    # REQ_DATA has a size prefix; SIGNALUPDATE replaces it with size + reason.
    body = word(reason) + (description if reason == 0 else description[4:])
    return packet(device, 1150, word(len(body) + 4) + body)


def mode(name="Static", *, flags=16 | 32 | 256, brightness=75, colors=None,
         minimum=10, maximum=90, color_mode=1, colors_min=1, colors_max=4,
         speed_min=0, speed_max=0, speed=0, value=0):
    return {"name": name, "value": value, "flags": flags, "speed_min": speed_min,
            "speed_max": speed_max,
            "brightness_min": minimum, "brightness_max": maximum,
            "colors_min": colors_min, "colors_max": colors_max, "speed": speed,
            "brightness": brightness, "direction": 0, "color_mode": color_mode,
            "colors": [0x00332211] if colors is None else colors}


def mode_bytes(value, version=6):
    body = string(value["name"])
    if version < 6:
        body += word(value["value"])
    fields = ["flags", "speed_min", "speed_max"]
    if version >= 3:
        fields += ["brightness_min", "brightness_max"]
    fields += ["colors_min", "colors_max", "speed"]
    if version >= 3:
        fields += ["brightness"]
    fields += ["direction", "color_mode"]
    body += b"".join(word(value[field]) for field in fields)
    return body + struct.pack("<H", len(value["colors"])) + b"".join(
        word(color) for color in value["colors"])


def msi_modes():
    """Real MSI descriptors sampled read-only with OpenRGB 1.1 / protocol 4.

    Keep original indices for the sampled modes; unobserved slots are deliberately
    neutral placeholders rather than invented hardware capabilities.
    """
    modes = [mode(f"Unobserved {index}", flags=0x10, color_mode=0)
             for index in range(23)]
    for index, name, flags, color_mode in (
            (0, "Direct", 0x0020, 1), (1, "Static", 0x0130, 1),
            (2, "Breathing", 0x0131, 1), (3, "Flashing", 0x01b1, 1),
            (7, "Color ring", 0x0191, 3), (17, "Rainbow wave", 0x0191, 3),
            (22, "Fire", 0x0191, 3)):
        modes[index] = mode(name, flags=flags, color_mode=color_mode,
                            speed_max=2 if flags & 1 else 0, value=index)
    return modes


def controller(name="MSI RGB", location="HID: /dev/hidraw9", serial="unique", version=6,
               with_lighting=True, modes=None, active=0, led_colors=None,
               vendor="MSI", description="USB lighting", firmware="1.0"):
    # Independent fixture including v6 zone/segment/display/configuration extensions.
    if modes is None:
        modes = [mode("Direct", flags=32), mode(flags=16 | 64 | 256, color_mode=2)]
    body = word(0) + string(name)
    if version >= 1:
        body += string(vendor)
    body += string(description) + string(firmware) + string(serial) + string(location)
    body += struct.pack("<HI", len(modes), active)
    body += b"".join(mode_bytes(value, version) for value in modes)
    body += struct.pack("<H", 1)
    body += string("All") + struct.pack("<4IH", 1, 1, 1, 1, 0)
    if version >= 4:
        body += struct.pack("<H", 1) + string("Segment") + struct.pack("<3I", 1, 0, 1)
    if version >= 6:
        body += struct.pack("<HI", 0, 0)  # Segment matrix and flags.
    if version >= 5:
        body += word(0)  # Zone flags.
    if version >= 6:
        body += struct.pack("<IH", 0, 0) + string("")
    if led_colors is None:
        led_colors = [0x00332211] if with_lighting else []
    count = len(led_colors)
    body += struct.pack("<H", count)
    for _ in led_colors:
        body += string("LED")
        if version < 6:
            body += word(0)
    body += struct.pack("<H", count)
    body += b"".join(word(color) for color in led_colors)
    if version >= 5:
        body += struct.pack("<H", 0) + word(0)
    if version >= 6:
        body += string("") + word(3) + b"{}\0"
    return word(len(body) + 4) + body


def controller_metadata(descriptor, *, version=6, **changes):
    """Change only SDK metadata, retaining the mode/LED buffers after real writes."""
    offset = 8
    fields = ["name", "vendor", "description", "firmware", "serial", "location"]
    body = descriptor[4:8]
    for field in fields:
        if field == "vendor" and version == 0:
            continue
        length, = struct.unpack_from("<H", descriptor, offset)
        end = offset + 2 + length
        body += string(changes[field]) if field in changes else descriptor[offset:end]
        offset = end
    body += descriptor[offset:]
    return word(len(body) + 4) + body


def apply_mode(descriptor, payload, *, version=6, ignore_brightness=False):
    """Apply precisely UPDATEMODE v4/v6 to the fake's descriptor, without hardware."""
    size, chosen = struct.unpack_from("<II", payload)
    if size != len(payload):
        raise ValueError("Wrong UPDATEMODE length")
    offset = 8
    for _ in range(6):
        length, = struct.unpack_from("<H", descriptor, offset)
        offset += 2 + length
    count, active = struct.unpack_from("<HI", descriptor, offset)
    active_offset = offset + 2
    offset += 6
    ranges = []
    for _ in range(count):
        start = offset
        length, = struct.unpack_from("<H", descriptor, offset)
        offset += 2 + length + (44 if version >= 6 else 48)
        colors, = struct.unpack_from("<H", descriptor, offset)
        offset += 2 + colors * 4
        ranges.append((start, offset))
    if chosen >= count:
        raise ValueError("Invalid mode index")
    name_length, = struct.unpack_from("<H", payload, 8)
    color_offset = 8 + 2 + name_length + (44 if version >= 6 else 48)
    colors, = struct.unpack_from("<H", payload, color_offset)
    if len(payload) != color_offset + 2 + 4 * colors:
        raise ValueError("Wrong mode color count")
    start, end = ranges[chosen]
    replacement = bytearray(payload[8:])
    if ignore_brightness:
        offset = 2 + name_length + (8 if version >= 6 else 9) * 4
        replacement[offset:offset + 4] = descriptor[start + offset:start + offset + 4]
    changed = bytearray(descriptor[:start] + replacement + descriptor[end:])
    struct.pack_into("<I", changed, active_offset, chosen)
    # OpenRGB 1.1 SetModeValuesFromMode updates mode.colors only. In particular,
    # UPDATEMODE does NOT change the controller's per-LED colour buffer.
    struct.pack_into("<I", changed, 0, len(changed))
    return bytes(changed)


def apply_leds(descriptor, payload, version=6):
    """Apply UPDATELEDS to the v4/v6 fixture, validating its LED count and uniformity."""
    size, count = struct.unpack_from("<IH", payload)
    if size != len(payload) or size != 6 + 4 * count or not 1 <= count <= 4096:
        raise ValueError("Wrong UPDATELEDS length")
    values = struct.unpack_from(f"<{count}I", payload, 6)
    if len(set(values)) != 1:
        raise ValueError("Only uniform LED buffers are allowed")
    # This fixture's v6 trailer: no LED names, flags=0, empty display name, config={};
    # immediately before it are the LED descriptors and the controller colour buffer.
    trailer = struct.pack("<HI", 0, 0) + string("") + word(3) + b"{}\0"
    if version < 6:
        trailer = struct.pack("<HI", 0, 0) if version >= 5 else b""
    if not descriptor.endswith(trailer):
        raise ValueError("Unexpected fake controller trailer")
    offset = len(descriptor) - len(trailer) - 4 * count
    actual, = struct.unpack_from("<H", descriptor, offset - 2)
    led_offset = offset - 2 - count * (len(string("LED")) + (4 if version < 6 else 0)) - 2
    leds, = struct.unpack_from("<H", descriptor, led_offset)
    if actual != count or leds != count:
        raise ValueError("UPDATELEDS must match the controller's LED count")
    return descriptor[:offset] + payload[6:] + descriptor[offset + 4 * count:]


class OpenRgbServer:
    def __init__(self, *, behavior="normal", descriptors=None, advertised=6, fragment=False,
                 listener=None, device_ids=None, defer_listen=False, updates="after"):
        self.behavior = behavior
        self.descriptors = descriptors if descriptors is not None else [controller()]
        self.advertised = advertised
        self.device_ids = device_ids
        self.fragment = fragment
        self.updates = updates
        self.respond = threading.Event()
        self.respond.set()
        self.commands = []
        self.sent = []
        self.saved_modes = {}
        self.command_times = []
        self.accepted = 0
        self.disconnected = threading.Event()
        self.stop_event = threading.Event()
        self.listening = threading.Event()
        self.ready = threading.Event()
        self.client = None
        self.lock = threading.Lock()
        self.listener = listener or socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if listener is None:
            self.listener.bind(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.listener.settimeout(0.1)
        if not defer_listen:
            self.start_listening()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def start_listening(self):
        self.listener.listen(8)
        self.listening.set()

    def send(self, data):
        with self.lock:
            if self.client is None:
                return
            self.sent.append(data)
            if self.fragment:
                for start in range(0, len(data), 3):
                    self.client.sendall(data[start:start + 3])
            else:
                self.client.sendall(data)

    def run(self):
        while not self.listening.wait(0.1):
            if self.stop_event.is_set():
                return
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
            updates = []
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
                            if self.advertised >= 6:
                                self.send(packet(0, 51, b"OpenRGB 1.1\0"))
                                self.send(packet(0, 10, word(40) + word(0)))
                        elif command == 0:
                            count = len(self.descriptors)
                            if self.behavior == "huge_count":
                                count = 0xffffffff
                            ids = self.device_ids or list(range(len(self.descriptors)))
                            suffix = b"".join(word(value) for value in ids)
                            self.send(packet(0, 0, word(count)
                                             + (suffix if self.advertised >= 6 else b"")))
                            if self.advertised >= 6:
                                self.send(packet(0, 10, word(0) + word(0)))
                        elif command == 1:
                            expected = b"" if self.advertised >= 6 else word(self.advertised)
                            if payload != expected:
                                raise ValueError("Wrong negotiated descriptor version")
                            ids = self.device_ids or list(range(len(self.descriptors)))
                            self.send(packet(device, 1, self.descriptors[ids.index(device)]))
                            if self.advertised >= 6:
                                self.send(packet(device, 10, word(1) + word(0)))
                            for update in updates:
                                self.send(update)
                            updates.clear()
                            self.ready.set()
                        elif command in (1101, 1050, 1102):
                            ids = self.device_ids or list(range(len(self.descriptors)))
                            index = ids.index(device)
                            rejected = self.behavior == "write_rejected" or (
                                command == 1050 and self.behavior == "led_write_rejected")
                            ignored = self.behavior == "write_ignored" or (
                                command == 1050 and self.behavior == "led_write_ignored")
                            if not rejected and not ignored:
                                if command == 1101:
                                    self.descriptors[index] = apply_mode(
                                        self.descriptors[index], payload, version=self.advertised,
                                        ignore_brightness=self.behavior == "brightness_ignored")
                                elif command == 1050:
                                    self.descriptors[index] = apply_leds(
                                        self.descriptors[index], payload, self.advertised)
                                else:
                                    apply_mode(self.descriptors[index], payload,
                                               version=self.advertised)
                                    self.saved_modes[device] = payload
                            status = 3 if rejected else 0
                            ack = word(command) + word(status)
                            if self.behavior == "bad_write_ack" or (
                                    command == 1050 and self.behavior == "bad_led_ack"):
                                ack = ack[:-1]
                            if self.advertised >= 6 and (command != 1050
                                    or self.behavior != "missing_led_ack"):
                                self.send(packet(device, 10, ack))
                            if self.advertised >= 6 and not rejected and not ignored:
                                reason = {1050: 0, 1101: 1, 1102: 2}[command]
                                description = (payload[4:] if command == 1050
                                               else self.descriptors[index])
                                update = signal_update(device, reason, description)
                                if self.updates == "after":
                                    updates.append(update)
                                elif self.updates == "before":
                                    self.send(update)
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
        self.thread.join(timeout=30)
        if self.thread.is_alive():
            raise AssertionError("Fake OpenRGB thread did not stop within 30s")
