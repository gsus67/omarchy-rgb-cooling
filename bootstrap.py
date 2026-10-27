#!/usr/bin/env python3
"""Prepare the socket-activated core and record the complete installation footprint."""
# SPDX-License-Identifier: GPL-3.0-or-later
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
import native_build

NAME = "omarchy-rgb-cooling"
PLACEHOLDER = "@RGB CD BINARY@"


def quote(value):
    """Quote a literal systemd argument, including specifier escaping."""
    value = str(value)
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError("Installation paths must not contain control characters")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def xdg_path(variable, default):
    """Require absolute paths so the ledger and unit never depend on cwd."""
    path = Path(os.environ.get(variable) or default)
    quote(path)
    if not path.is_absolute():
        raise ValueError(f"{variable} must be an absolute path")
    return path


def atomic_write(path, content, mode=0o600):
    """Replace a file on the same filesystem; remove failed staging files."""
    if (path.is_file() and path.read_text(encoding="utf-8") == content
            and path.stat().st_mode & 0o777 == mode):
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".staging-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def make_directory(path, entries):
    """Record only directories created by this installation, with a final slash."""
    if path.is_dir():
        return
    make_directory(path.parent, entries)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if not path.is_dir():
            raise
    else:
        entries.add(str(path) + "/")


def systemctl(*arguments):
    """Use PATH deliberately, allowing isolated tests to supply a stub."""
    native_build.run("systemctl", "--user", *arguments)


def user_directory(path):
    """Keep user data outside the ledger; never chmod a symlink or another owner's data."""
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        pass
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        return
    if stat.S_IMODE(metadata.st_mode) != 0o700:
        os.chmod(path, 0o700, follow_symlinks=False)


def ensure(source):
    """Build under flock and activate only the socket when the installation changes."""
    source = Path(source).resolve()
    quote(source)
    if not (source / "src/main.cpp").is_file():
        raise ValueError("Plugin core sources were not found")
    if shutil.which("systemctl") is None:
        raise RuntimeError("systemctl is required")
    state_home = xdg_path("XDG_STATE_HOME", Path.home() / ".local/state")
    config = xdg_path("XDG_CONFIG_HOME", Path.home() / ".config")
    xdg_path("XDG_RUNTIME_DIR", Path(f"/run/user/{os.getuid()}"))
    state = state_home / NAME
    ledger = state / "installed-files"
    entries = set()
    make_directory(state, entries)
    # Preserve directories made before taking the lock, including after a failed build.
    created_directories = entries.copy()
    lock_path = state / ".bootstrap.lock"
    with lock_path.open("a", encoding="utf-8") as lock:
        if lock_path.stat().st_mode & 0o777 != 0o600:
            os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        if ledger.is_file():
            entries.update(ledger.read_text(encoding="utf-8").splitlines())
        entries.update(created_directories)
        entries.update((str(lock_path), str(ledger)))
        try:
            return install(source, state, config, entries)
        finally:
            atomic_write(ledger, "\n".join(sorted(entries)) + "\n")


def install(source, state, config, entries):
    """Install exactly the contracted files; staging directories are temporary."""
    tools = native_build.discover()
    fingerprint = native_build.fingerprint(source, tools)
    marker = state / ".core-version"
    binary = state / "bin/rgbcd"
    entries.update((str(marker), str(binary)))
    make_directory(binary.parent, entries)
    # Only the lock owner may clean an interrupted compiler's temporary output.
    for stale in state.glob("build-*"):
        if stale.is_dir() and not stale.is_symlink():
            shutil.rmtree(stale)
    changed = (not binary.is_file() or not marker.is_file()
               or marker.read_text(encoding="utf-8") != fingerprint)
    if changed:
        with tempfile.TemporaryDirectory(prefix="build-", dir=state) as temporary:
            compiled = native_build.build(source, temporary, tools=tools)
            os.replace(compiled, binary)
    unit_dir = config / "systemd/user"
    make_directory(unit_dir, entries)
    user_directory(config / NAME)
    for suffix in ("socket", "service", "openrgb.service"):
        name = (f"{NAME}-openrgb.service" if suffix == "openrgb.service"
                else f"{NAME}.{suffix}")
        destination = unit_dir / name
        content = (source / "systemd" / name).read_text(encoding="utf-8")
        if suffix == "service":
            if content.count(PLACEHOLDER) != 1:
                raise ValueError("Service template must contain exactly one executable placeholder")
            command = quote(binary) + " --data-dir " + quote(source / "data")
            content = content.replace(PLACEHOLDER, command)
        if suffix == "openrgb.service":
            rgb_config = state / "openrgb"
            make_directory(rgb_config, entries)
            content = content.replace("@OPENRGB LAUNCHER@",
                                      quote(source / "bin/omarchy-rgb-openrgb"))
            content = content.replace("@OPENRGB CONFIG@", quote(rgb_config))
        entries.add(str(destination))
        if not destination.is_file() or destination.read_text(encoding="utf-8") != content:
            atomic_write(destination, content)
            changed = True
    wants = unit_dir / "sockets.target.wants"
    make_directory(wants, entries)
    enablement = wants / f"{NAME}.socket"
    entries.add(str(enablement))
    # Commit the ledger before commands which can fail or be interrupted.
    atomic_write(state / "installed-files", "\n".join(sorted(entries)) + "\n")
    if changed:
        # A failed activation must be retried on the next bootstrap. Publish the
        # fingerprint only after all systemctl operations have succeeded.
        marker.unlink(missing_ok=True)
        systemctl("daemon-reload")
        systemctl("enable", "--now", f"{NAME}.socket")
        systemctl("try-restart", f"{NAME}.service")
        atomic_write(marker, fingerprint)
    return {"ok": True}


def main():
    def terminate(signum, _frame):
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        source = sys.argv[1] if len(sys.argv) == 2 else Path(__file__).parent
        if len(sys.argv) > 2:
            raise ValueError("Usage: bootstrap.py <plugin dir>")
        result = ensure(source)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
