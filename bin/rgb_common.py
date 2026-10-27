"""Shared, read-only USB identity and opt-in validation for the RGB helpers."""
import json
import os
from pathlib import Path
import re

NAME = "omarchy-rgb-cooling"
USB = re.compile(r"usb:[0-9a-f]{4}:[0-9a-f]{4}:[^\x00-\x1f\x7f]{0,256}\Z")


def xdg(variable, fallback):
    path = Path(os.environ.get(variable) or Path.home() / fallback)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be absolute")
    return path / NAME


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(262145)
    if len(raw) > 262144:
        raise ValueError(f"{path.name} exceeds 256 KiB")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def enabled_devices():
    path = xdg("XDG_CONFIG_HOME", ".config") / "devices.json"
    try:
        value = read_json(path)
    except FileNotFoundError:
        return set()
    if (not isinstance(value, dict) or set(value) != {"v", "enabled"}
            or type(value["v"]) is not int or value["v"] != 1
            or not isinstance(value["enabled"], dict) or len(value["enabled"]) > 1024):
        raise ValueError("Invalid devices.json schema")
    for key, enabled in value["enabled"].items():
        if not USB.fullmatch(key) or type(enabled) is not bool:
            raise ValueError("Invalid devices.json USB identity or enabled value")
    return {key for key, enabled in value["enabled"].items() if enabled}


def hidraw_devices(root, *, with_paths=False):
    """Walk from each hidraw interface to its USB device, never open /dev nodes."""
    root = Path(root).resolve(strict=True)
    result = {}
    for node in sorted((root / "class/hidraw").glob("hidraw*")):
        if not re.fullmatch(r"hidraw[0-9]+", node.name):
            continue
        try:
            parent = (node / "device").resolve(strict=True)
            if not parent.is_relative_to(root):
                continue
            for ancestor in (parent, *parent.parents):
                if not ancestor.is_relative_to(root):
                    break
                if not (ancestor / "idVendor").is_file():
                    continue
                vendor = (ancestor / "idVendor").read_text().strip().lower()
                product = (ancestor / "idProduct").read_text().strip().lower()
                serial_file = ancestor / "serial"
                serial = serial_file.read_text().strip() if serial_file.exists() else ""
                identity = f"usb:{vendor}:{product}:{serial}"
                if USB.fullmatch(identity):
                    result[f"/dev/{node.name}"] = ((identity, str(ancestor))
                                                 if with_paths else identity)
                break
        except (OSError, ValueError):
            continue
    return result
