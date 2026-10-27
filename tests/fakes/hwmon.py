"""A fake class tree with canonical device parents and observable file access."""
import ctypes
import hashlib
import os
from pathlib import Path
import struct


class HwmonTree:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.root = self.directory / "class/hwmon"
        self.root.mkdir(parents=True)
        self.cpu = self.add("hwmon8", "coretemp", "platform/coretemp.0", {
            "temp1_label": "Package id 0", "temp1_input": "42500",
            "temp2_label": "Core 0", "temp2_input": "39000",
        })
        self.gpu = self.add("hwmon3", "amdgpu", "pci0000:00/0000:03:00.0", {
            "temp1_label": "edge", "temp1_input": "46000", "fan1_input": "0",
            "pwm1": "38", "pwm1_enable": "2",
        })

    def add(self, number, name, parent, files):
        device = self.directory / "devices" / parent
        device.mkdir(parents=True, exist_ok=True)
        node = device / "hwmon" / number
        node.mkdir(parents=True)
        (node / "name").write_text(name + "\n")
        for filename, value in files.items():
            (node / filename).write_text(value + "\n")
        (node / "device").symlink_to(device, target_is_directory=True)
        (self.root / number).symlink_to(node, target_is_directory=True)
        return node

    def add_mdio_ethernet(self, number="hwmon30"):
        return self.add(number, "r8169_0_600:00", "platform/mdio_bus/0/0-0000:00:00.0", {
            "temp1_input": "47000",
        })

    def snapshot(self):
        return {str(path.relative_to(self.directory)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.directory.rglob("*") if path.is_file()}


class FileWatch:
    """Expose real kernel inotify observations without third-party Python packages."""
    def __init__(self, path):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.fd = self.libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        # ACCESS, MODIFY, ATTRIB, CLOSE_WRITE, OPEN: distinguish reads from writes.
        self.libc.inotify_add_watch.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32)
        if self.libc.inotify_add_watch(self.fd, os.fsencode(path), 0x3f) < 0:
            self.close()
            raise OSError(ctypes.get_errno(), "inotify_add_watch")

    def drain(self):
        masks = []
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                break
            offset = 0
            while offset < len(data):
                _watch, mask, _cookie, length = struct.unpack_from("iIII", data, offset)
                masks.append(mask)
                offset += 16 + length
        return masks

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
