"""Shared, read-only USB identity and opt-in validation for the RGB helpers."""
import errno
import json
import os
from pathlib import Path
import re
import stat
import tempfile

NAME = "omarchy-rgb-cooling"
USB = re.compile(r"usb:[0-9a-f]{4}:[0-9a-f]{4}:[^\x00-\x1f\x7f]{0,256}\Z")


class JsonFileError(ValueError):
    """The path is unsafe or violates the bounded-file contract."""


class JsonFormatError(ValueError):
    """The opened file does not contain accepted JSON."""


def xdg(variable, fallback):
    path = Path(os.environ.get(variable) or Path.home() / fallback)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be absolute")
    return path / NAME


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise JsonFormatError("Duplicate JSON key")
        result[key] = value
    return result


def parse_constant(_value):
    raise JsonFormatError("JSON numbers must be finite")


def read_json(path):
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise JsonFileError(f"{path.name} must be a regular file") from error
        raise
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise JsonFileError(f"{path.name} must be a regular file")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            raw = stream.read(262145)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(raw) > 262144:
        raise JsonFileError(f"{path.name} exceeds 256 KiB")
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                          parse_constant=parse_constant)
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as error:
        raise JsonFormatError(f"Invalid JSON in {path.name}") from error


def secure_directory(path):
    """Create a private user directory and reject links or foreign owners."""
    try:
        path.mkdir(mode=0o700, parents=True)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if (not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid()):
        raise ValueError(f"{path.name} must be a user-owned directory")
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        os.chmod(path, 0o700, follow_symlinks=False)


def atomic_write_json(path, value, *, prefix=".staging-"):
    """Atomically replace one private JSON file and sync its directory."""
    secure_directory(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix=prefix, dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


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
