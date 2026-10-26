#!/usr/bin/env python3
"""Install into a throwaway HOME, uninstall, and fail if anything is left.

Runs bootstrap.py the way Omarchy does when the plugin loads, then
uninstall.sh, with stub `systemctl` and `omarchy` first on PATH. The stubs
behave like the real commands for the parts that touch the filesystem
(`enable` creates the WantedBy symlink, `plugin remove` deletes the plugin
folder). Two scenarios: a fresh home, and a home that already has its own user
units and sockets.target.wants, which must survive untouched.

Usage: python tests/clean_uninstall.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ID = "io.github.gsus67.omarchy-rgb-cooling"
NAME = "omarchy-rgb-cooling"

SYSTEMCTL = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = [a for a in sys.argv[1:] if a not in ("--user", "--now", "--quiet", "-q")]
with open(os.environ["STUB_LOG"], "a") as log:
    log.write("systemctl " + " ".join(sys.argv[1:]) + "\n")
units = Path(os.environ["XDG_CONFIG_HOME"]) / "systemd/user"
if args and args[0] in ("enable", "disable"):
    for unit in args[1:]:
        source = units / unit
        targets = []
        if source.exists():
            for line in source.read_text().splitlines():
                if line.strip().startswith("WantedBy="):
                    targets += line.split("=", 1)[1].split()
        for target in targets:
            link = units / (target + ".wants") / unit
            if args[0] == "enable":
                link.parent.mkdir(parents=True, exist_ok=True)
                if not link.is_symlink():
                    link.symlink_to(source)
            elif link.is_symlink():
                link.unlink()
'''

OMARCHY = r'''#!/usr/bin/env python3
import os, shutil, sys
from pathlib import Path
with open(os.environ["STUB_LOG"], "a") as log:
    log.write("omarchy " + " ".join(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["plugin", "remove"]:
    shutil.rmtree(Path(os.environ["XDG_CONFIG_HOME"]) / "omarchy/plugins" / sys.argv[3])
'''


def snapshot(home):
    """Every path under home with its type and content, ignoring the stubs."""
    result = {}
    for path in sorted(Path(home).rglob("*")):
        relative = str(path.relative_to(home))
        if relative.startswith("stubs"):
            continue
        if path.is_symlink():
            result[relative] = "link:" + os.readlink(path)
        elif path.is_dir():
            result[relative] = "dir"
        else:
            result[relative] = "file:" + path.read_bytes().hex()
    return result


def run(command, env, cwd=None):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise AssertionError(
            f"{command} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result.stdout


def scenario(name, prepare):
    with tempfile.TemporaryDirectory(prefix="rgbc-clean-") as home:
        home = Path(home)
        env = {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "XDG_RUNTIME_DIR": str(home / "run"),
            "STUB_LOG": str(home / "stubs/log"),
            "PATH": str(home / "stubs") + os.pathsep + os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
        }
        stubs = home / "stubs"
        stubs.mkdir()
        for tool, source in (("systemctl", SYSTEMCTL), ("omarchy", OMARCHY)):
            (stubs / tool).write_text(source)
            (stubs / tool).chmod(0o755)
        for directory in (".config/omarchy/plugins", ".local/state", "run"):
            (home / directory).mkdir(parents=True)
        prepare(home)
        before = snapshot(home)

        # What `omarchy plugin add` leaves: the repository in the plugins folder.
        plugin = home / ".config/omarchy/plugins" / PLUGIN_ID
        shutil.copytree(ROOT, plugin, ignore=shutil.ignore_patterns(".git", "build", "__pycache__"))
        output = run([sys.executable, str(plugin / "bootstrap.py"), str(plugin)], env)
        reply = json.loads(output.strip().splitlines()[-1])
        if reply.get("ok") is not True:
            raise AssertionError(f"bootstrap failed: {reply}")
        units = home / ".config/systemd/user"
        expected_paths = (
            units / f"{NAME}.socket",
            units / f"{NAME}.service",
            home / f".local/state/{NAME}/bin/rgbcd",
            units / f"sockets.target.wants/{NAME}.socket",
        )
        for expected in expected_paths:
            if not os.path.lexists(expected):
                raise AssertionError(f"bootstrap did not create {expected}")
        # try-restart is fine: it only restarts a service that is already running.
        for line in (home / "stubs/log").read_text().splitlines():
            words = line.split()
            if f"{NAME}.service" in words and {"enable", "start", "restart"} & set(words):
                raise AssertionError(
                    f"bootstrap must activate only the socket, never the service: {line}")

        run(["bash", str(plugin / "uninstall.sh")], env)
        after = snapshot(home)
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(p for p in set(before) & set(after) if before[p] != after[p])
        if added or removed or changed:
            raise AssertionError(
                f"{name}: left behind {added}, removed {removed}, changed {changed}")
        print(f"ok: {name}")


def fresh(home):
    pass


def existing_units(home):
    units = home / ".config/systemd/user"
    (units / "sockets.target.wants").mkdir(parents=True)
    (units / "other.socket").write_text(
        "[Socket]\nListenStream=%t/other.sock\n[Install]\nWantedBy=sockets.target\n")
    (units / "sockets.target.wants/other.socket").symlink_to(units / "other.socket")
    (home / ".config/omarchy-rgb-cooling-unrelated").write_text("keep me\n")


def main():
    scenario("fresh home", fresh)
    scenario("home with its own user units", existing_units)


if __name__ == "__main__":
    main()
