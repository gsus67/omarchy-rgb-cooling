"""Profile storage contract, isolated from hardware and the network."""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO = Path(__file__).resolve().parents[1]


def load_helper():
    """Import bin/omarchy-rgb-profiles (no .py suffix) as a fresh module."""
    path = REPO / "bin/omarchy-rgb-profiles"
    loader = importlib.machinery.SourceFileLoader("omarchy_rgb_profiles", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "bin"))
    try:
        loader.exec_module(module)
    finally:
        sys.path.remove(str(REPO / "bin"))
    return module


def settings(name="Work"):
    return {
        "name": name,
        "power_profile": "balanced",
        "lighting": {
            "device": "openrgb:0123456789abcdef",
            "mode": "Static",
            "color": "#82fb9c",
            "brightness": 73,
            "speed": 40,
            "random": False,
        },
    }


class Profiles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rgbc-profiles-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / "config"
        self.path = self.config / "omarchy-rgb-cooling/profiles.json"
        self.environment = mock.patch.dict(
            os.environ,
            {"HOME": str(self.home), "XDG_CONFIG_HOME": str(self.config)},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.helper = load_helper()

    def execute(self, *arguments):
        return self.helper.execute(list(arguments))

    def run_cli(self, *arguments, success=True):
        # Fixed interpreter and helper paths; arguments are passed directly, never via a shell.
        completed = subprocess.run(  # noqa: S603
            [sys.executable, str(REPO / "bin/omarchy-rgb-profiles"), *arguments],
            capture_output=True,
            env=os.environ.copy(),
            text=True,
            timeout=10,
        )
        self.assertEqual(completed.returncode, 0 if success else 1,
                         completed.stderr + completed.stdout)
        return json.loads(completed.stdout)

    def test_default_is_empty_with_theme_sync_off(self):
        self.assertEqual(
            self.execute("list"),
            {"ok": True, "profiles": [], "sync_theme": False},
        )
        self.assertFalse(self.path.exists())
        self.assertEqual(
            self.execute("list", "", ""),
            {"ok": True, "profiles": [], "sync_theme": False},
        )

    def test_save_replaces_by_name_and_writes_private_atomic_file(self):
        first = settings()
        self.execute("save", first["name"], json.dumps(first))
        changed = settings()
        changed["lighting"]["brightness"] = 22
        result = self.execute("save", changed["name"], json.dumps(changed))

        self.assertEqual(result["profiles"], [changed])
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(list(self.path.parent.glob(".profiles-*")), [])
        self.assertEqual(json.loads(self.path.read_text())["profiles"], [changed])

    def test_delete_removes_only_the_named_profile(self):
        for name in ("Day", "Night"):
            value = settings(name)
            self.execute("save", name, json.dumps(value))

        result = self.execute("delete", "Day")

        self.assertEqual([item["name"] for item in result["profiles"]], ["Night"])
        with self.assertRaisesRegex(ValueError, "not found"):
            self.execute("delete", "Missing")

    def test_theme_sync_toggle_is_closed_and_persistent(self):
        self.assertTrue(self.execute("sync-theme", "on")["sync_theme"])
        self.assertTrue(self.execute("list")["sync_theme"])
        self.assertFalse(self.execute("sync-theme", "off")["sync_theme"])
        with self.assertRaisesRegex(ValueError, "Usage"):
            self.execute("sync-theme", "yes")

    def test_name_is_trimmed_bounded_and_has_no_controls(self):
        for name in ("", " leading", "trailing ", "x" * 49, "bad\nname",
                     "left\u202eright", "line\u2028break", "mark\u2066name"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "name"):
                value = settings(name)
                self.execute("save", name, json.dumps(value))

    def test_qml_three_argument_cli_forms_and_name_match(self):
        value = settings("CLI")
        saved = self.run_cli("save", "CLI", json.dumps(value))
        self.assertEqual(saved["profiles"], [value])
        self.assertTrue(self.run_cli("sync-theme", "on", "")["sync_theme"])
        self.assertEqual(self.run_cli("list", "", "")["profiles"], [value])
        self.assertEqual(self.run_cli("delete", "CLI", "")["profiles"], [])

        mismatch = settings("Payload name")
        reply = self.run_cli("save", "Argument name", json.dumps(mismatch), success=False)
        self.assertIn("does not match", reply["error"])

    def test_settings_use_closed_schema_and_finite_bounded_values(self):
        mutations = (
            ("top-level field", lambda value: value.update({"token": "secret"})),
            ("power profile", lambda value: value.update({"power_profile": "turbo"})),
            ("power profile type", lambda value: value.update({"power_profile": []})),
            ("lighting field", lambda value: value["lighting"].update({"pwm": 50})),
            ("brightness bool", lambda value: value["lighting"].update({"brightness": True})),
            ("brightness high", lambda value: value["lighting"].update({"brightness": 101})),
            ("speed low", lambda value: value["lighting"].update({"speed": -1})),
            ("bad colour", lambda value: value["lighting"].update({"color": "red"})),
            ("control in mode", lambda value: value["lighting"].update({"mode": "bad\x00mode"})),
        )
        for label, mutate in mutations:
            with self.subTest(label=label):
                value = settings()
                mutate(value)
                with self.assertRaises(ValueError):
                    self.execute("save", value["name"], json.dumps(value))

        for constant in ("NaN", "Infinity", "-Infinity"):
            payload = json.dumps(settings()).replace("73", constant, 1)
            with self.subTest(constant=constant), self.assertRaisesRegex(ValueError, "finite"):
                self.execute("save", "Work", payload)

    def test_maximum_profile_count_is_enforced(self):
        for index in range(32):
            value = settings(f"Profile {index:02d}")
            self.execute("save", value["name"], json.dumps(value))
        value = settings("One too many")
        with self.assertRaisesRegex(ValueError, "32"):
            self.execute("save", value["name"], json.dumps(value))

    def test_duplicate_keys_are_recovered_but_oversized_file_is_rejected(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"v":1,"v":1,"sync_theme":false,"profiles":[]}')
        self.assertTrue(self.execute("list")["recovered"])
        self.assertTrue(self.path.with_name("profiles.json.corrupt").exists())

        self.path.write_bytes(b" " * 262145)
        with self.assertRaisesRegex(ValueError, "256 KiB"):
            self.execute("list")

    def test_corrupt_store_is_moved_aside_and_reset_with_warning(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{")

        reply = self.execute("list")

        self.assertEqual(reply["profiles"], [])
        self.assertTrue(reply["recovered"])
        self.assertFalse(self.path.exists())
        self.assertEqual(self.path.with_name("profiles.json.corrupt").read_text(), "{")

    def test_deeply_nested_json_is_recovered_or_reported_without_traceback(self):
        self.path.parent.mkdir(parents=True)
        nested = "[" * 1200 + "0" + "]" * 1200
        self.path.write_text(nested)
        reply = self.execute("list")
        self.assertTrue(reply["recovered"])

        cli = self.run_cli("save", "Deep", nested, success=False)
        self.assertFalse(cli["ok"])
        self.assertIsInstance(cli["error"], str)

    def test_main_catches_recursion_error_as_json_failure(self):
        output = io.StringIO()
        with mock.patch.object(self.helper, "execute", side_effect=RecursionError("nested")):
            with contextlib.redirect_stdout(output):
                code = self.helper.main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {"ok": False, "error": "nested"})

    def test_stale_metadata_check_cannot_turn_symlink_into_followed_file(self):
        self.path.parent.mkdir(parents=True)
        target = self.home / "target.json"
        target.write_text('{"v":1,"sync_theme":false,"profiles":[]}')
        self.path.symlink_to(target)
        original_lstat = Path.lstat

        def stale_lstat(path):
            return target.stat() if path == self.path else original_lstat(path)

        with mock.patch.object(Path, "lstat", stale_lstat):
            with self.assertRaisesRegex(ValueError, "regular file"):
                self.execute("list")

    def test_nonregular_profile_fifo_is_rejected_without_blocking(self):
        self.path.parent.mkdir(parents=True)
        os.mkfifo(self.path)
        # Fixed interpreter and helper paths; no shell or path lookup is involved.
        completed = subprocess.run(  # noqa: S603
            [sys.executable, str(REPO / "bin/omarchy-rgb-profiles"), "list"],
            capture_output=True,
            env=os.environ.copy(),
            text=True,
            timeout=0.5,
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn("regular file", json.loads(completed.stdout)["error"])

    def test_secure_directory_rejects_links_foreign_owner_and_repairs_mode(self):
        directory = self.path.parent
        directory.parent.mkdir(parents=True)
        target = self.home / "target-directory"
        target.mkdir()
        directory.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "user-owned directory"):
            self.execute("list")
        directory.unlink()

        directory.mkdir(mode=0o755)
        self.execute("list")
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        with mock.patch.object(self.helper.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(ValueError, "user-owned directory"):
                self.execute("list")

    def test_orphaned_profile_temporary_is_removed_under_lock(self):
        self.path.parent.mkdir(parents=True)
        orphan = self.path.parent / ".profiles-abandoned"
        orphan.write_text("partial")
        self.execute("list")
        self.assertFalse(orphan.exists())

    def test_cli_waits_for_exclusive_directory_lock(self):
        self.path.parent.mkdir(parents=True, mode=0o700)
        descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, descriptor)
        self.helper.fcntl.flock(descriptor, self.helper.fcntl.LOCK_EX)
        # Fixed interpreter and helper paths; no shell or path lookup is involved.
        process = subprocess.Popen(  # noqa: S603
            [sys.executable, str(REPO / "bin/omarchy-rgb-profiles"), "list"],
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        with self.assertRaises(subprocess.TimeoutExpired):
            process.communicate(timeout=0.2)
        self.helper.fcntl.flock(descriptor, self.helper.fcntl.LOCK_UN)
        stdout, stderr = process.communicate(timeout=5)
        self.assertEqual(process.returncode, 0, stderr + stdout)
        self.assertTrue(json.loads(stdout)["ok"])

    def test_symlinked_profile_file_is_never_followed(self):
        self.path.parent.mkdir(parents=True)
        target = self.home / "target"
        target.write_text("untouched")
        self.path.symlink_to(target)

        with self.assertRaisesRegex(ValueError, "regular file"):
            self.execute("list")
        self.assertEqual(target.read_text(), "untouched")


if __name__ == "__main__":
    unittest.main()
