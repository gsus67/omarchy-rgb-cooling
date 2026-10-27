"""Engine ownership and bubblewrap contract, with no package or hardware access."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
import contextlib
import importlib.machinery
import importlib.util
import io
import types
from unittest import mock

from fakes.usb import UsbTree

REPO = Path(__file__).resolve().parents[1]



def load_launcher():
    """Import bin/omarchy-rgb-openrgb (no .py suffix) as a fresh module."""
    path = REPO / "bin/omarchy-rgb-openrgb"
    loader = importlib.machinery.SourceFileLoader("omarchy_rgb_openrgb", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO / "bin"))
    try:
        loader.exec_module(module)
    finally:
        sys.path.remove(str(REPO / "bin"))
    return module

class Helpers(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rgbc-helpers-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.stubs = self.home / "stubs"
        self.stubs.mkdir()
        self.env = {**os.environ, "HOME": str(self.home), "PATH": str(self.stubs),
                    "XDG_CONFIG_HOME": str(self.home / "config"),
                    "XDG_STATE_HOME": str(self.home / "state"),
                    "RGB_TEST_HOME": str(self.home)}
        self.record = self.home / "state/omarchy-rgb-cooling/engines.json"
        self.log = self.home / "log"
        self.stub("pacman", '''
import json, os, sys
from pathlib import Path
root = Path(os.environ['RGB_TEST_HOME'])
args = sys.argv[1:]
with (root/'log').open('a') as log:
    log.write(json.dumps(['pacman', *args])+'\\n')
if args[0] == '-Q':
    if not (root/'installed').exists():
        sys.exit(1)
    print('openrgb 1.1-1')
else:
    if not (root/'installed').exists():
        print('new-dependency\\nopenrgb')
''')
        self.stub("pkexec", '''
import json, os, sys
from pathlib import Path
root = Path(os.environ['RGB_TEST_HOME'])
with (root/'log').open('a') as log:
    log.write(json.dumps(['pkexec', *sys.argv[1:]])+'\\n')
if os.environ.get('CANCEL'):
    sys.exit(126)
if '-S' in sys.argv:
    (root/'installed').touch()
else:
    (root/'installed').unlink(missing_ok=True)
''')

    def stub(self, name, code):
        path = self.stubs / name
        path.write_text(f"#!{sys.executable}\n" + code)
        path.chmod(0o700)

    def run_helper(self, *args, success=True):
        result = subprocess.run([sys.executable, str(REPO / "bin/omarchy-rgb-engines"), *args],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0 if success else 1, result.stderr + result.stdout)
        return json.loads(result.stdout)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_new_install_records_plan_before_pkexec_atomic_0600_and_status(self):
        self.assertTrue(self.run_helper("install", "openrgb")["ok"])
        self.assertEqual(self.commands(), [
            ["pacman", "-Q", "openrgb"],
            ["pacman", "-S", "--print", "--print-format", "%n", "--needed", "openrgb"],
            ["pkexec", "/usr/bin/pacman", "-S", "--needed", "--noconfirm", "openrgb"],
        ])
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode), 0o600)
        entry = json.loads(self.record.read_text())["engines"]["openrgb"]
        self.assertTrue(entry["installed_by_plugin"])
        self.assertEqual(entry["packages"], ["openrgb"])
        self.assertEqual(entry["new_dependencies"], ["new-dependency"])
        self.assertTrue(entry["installed_at"])
        self.assertEqual(list(self.record.parent.glob(".engines-*")), [])
        status = self.run_helper("status")["engines"][0]
        self.assertTrue(status["installed"])
        self.assertTrue(status["installed_by_plugin"])
        self.assertEqual(status["version"], "1.1-1")
        self.assertEqual(status["size"], "9.5 MiB")
        self.assertTrue(status["purpose"])

    def test_preexisting_package_is_never_marked_or_uninstalled(self):
        (self.home / "installed").touch()
        self.run_helper("install", "openrgb")
        self.assertFalse(self.record.exists())
        self.assertFalse(self.run_helper("status")["engines"][0]["installed_by_plugin"])
        before = self.commands()
        self.run_helper("uninstall", "openrgb", success=False)
        self.assertEqual(self.commands(), before)

    def test_cancelled_install_and_uninstall_preserve_record_byte_for_byte(self):
        self.env["CANCEL"] = "1"
        self.run_helper("install", "openrgb", success=False)
        self.assertFalse(self.record.exists())
        self.env.pop("CANCEL")
        self.run_helper("install", "openrgb")
        before = self.record.read_bytes(), self.record.stat().st_ino
        self.env["CANCEL"] = "1"
        self.run_helper("uninstall", "openrgb", success=False)
        self.assertEqual((self.record.read_bytes(), self.record.stat().st_ino), before)

    def test_existing_real_record_shape_preserves_additional_fields_on_reinstall(self):
        self.run_helper("install", "openrgb")
        value = json.loads(self.record.read_text())
        value["engines"]["openrgb"]["note"] = "User's existing installation"
        self.record.write_text(json.dumps(value))
        before = self.record.read_bytes()
        self.run_helper("install", "openrgb")
        self.assertEqual(self.record.read_bytes(), before)
        self.run_helper("uninstall", "openrgb")
        self.assertEqual(self.commands()[-1],
                         ["pkexec", "/usr/bin/pacman", "-Rns", "--noconfirm", "openrgb"])
        self.assertEqual(json.loads(self.record.read_text()), {"v": 1, "engines": {}})

    def test_uninstall_all_only_plugin_owned_and_is_idempotent(self):
        self.run_helper("uninstall-all")
        self.assertFalse(self.log.exists())
        self.run_helper("install", "openrgb")
        self.run_helper("uninstall-all")
        before = self.commands()
        self.run_helper("uninstall-all")
        self.assertEqual(self.commands(), before)
        self.assertFalse((self.home / "installed").exists())

    def test_closed_commands_and_names_rejected_before_any_side_effect(self):
        for args in ([], ["install"], ["install", "--help"], ["install", "other"],
                     ["uninstall", "openrgb;id"], ["status", "openrgb"], ["wat"]):
            with self.subTest(args=args):
                self.run_helper(*args, success=False)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.record.parent.exists())

    def test_uninstall_all_skips_explicit_external_ownership_record(self):
        self.run_helper("install", "openrgb")
        value = json.loads(self.record.read_text())
        value["engines"]["openrgb"]["installed_by_plugin"] = False
        self.record.write_text(json.dumps(value))
        before = self.record.read_bytes(), self.commands()
        self.run_helper("uninstall-all")
        self.assertEqual((self.record.read_bytes(), self.commands()), before)

    def test_openrgb_unit_verifies_and_meets_security_threshold_offline(self):
        config = self.home / "openrgb"
        config.mkdir()
        unit = self.home / "omarchy-rgb-cooling-openrgb.service"
        content = (REPO / "systemd" / unit.name).read_text()
        content = content.replace("@OPENRGB LAUNCHER@",
                                  '"' + str(REPO / "bin/omarchy-rgb-openrgb") + '"')
        content = content.replace("@OPENRGB CONFIG@", '"' + str(config) + '"')
        unit.write_text(content)
        self.assertNotIn("[Install]", content)
        self.assertIn("NoNewPrivileges=yes", content)
        self.assertIn("PrivateTmp=no", content)
        self.assertIn("ProtectSystem=strict", content)
        # bwrap rules out PrivateTmp/ProtectHostname/ProtectKernelLogs (see the unit).
        # Security is scored as the user unit it is; systemd needs a runtime
        # directory for that, which a CI container without a session lacks.
        runtime = self.home / "runtime"
        runtime.mkdir(mode=0o700)
        commands = (["systemd-analyze", "verify", str(unit)],
                    ["systemd-analyze", "--user", "--offline=yes", "security",
                     "--threshold=32", str(unit)])
        for command in commands:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30,
                                    env=dict(os.environ, XDG_RUNTIME_DIR=str(runtime)))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def launcher(self, *, success=True):
        """Run the launcher in-process with its fixed binaries pointed at test stubs.

        The launcher has no way to change BWRAP/OPENRGB from outside (no PATH
        lookup, no environment override); only the test swaps the module
        constants, and os.execv is captured instead of replacing the process.
        """
        module = load_launcher()
        module.BWRAP = str(self.stubs / "bwrap")
        module.OPENRGB = str(self.stubs / "openrgb")
        executed = []
        stderr = io.StringIO()
        environment = {key: value for key, value in self.env.items()}
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(module.os, "execv", lambda path, argv: executed.append(argv)), \
                mock.patch.object(sys, "argv", ["omarchy-rgb-openrgb", "--sys-root",
                                                str(self.usb.root)]), \
                contextlib.redirect_stderr(stderr):
            code = module.main()
        self.assertEqual(code or 0, 0 if success else 1, stderr.getvalue())
        if executed:
            (self.home / "bwrap.json").write_text(json.dumps(executed[0][1:]))
        return types.SimpleNamespace(stderr=stderr.getvalue(), argv=executed)

    def prepare_launcher(self, enabled):
        self.usb = UsbTree(self.home / "sys")
        config = self.home / "config/omarchy-rgb-cooling"
        config.mkdir(parents=True)
        (config / "devices.json").write_text(json.dumps({"v": 1, "enabled": enabled}))
        self.stub("openrgb", "raise AssertionError('OpenRGB must never be executed by tests')")
        self.stub("bwrap", '''
import json, os, sys
from pathlib import Path
Path(os.environ['RGB_TEST_HOME'], 'bwrap.json').write_text(json.dumps(sys.argv[1:]))
''')

    def test_launcher_exact_bwrap_vector_only_enabled_usb_hid(self):
        self.prepare_launcher({"usb:1462:7d98:unique": True})
        self.usb.add()
        self.usb.add(10, "1234", "abcd", "other")
        self.usb.add(11, "0416", "5302", "trofeo")
        self.launcher()
        config = str(self.home / "state/omarchy-rgb-cooling/openrgb")
        args = ["--unshare-all", "--share-net", "--die-with-parent", "--new-session"]
        for path in ("/usr", "/etc", "/sys", "/run/udev"):
            args += ["--ro-bind", path, path]
        for name in ("lib", "lib64", "bin", "sbin"):
            args += ["--symlink", "usr/" + name, "/" + name]
        args += ["--proc", "/proc", "--dev", "/dev", "--dev-bind", "/dev/hidraw9",
                 "/dev/hidraw9", "--tmpfs", "/tmp", "--bind", config, config,
                 "--setenv", "QT_QPA_PLATFORM", "offscreen", "--setenv", "HOME", config,
                 str(self.stubs / "openrgb"), "--server", "--server-host", "127.0.0.1",
                 "--server-port",
                 "6742", "--noautoconnect", "--config", config, "--loglevel", "warning"]
        self.assertEqual(json.loads((self.home / "bwrap.json").read_text()), args)

    def test_launcher_binaries_are_fixed_system_paths(self):
        # Regression: resolving bwrap/openrgb through PATH let an impostor run.
        module = load_launcher()
        self.assertEqual(module.BWRAP, "/usr/bin/bwrap")
        self.assertEqual(module.OPENRGB, "/usr/bin/openrgb")
        self.assertNotIn("shutil.which", (REPO / "bin/omarchy-rgb-openrgb").read_text())

    def test_launcher_rejects_trofeo_even_if_explicitly_enabled(self):
        self.prepare_launcher({"usb:0416:5302:trofeo": True})
        self.usb.add(9, "0416", "5302", "trofeo")
        self.assertIn("omarchy-trcc", self.launcher(success=False).stderr)
        self.assertFalse((self.home / "bwrap.json").exists())

    def test_launcher_no_devices_duplicates_nonusb_and_missing_binaries(self):
        self.prepare_launcher({"usb:1462:7d98:unique": True})
        interface = self.usb.root / "devices/nonusb/hid"
        interface.mkdir(parents=True)
        node = self.usb.root / "class/hidraw/hidraw1"
        node.mkdir()
        (node / "device").symlink_to(interface)
        self.assertIn("No enabled", self.launcher(success=False).stderr)
        self.usb.add()
        self.usb.add(10)
        self.assertIn("uniquely", self.launcher(success=False).stderr)
        for name in ("bwrap", "openrgb"):
            path = self.stubs / name
            path.rename(path.with_suffix(".hidden"))
            self.assertIn(f"{path} is required", self.launcher(success=False).stderr)
            path.with_suffix(".hidden").rename(path)

    def test_launcher_allows_multiple_interfaces_of_the_same_physical_usb(self):
        self.prepare_launcher({"usb:1462:7d98:unique": True})
        self.usb.add()
        node = self.usb.root / "class/hidraw/hidraw12"
        node.mkdir()
        (node / "device").symlink_to(self.usb.root / "devices/usb9/interface/hid")
        self.launcher()
        args = json.loads((self.home / "bwrap.json").read_text())
        self.assertEqual(args.count("--dev-bind"), 2)
        self.assertIn("/dev/hidraw9", args)
        self.assertIn("/dev/hidraw12", args)

    def test_launcher_invalid_config_fails_closed(self):
        self.prepare_launcher({"usb:1462:7d98:unique": True})
        self.usb.add()
        path = self.home / "config/omarchy-rgb-cooling/devices.json"
        for value in ('{"v":1,"enabled":{"usb:1462:7d98:unique":1}}',
                      '{"v":1,"v":1,"enabled":{}}', '{"v":true,"enabled":{}}'):
            path.write_text(value)
            self.launcher(success=False)
        self.assertFalse((self.home / "bwrap.json").exists())


if __name__ == "__main__":
    unittest.main()
