"""Synthetic sysfs USB HID nodes; these fixtures never open a device node."""
from pathlib import Path


class UsbTree:
    def __init__(self, directory):
        self.root = Path(directory)
        (self.root / "class/hidraw").mkdir(parents=True)

    def add(self, number=9, vendor="1462", product="7d98", serial="unique"):
        device = self.root / "devices" / f"usb{number}"
        device.mkdir(parents=True)
        for key, value in (("idVendor", vendor), ("idProduct", product), ("serial", serial)):
            (device / key).write_text(value + "\n")
        interface = device / "interface/hid"
        interface.mkdir(parents=True)
        node = self.root / "class/hidraw" / f"hidraw{number}"
        node.mkdir()
        (node / "device").symlink_to(interface)
        return f"usb:{vendor}:{product}:{serial}"


def rule(vendor="1462", product="7d98", name="MSI_Mystic_Light"):
    return (f'SUBSYSTEMS=="usb|hidraw", ATTRS{{idVendor}}=="{vendor}", '
            f'ATTRS{{idProduct}}=="{product}", TAG+="uaccess", TAG+="{name}"\n')
