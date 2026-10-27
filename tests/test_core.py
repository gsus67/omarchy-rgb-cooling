"""API.md contract regressions; stdlib-only and isolated from the user's hardware."""
# SPDX-License-Identifier: GPL-3.0-or-later
import errno
import json
import os
from pathlib import Path
import select
import shlex
import shutil
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fakes.hwmon import FileWatch, HwmonTree
from fakes.dmi import DmiTree
from fakes.openrgb import OpenRgbServer, controller
from fakes.usb import UsbTree
from rgb_contract import OpenRgbContractMixin

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BUILD_DIRECTORY = None
BINARY = None
PEERCRED_LIBRARY = None
UDEV_LIBRARY = None
RUNTIME_LIBRARY = None
POWER_PROFILES_FAKE = None
SYSTEMD_FAKE = None
WAIT_TIMEOUT = 30


def wait_until(predicate, timeout=WAIT_TIMEOUT, *, message):
    """Return the first truthy observation, or fail with the condition and last value."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"Timed out after {timeout}s: {message}; last value: {value!r}")
        time.sleep(min(0.02, remaining))


def wait_event(client, topic, predicate, *, message, timeout=WAIT_TIMEOUT):
    deadline = time.monotonic() + timeout

    def matching_event():
        try:
            event = client.event(topic, timeout=max(0.001, deadline - time.monotonic()))
        except AssertionError as error:
            raise AssertionError(f"Timed out: {message}") from error
        return event if predicate(event["data"]) else None

    return wait_until(matching_event, timeout, message=message)["data"]


class TestClock:
    """Freeze only the daemon clock; client deadlines always use real monotonic time."""
    def __init__(self, directory):
        self.path = Path(directory) / "clock"
        self.nanoseconds = 100_000_000_000
        self.real_started = 0
        self.write()

    def write(self):
        temporary = self.path.with_suffix(".new")
        temporary.write_bytes(struct.pack("qq", self.nanoseconds, self.real_started))
        temporary.replace(self.path)

    def advance(self, seconds):
        assert not self.real_started, "Pause the clock before advancing it"
        self.nanoseconds += round(seconds * 1_000_000_000)
        self.write()

    def resume(self):
        self.real_started = time.monotonic_ns()
        self.write()

    def pause(self):
        self.nanoseconds += time.monotonic_ns() - self.real_started
        self.real_started = 0
        self.write()


def setUpModule():
    """Compile exactly once for this module, in a disposable directory."""
    global BUILD_DIRECTORY, BINARY, PEERCRED_LIBRARY, UDEV_LIBRARY, RUNTIME_LIBRARY
    global POWER_PROFILES_FAKE, SYSTEMD_FAKE
    BUILD_DIRECTORY = tempfile.TemporaryDirectory(prefix="rgbcd-contract-")
    result = subprocess.run(
        [sys.executable, str(REPO / "native_build.py"), "--output", BUILD_DIRECTORY.name],
        capture_output=True, text=True, timeout=180,
    )
    if result.returncode:
        BUILD_DIRECTORY.cleanup()
        raise RuntimeError(result.stdout + result.stderr)
    BINARY = Path(BUILD_DIRECTORY.name) / "rgbcd"
    PEERCRED_LIBRARY = Path(BUILD_DIRECTORY.name) / "peercred.so"
    compiler = shutil.which(os.environ.get("CXX", "g++"))
    UDEV_LIBRARY = Path(BUILD_DIRECTORY.name) / "udev.so"
    RUNTIME_LIBRARY = Path(BUILD_DIRECTORY.name) / "runtime.so"
    for name, library in (("peercred", PEERCRED_LIBRARY), ("udev", UDEV_LIBRARY),
                          ("runtime", RUNTIME_LIBRARY)):
        result = subprocess.run([
            compiler, "-std=c++20", "-shared", "-fPIC", str(REPO / f"tests/fakes/{name}.cpp"),
            "-ldl", "-o", str(library),
        ], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    POWER_PROFILES_FAKE = Path(BUILD_DIRECTORY.name) / "power-profiles"
    qt_flags = shlex.split(subprocess.check_output(
        ["pkg-config", "--cflags", "--libs", "Qt6Core", "Qt6DBus"], text=True))
    result = subprocess.run([
        compiler, "-std=c++20", "-fPIC", "-Wall", "-Wextra", "-Wpedantic",
        str(REPO / "tests/fakes/power_profiles.cpp"), *qt_flags, "-o", str(POWER_PROFILES_FAKE),
    ], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)

    SYSTEMD_FAKE = Path(BUILD_DIRECTORY.name) / "systemd-fake"
    result = subprocess.run([
        compiler, "-std=c++20", "-fPIC", "-Wall", "-Wextra", "-Wpedantic",
        str(REPO / "tests/fakes/systemd.cpp"), *qt_flags, "-o", str(SYSTEMD_FAKE),
    ], capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)


def tearDownModule():
    if BUILD_DIRECTORY is not None:
        BUILD_DIRECTORY.cleanup()


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(WAIT_TIMEOUT)
        try:
            self.socket.connect(str(path))
        except OSError:
            self.socket.close()
            raise
        self.input = b""
        self.sequence = 0
        self.events = []
        # Replies to earlier requests that arrived while request() was waiting
        # for its own; read() hands them out first, in arrival order.
        self.stashed = []

    def send(self, value):
        self.socket.sendall(json.dumps(value).encode() + b"\n")

    def read(self, timeout=WAIT_TIMEOUT):
        if self.stashed:
            return self.stashed.pop(0)
        return self.read_line(timeout)

    def read_line(self, timeout=WAIT_TIMEOUT):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.input:
            self.socket.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                chunk = self.socket.recv(65536)
            except TimeoutError as error:
                message = f"Timed out waiting for a JSON line after {timeout}s"
                raise AssertionError(message) from error
            if not chunk:
                raise EOFError("Core closed the connection")
            self.input += chunk
        line, self.input = self.input.split(b"\n", 1)
        return json.loads(line)

    def request(self, operation, params=None):
        self.sequence += 1
        self.send({"v": 1, "id": self.sequence, "op": operation, "params": params or {}})
        while True:
            response = self.read_line()
            if "event" in response:
                self.events.append(response)
                continue
            if response.get("id") != self.sequence:
                # Another request's reply overtook ours: keep it for read().
                self.stashed.append(response)
                continue
            return response

    def event(self, topic, timeout=WAIT_TIMEOUT):
        for index, event in enumerate(self.events):
            if event["event"] == topic:
                return self.events.pop(index)
        deadline = time.monotonic() + timeout
        while True:
            event = self.read_line(max(0.001, deadline - time.monotonic()))
            if event.get("event") == topic:
                return event
            if "event" in event:
                self.events.append(event)

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.close()

    def close(self):
        self.socket.close()


class Daemon:
    def __init__(self, directory, *, demo=False, activation=None, extra=None,
                 alien_uid=False, environment=None, clock=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tree = HwmonTree(self.directory / "hwmon")
        self.path = self.directory / "core.sock"
        self.usb = UsbTree(self.directory / "sys")
        rules = self.directory / "openrgb.rules"
        rules.write_text("")
        environment = {**os.environ,
                       "HOME": str(self.directory),
                       "XDG_CONFIG_HOME": str(self.directory / "config"),
                       "DBUS_SESSION_BUS_ADDRESS": "unix:path=/nonexistent/rgbcd-session-bus",
                       "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=/nonexistent/rgbcd-test-bus",
                       **(environment or {})}
        for variable in ("LISTEN_FDS", "LISTEN_PID", "LISTEN_FDNAMES", "CORE_TEST_CLOCK"):
            environment.pop(variable, None)
        libraries = [str(RUNTIME_LIBRARY), str(UDEV_LIBRARY)]
        if environment.get("LD_PRELOAD"):
            libraries.append(environment["LD_PRELOAD"])
        if alien_uid:
            libraries.append(str(PEERCRED_LIBRARY))
        environment["LD_PRELOAD"] = ":".join(libraries)
        self.clock = TestClock(self.directory) if clock else None
        if self.clock:
            environment["CORE_TEST_CLOCK"] = str(self.clock.path)
        arguments = [str(BINARY), "--hwmon-root", str(self.tree.root),
                     "--sys-root", str(self.usb.root), "--openrgb-rules", str(rules)]
        if demo:
            arguments.append("--demo")
        if extra:
            arguments.extend(extra)
        if activation is None:
            arguments += ["--listen", str(self.path)]
            pass_fds = ()
        else:
            self.path = Path(activation.getsockname())
            launcher = (
                "import os,sys; fd=int(sys.argv[1]); os.dup2(fd,3); "
                "os.set_inheritable(3,True); os.environ['LISTEN_PID']=str(os.getpid()); "
                "os.environ['LISTEN_FDS']='1'; os.execv(sys.argv[2],sys.argv[2:])"
            )
            arguments = [sys.executable, "-c", launcher, str(activation.fileno()), *arguments]
            pass_fds = (activation.fileno(),)
        self.process = subprocess.Popen(arguments, env=environment, pass_fds=pass_fds,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.stderr = ""

        def listening():
            if self.process.poll() is not None:
                self.close()
                raise RuntimeError("rgbcd exited before listening: " + self.stderr)
            if not self.path.is_socket():
                return False
            if alien_uid:
                return True
            # Activation sockets already exist; binding a private socket also precedes listen.
            try:
                with self.client() as client:
                    if not client.request("hello")["ok"]:
                        raise AssertionError("rgbcd startup hello failed")
            except (FileNotFoundError, ConnectionRefusedError):
                return False
            return True

        try:
            wait_until(listening, message=f"rgbcd to answer hello on {self.path}")
        except Exception:
            self.close()
            raise

    def advance(self, seconds, client):
        self.clock.advance(seconds)
        # Wake Qt's event dispatcher so it re-evaluates virtual timer deadlines.
        client.request("hello")

    def client(self):
        return Client(self.path)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            _stdout, stderr = self.process.communicate(timeout=WAIT_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.process.kill()
            _stdout, stderr = self.process.communicate()
        self.stderr = stderr.decode(errors="replace")


class CoreContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-api-")
        self.addCleanup(self.temporary.cleanup)
        self.daemon = Daemon(self.temporary.name, demo=True, clock=True)
        self.addCleanup(self.daemon.close)
        self.client = self.daemon.client()
        self.addCleanup(self.client.close)

    def assert_error(self, response, code):
        self.assertEqual(set(response), {"v", "id", "ok", "error"})
        self.assertEqual(response["v"], 1)
        self.assertIs(response["ok"], False)
        self.assertEqual(set(response["error"]), {"code", "message"})
        self.assertEqual(response["error"]["code"], code)
        self.assertIsInstance(response["error"]["message"], str)
        self.assertTrue(response["error"]["message"])

    def test_contract_hello_version_api_demo_and_response_envelope(self):
        result = self.client.request("hello")
        self.assertEqual(set(result), {"v", "id", "ok", "result"})
        self.assertEqual(result, {"v": 1, "id": 1, "ok": True, "result": {
            "version": "0.1.0", "api": 1, "demo": True,
        }})

    def test_contract_demo_rescan_lists_devices_and_rate_limits(self):
        devices = self.client.request("devices.rescan")["result"]
        self.assertEqual(devices["devices"][0]["id"], "demo:rgb0")
        self.assert_error(self.client.request("devices.rescan"), "rate_limited")
        self.daemon.advance(2.3, self.client)
        self.assertEqual(self.client.request("devices.rescan")["result"], devices)

    def test_contract_status_engine_schema_and_uptime(self):
        status = self.client.request("status")["result"]
        self.assertEqual(set(status), {"engines", "uptime_s"})
        self.assertIsInstance(status["uptime_s"], int)
        self.assertGreaterEqual(status["uptime_s"], 0)
        self.assertEqual(set(status["engines"][0]), {"id", "state", "reason"})
        self.assertEqual(status["engines"][0]["id"], "openrgb")
        self.assertIn(status["engines"][0]["state"],
                      ("absent", "unreachable", "ready", "blocked"))

    def test_contract_closed_operations_unknown_fields_and_optional_params(self):
        self.client.send({"v": 1, "id": 19, "op": "hello", "ignored": [False]})
        self.assertTrue(self.client.read()["ok"])
        for operation in ("shell", "exec", "fans.set", "restore-auto", "", "HELLO"):
            self.assert_error(self.client.request(operation), "unknown_op")

    def test_contract_positive_integer_ids_echo_without_an_arbitrary_32bit_limit(self):
        for identifier in (1, 2**32, 2**53 - 1, 2**53, 0, -1, 1.5, "1"):
            with self.subTest(identifier=identifier):
                self.client.send({"v": 1, "id": identifier, "op": "hello"})
                response = self.client.read()
                if isinstance(identifier, int) and 1 <= identifier <= 2**53 - 1:
                    self.assertTrue(response["ok"])
                    self.assertEqual(response["id"], identifier)
                else:
                    self.assert_error(response, "bad_request")
                    self.assertIsNone(response["id"])

    def test_contract_bad_request_wrong_envelope_types_and_utf8(self):
        valid = {"v": 1, "id": 7, "op": "hello", "params": {}}
        cases = []
        for field, values in {
            "v": [None, False, 2, "1", 1.5],
            "id": [None, False, 0, -1, 1.5, "7"],
            "op": [None, False, 7, []],
            "params": [None, [], False, ""],
        }.items():
            for value in values:
                cases.append({**valid, field: value})
        for field in ("v", "id", "op"):
            cases.append({key: value for key, value in valid.items() if key != field})
        for value in cases + [[], None, True, 7, "hello"]:
            with self.subTest(value=value):
                self.client.send(value)
                self.assert_error(self.client.read(), "bad_request")
        for line in (b"\xff\n", b"{bad json}\n", b"\n"):
            self.client.socket.sendall(line)
            self.assert_error(self.client.read(), "bad_request")

    def test_contract_bad_request_lighting_and_subscribe_parameters(self):
        for params in ({}, {"device": 7}, {"device": ""}):
            self.assert_error(self.client.request("lighting.get", params), "bad_request")
        valid = {"device": "demo:rgb0", "color": "#112233", "brightness": 50}
        for field, values in {
            "device": [None, 3, ""],
            "color": [None, True, "red", "#123", "#gg1234", "#123456\n"],
            "brightness": [None, True, "50", -1, 101, 1.5],
        }.items():
            for value in values:
                self.assert_error(self.client.request("lighting.set", {**valid, field: value}),
                                  "bad_request")
        for params in ({}, {"topics": "sensors"}, {"topics": [False]},
                       {"topics": ["unknown"]}, {"topics": [], "interval_ms": True},
                       {"topics": [], "interval_ms": 1.5}):
            self.assert_error(self.client.request("subscribe", params), "bad_request")

    def test_contract_each_operation_parameter_schema_rejects_wrong_types(self):
        valid = {"device": "demo:rgb0", "color": "#112233", "brightness": 50}
        cases = []
        for value in (None, True, 3, [], {}):
            cases.append(("lighting.get", {"device": value}))
            cases.append(("lighting.set", {**valid, "device": value}))
        for value in (None, True, 3, [], {}, "red", "#12345g", "#123456\n"):
            cases.append(("lighting.set", {**valid, "color": value}))
        for value in (None, True, "50", [], {}, -1, 101, 1.5):
            cases.append(("lighting.set", {**valid, "brightness": value}))
        for value in (None, True, "sensors", 3, {}, [1], [None], ["sensors", False]):
            cases.append(("subscribe", {"topics": value}))
        for value in (None, True, "500", [], {}, 1.5):
            cases.append(("subscribe", {"topics": ["sensors"], "interval_ms": value}))
        for operation in ("lighting.set", "lighting.get", "subscribe"):
            cases.append((operation, {}))
        for operation, params in cases:
            with self.subTest(operation=operation, params=params):
                reply = self.client.request(operation, params)
                self.assert_error(reply, "bad_request")
                self.assertEqual(reply["id"], self.client.sequence)
        # No-parameter operations still require params to be an object.
        for operation in ("hello", "status", "sensors", "devices", "devices.rescan", "unsubscribe"):
            self.client.send({"v": 1, "id": 800, "op": operation, "params": []})
            self.assert_error(self.client.read(), "bad_request")
        self.assertEqual(self.client.request("lighting.set", {
            **valid, "color": "#ABCDEF", "unknown": [],
        })["result"]["color"], "#abcdef")

    def test_contract_subscription_timer_sleeps_until_earliest_connection_deadline(self):
        self.client.request("subscribe", {"topics": ["sensors"], "interval_ms": 10000})
        self.client.event("sensors")
        status = Path(f"/proc/{self.daemon.process.pid}/status")

        def wakeups():
            return int(next(line.split()[1] for line in status.read_text().splitlines()
                            if line.startswith("voluntary_ctxt_switches:")))

        # Real time must run during wakeup observations to expose periodic polling timers.
        self.daemon.clock.resume()
        before = wakeups()
        started = time.monotonic()
        time.sleep(1.2)
        # Scale the budget to the actual observation window after scheduler delays.
        # A 50 ms polling timer still exceeds this by an order of magnitude.
        self.assertLess(wakeups() - before, max(10, 2 * (time.monotonic() - started)))
        self.daemon.clock.pause()
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        peer.request("subscribe", {"topics": ["sensors"], "interval_ms": 500})
        peer.event("sensors")
        self.daemon.advance(0.4, peer)
        self.assertEqual(peer.events, [])
        self.assertEqual(select.select([peer.socket], [], [], 0.1)[0], [])
        self.daemon.advance(0.2, peer)
        peer.event("sensors")
        peer.request("unsubscribe")
        self.client.request("unsubscribe")
        self.daemon.clock.resume()
        before = wakeups()
        started = time.monotonic()
        time.sleep(0.7)
        self.assertLess(wakeups() - before, max(5, 2 * (time.monotonic() - started)))

    def test_contract_framing_fragmentation_pipelining_and_64kib_boundary(self):
        line = json.dumps({"v": 1, "id": 101, "op": "hello"}).encode()
        self.client.socket.sendall(line[:4])
        self.client.socket.sendall(line[4:] + b"\n" + line.replace(b"101", b"102") + b"\n")
        self.assertEqual(self.client.read()["id"], 101)
        self.assertEqual(self.client.read()["id"], 102)
        self.client.socket.sendall(line + b" " * (65536 - len(line)) + b"\n")
        self.assertTrue(self.client.read()["ok"])
        self.client.socket.sendall(b"x" * 65537)
        self.assert_error(self.client.read(), "too_large")
        self.assertEqual(self.client.socket.recv(1), b"")

    def test_contract_limit_eight_connections(self):
        peers = [self.daemon.client() for _index in range(7)]
        self.addCleanup(lambda: [peer.close() for peer in peers])
        for peer in peers:
            self.assertTrue(peer.request("hello")["ok"])
        extra = self.daemon.client()
        self.addCleanup(extra.close)
        with self.assertRaises((EOFError, ConnectionResetError, BrokenPipeError)):
            extra.request("hello")
        self.assertTrue(self.client.request("hello")["ok"])

    def test_contract_socket_0600_refuses_non_socket_and_live_socket(self):
        self.assertEqual(stat.S_IMODE(self.daemon.path.stat().st_mode), 0o600)
        sentinel = Path(self.temporary.name) / "sentinel"
        sentinel.write_text("keep")
        for path in (sentinel, self.daemon.path):
            result = subprocess.run([str(BINARY), "--demo", "--listen", str(path)],
                                    capture_output=True, text=True, timeout=WAIT_TIMEOUT)
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertTrue(self.client.request("hello")["ok"])

    def test_contract_demo_devices_sensor_schema_and_never_touches_hwmon(self):
        watch = FileWatch(self.daemon.tree.cpu / "temp1_input")
        self.addCleanup(watch.close)
        before = self.daemon.tree.snapshot()
        watch.drain()
        device = self.client.request("devices")["result"]["devices"][0]
        self.assertEqual(set(device), {"id", "name", "vendor", "engine", "support", "writable",
                                       "blocked_reason", "excluded", "capabilities"})
        self.assertEqual(device["id"], "demo:rgb0")
        self.assertEqual(device["support"], "simulation-tested")
        self.assertTrue(device["writable"])
        self.assertFalse(device["excluded"])
        self.assertEqual(device["blocked_reason"], "")
        self.assertEqual(device["capabilities"], ["lighting.read", "lighting.write", "brightness"])
        sensors = self.client.request("sensors")["result"]
        self.assertIn(sensors["primary"], [sensor["id"] for sensor in sensors["sensors"]])
        for sensor in sensors["sensors"]:
            self.assertEqual(set(sensor), {"id", "label", "device", "kind", "value", "unit",
                                          "source", "stale", "channel", "header"})
            self.assertEqual(sensor["channel"], sensor["id"].rsplit(":", 1)[1])
            self.assertEqual(sensor["header"], "")
            self.assertEqual(sensor["source"], "demo")
            self.assertIn(sensor["kind"], ("temp", "fan"))
            self.assertIs(sensor["stale"], False)
        self.client.request("subscribe", {"topics": ["sensors"], "interval_ms": 500})
        self.client.event("sensors")
        self.assertEqual(watch.drain(), [])
        self.assertEqual(before, self.daemon.tree.snapshot())

    def test_contract_demo_lighting_get_set_roundtrip_and_unavailable(self):
        expected = {"device": "demo:rgb0", "color": "#abcdef", "brightness": 0,
                    "brightness_emulated": True}
        reply = self.client.request("lighting.set", {
            "device": "demo:rgb0", "color": "#ABCDEF", "brightness": 0,
        })
        self.assertEqual(reply["result"], expected)
        self.assertEqual(self.client.request("lighting.get", {"device": "demo:rgb0"})["result"],
                         expected)
        for operation in ("lighting.get", "lighting.set"):
            self.assert_error(self.client.request(operation, {
                "device": "missing", "color": "#123456", "brightness": 100,
            }), "unavailable")

    def test_contract_lighting_set_rate_limit_ten_per_second_per_connection(self):
        for index in range(11):
            self.client.send({"v": 1, "id": 100 + index, "op": "lighting.set", "params": {
                "device": "demo:rgb0", "color": "#123456", "brightness": 50,
            }})
        for _index in range(10):
            self.assertTrue(self.client.read()["ok"])
        self.assert_error(self.client.read(), "rate_limited")
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("lighting.set", {
            "device": "demo:rgb0", "color": "#123456", "brightness": 100,
        })["ok"])
        self.daemon.advance(1.3, self.client)
        self.assertTrue(self.client.request("lighting.set", {
            "device": "demo:rgb0", "color": "#123456", "brightness": 100,
        })["ok"])

    def test_contract_subscribe_events_no_id_unsubscribe_and_interval_clamp_500_10000(self):
        self.assertEqual(self.client.request("subscribe", {
            "topics": ["sensors", "devices"], "interval_ms": -100,
        })["result"], {})
        first = self.client.event("sensors")
        self.assertEqual(set(first), {"v", "event", "data"})
        self.assertEqual(first["v"], 1)
        self.assertEqual(set(self.client.event("devices")["data"]), {"devices"})
        self.daemon.advance(0.4, self.client)
        self.assertEqual(self.client.events, [])
        self.assertEqual(select.select([self.client.socket], [], [], 0.1)[0], [])
        self.daemon.advance(0.2, self.client)
        self.client.event("sensors")
        self.client.event("devices")
        self.assertEqual(self.client.request("unsubscribe")["result"], {})
        self.client.events.clear()
        self.assertEqual(self.client.input, b"")
        self.assertEqual(select.select([self.client.socket], [], [], 0.6)[0], [])
        self.client.request("subscribe", {"topics": ["sensors"], "interval_ms": 999999999})
        self.client.event("sensors")
        self.daemon.advance(9.4, self.client)
        self.assertEqual(self.client.events, [])
        self.assertEqual(select.select([self.client.socket], [], [], 0.1)[0], [])
        self.daemon.advance(0.9, self.client)
        self.client.event("sensors")


class HwmonContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-hwmon-")
        self.addCleanup(self.temporary.cleanup)
        self.fake = OpenRgbServer(descriptors=[])
        self.addCleanup(self.fake.close)
        controlled = self._testMethodName in (
            "test_contract_hwmon_on_demand_cache_read_only_primary_cpu_and_units",
            "test_contract_hwmon_blocked_read_does_not_block_other_connections",
        )
        self.daemon = Daemon(self.temporary.name, clock=controlled, environment={
            "CORE_TEST_OPENRGB_PORT": str(self.fake.port),
        })
        self.addCleanup(self.daemon.close)
        self.client = self.daemon.client()
        self.addCleanup(self.client.close)

    def subscribe(self):
        self.assertTrue(self.client.request("subscribe", {
            "topics": ["sensors"], "interval_ms": 500,
        })["ok"])
        return self.client.event("sensors")["data"]

    def test_contract_hwmon_on_demand_cache_read_only_primary_cpu_and_units(self):
        watch = FileWatch(self.daemon.tree.cpu / "temp1_input")
        self.addCleanup(watch.close)
        before = self.daemon.tree.snapshot()
        watch.drain()
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 500})
        self.client.event("devices")
        self.assertEqual(watch.drain(), [])
        self.client.request("unsubscribe")
        data = self.client.request("sensors")["result"]
        self.assertTrue(any(mask & 1 for mask in watch.drain()))
        cached = self.client.request("sensors")["result"]
        self.assertEqual(cached, data)
        self.assertEqual(watch.drain(), [])
        self.daemon.advance(0.8, self.client)
        data = self.subscribe()
        self.assertEqual(data["primary"], "coretemp:platform/coretemp.0:temp1")
        sensors = {sensor["id"]: sensor for sensor in data["sensors"]}
        primary = sensors[data["primary"]]
        self.assertEqual(primary["value"], 42.5)
        self.assertEqual(primary["unit"], "C")
        self.assertEqual(primary["source"], "hwmon")
        self.assertFalse(primary["stale"])
        fan = next(sensor for sensor in sensors.values() if sensor["kind"] == "fan")
        self.assertEqual(fan["value"], 0)
        self.assertEqual(fan["unit"], "rpm")
        masks = watch.drain()
        self.assertTrue(any(mask & 1 for mask in masks))
        self.assertFalse(any(mask & (2 | 8) for mask in masks), masks)
        self.client.request("unsubscribe")
        watch.drain()
        self.daemon.advance(0.8, self.client)
        # Absence observation: extra real waiting is safe, even on a loaded runner.
        time.sleep(0.7)
        self.assertEqual(watch.drain(), [])
        self.client.request("sensors")
        self.assertTrue(any(mask & 1 for mask in watch.drain()))
        self.assertEqual(before, self.daemon.tree.snapshot())

    def test_contract_sensor_human_names_with_fake_hwmon_tree(self):
        devices = (
            ("hwmon21", "nvme", "pci0000:00/0000:00:1c.0/0000:05:00.0",
             {"temp1_input": "42000"}),
            ("hwmon22", "nvme", "pci0000:00/0000:00:1c.1/0000:02:00.0",
             {"temp1_input": "43000"}),
            ("hwmon23", "spd5118", "platform/i2c-8/8-0053", {"temp1_input": "44000"}),
            ("hwmon24", "spd5118", "platform/i2c-8/8-0051", {"temp1_input": "45000"}),
            ("hwmon25", "iwlwifi_1", "pci0000:00/0000:06:00.0", {"temp1_input": "46000"}),
            ("hwmon26", "r8169-0000:04:00.0", "pci0000:00/0000:04:00.0",
             {"temp1_input": "47000"}),
            ("hwmon27", "acpitz", "virtual/thermal/thermal_zone0", {"temp1_input": "48000"}),
        )
        for number, name, parent, files in devices:
            self.daemon.tree.add(number, name, parent, files)
        self.daemon.tree.add_mdio_ethernet()
        data = self.client.request("sensors")["result"]
        sensors = {sensor["id"]: sensor for sensor in data["sensors"]}
        expected = {
            "amdgpu:pci0000:00/0000:03:00.0:temp1": ("AMD GPU", "edge"),
            "nvme:pci0000:00/0000:00:1c.0/0000:05:00.0:temp1":
                ("NVMe 2", "Temperature"),
            "nvme:pci0000:00/0000:00:1c.1/0000:02:00.0:temp1":
                ("NVMe 1", "Temperature"),
            "spd5118:platform/i2c-8/8-0053:temp1": ("RAM", "DIMM 2"),
            "spd5118:platform/i2c-8/8-0051:temp1": ("RAM", "DIMM 1"),
            "iwlwifi_1:pci0000:00/0000:06:00.0:temp1": ("Wi-Fi", "Temperature"),
            "r8169-0000:04:00.0:pci0000:00/0000:04:00.0:temp1":
                ("Ethernet", "Temperature"),
            "acpitz:virtual/thermal/thermal_zone0:temp1": ("ACPI", "Temperature"),
            "r8169_0_600:00:platform/mdio_bus/0/0-0000:00:00.0:temp1":
                ("Ethernet", "Temperature"),
        }
        for sensor_id, (device, label) in expected.items():
            with self.subTest(sensor_id=sensor_id):
                self.assertEqual(sensors[sensor_id]["device"], device)
                self.assertEqual(sensors[sensor_id]["label"], label)
        self.assertEqual(sensors["coretemp:platform/coretemp.0:temp1"]["device"], "Intel CPU")
        self.assertEqual(sensors["coretemp:platform/coretemp.0:temp1"]["label"], "Package id 0")

    def test_contract_single_ram_module_is_dimm_one(self):
        self.daemon.tree.add("hwmon31", "spd5118", "platform/i2c-12/12-0052", {
            "temp1_input": "44000",
        })
        sensors = self.client.request("sensors")["result"]["sensors"]
        ram = [sensor for sensor in sensors if sensor["id"].startswith("spd5118:")]
        self.assertEqual(len(ram), 1)
        self.assertEqual((ram[0]["device"], ram[0]["label"]), ("RAM", "DIMM 1"))

    def test_contract_motherboard_fans_are_named_and_never_writable(self):
        names = ("nct6683", "nct6687", "nct6775", "nct6779", "it87", "it8689", "it8xxx")
        for number, name in enumerate(names, 40):
            node = self.daemon.tree.add(f"hwmon{number}", name, f"platform/{name}", {
                "temp1_input": "42000", "fan1_input": "800", "fan1_label": "CPU_FAN",
                "fan2_input": "900", "fan2_label": "SYS_FAN", "pwm1": "100",
                "pwm1_enable": "2", "fan1_target": "1000", "fan10_input": "1000",
            })
            for path in node.iterdir():
                if path.is_file():
                    path.chmod(0o666)
        before = self.daemon.tree.snapshot()
        data = self.client.request("sensors")["result"]
        for name in names:
            sensors = [item for item in data["sensors"] if item["id"].startswith(name + ":")]
            self.assertEqual(len(sensors), 4)
            self.assertEqual([item["kind"] for item in sensors], ["temp", "fan", "fan", "fan"])
            self.assertEqual({item["device"] for item in sensors}, {"Motherboard"})
            fans = [item for item in sensors if item["kind"] == "fan"]
            self.assertEqual([item["label"] for item in fans], ["Fan 1", "Fan 2", "Fan 10"])
            for fan in fans:
                for op in ("fans.set", "fan.set", "pwm.set"):
                    response = self.client.request(op, {"device": fan["id"], "value": 255})
                    self.assertEqual(response["error"]["code"], "unknown_op")
                response = self.client.request("lighting.set", {
                    "device": fan["id"], "color": "#ffffff", "brightness": 100,
                })
                self.assertFalse(response["ok"])
        self.assertEqual(before, self.daemon.tree.snapshot())

    def test_contract_hwmon_blocked_read_does_not_block_other_connections(self):
        path = self.daemon.tree.cpu / "temp1_input"
        path.unlink()
        os.mkfifo(path)
        self.client.send({"v": 1, "id": 100, "op": "sensors"})
        # Opening the write end proves the worker has reached the blocking read.
        def open_writer():
            try:
                return (os.open(path, os.O_WRONLY | os.O_NONBLOCK),)
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise
                return None

        writer = wait_until(open_writer, message="hwmon worker to open its FIFO for reading")[0]
        try:
            peer = self.daemon.client()
            self.addCleanup(peer.close)
            # The FIFO remains blocked: hello must complete before the worker can finish.
            self.assertTrue(peer.request("hello")["ok"])
            # Coalesce a second sensor request while the first read is still pending.
            peer.send({"v": 1, "id": 200, "op": "sensors"})
            self.assertTrue(peer.request("hello")["ok"])
            os.write(writer, b"42500\n")
        finally:
            os.close(writer)
        first = self.client.read()
        second = peer.read()
        self.assertEqual(first["id"], 100)
        self.assertEqual(second["id"], 200)
        self.assertEqual(first["result"], second["result"])
        self.assertTrue(first["result"]["sensors"])

    def test_contract_hwmon_stable_ids_never_hwmon_number_and_rescan_hotplug(self):
        initial = self.subscribe()
        target = self.daemon.tree.cpu
        replacement = target.with_name("hwmon99")
        target.rename(replacement)
        (replacement / "temp1_input").write_text("43000")
        (self.daemon.tree.root / "hwmon8").unlink()
        (self.daemon.tree.root / "hwmon99").symlink_to(replacement, target_is_directory=True)
        data = wait_event(self.client, "sensors", lambda data: any(
            item["id"] == initial["primary"] and item["value"] == 43
            for item in data["sensors"]
        ), message="renumbered hwmon primary to report 43 C")
        self.assertEqual(data["primary"], initial["primary"])
        self.assertFalse(any("hwmon" in item["id"] for item in data["sensors"]))

    def wait_for_primary(self, primary, predicate, *, message, timeout=WAIT_TIMEOUT):
        """Ignore events sampled before the fixture change, including buffered events."""
        data = wait_event(self.client, "sensors", lambda data: any(
            item["id"] == primary and predicate(item) for item in data["sensors"]
        ), timeout=timeout, message=f"primary sensor {primary}: {message}")
        return next(item for item in data["sensors"] if item["id"] == primary)

    def test_contract_hwmon_nan_missing_failed_read_null_and_stale_after_three_intervals(self):
        data = self.subscribe()
        primary = data["primary"]
        for invalid in ("NaN", "inf", "-inf", "not a number", ""):
            # Restore a valid reading first so each invalid value is observed on its own.
            (self.daemon.tree.cpu / "temp1_input").write_text("42500")
            self.wait_for_primary(primary, lambda sensor: sensor["value"] is not None,
                                  message="valid reading to be restored")
            (self.daemon.tree.cpu / "temp1_input").write_text(invalid)
            # An event sampled before the write may already be in flight: wait for the change.
            self.wait_for_primary(primary, lambda sensor: sensor["value"] is None,
                                  message=f"{invalid!r} to produce null")
        (self.daemon.tree.cpu / "temp1_input").unlink()
        def missing_and_stale(sensor):
            self.assertIsNone(sensor["value"])
            return sensor["stale"]

        self.wait_for_primary(primary, missing_and_stale,
                              message="missing input to become stale")
        shutil.rmtree(self.daemon.tree.cpu)
        data = self.client.event("sensors")["data"]
        sensor = next(item for item in data["sensors"] if item["id"] == primary)
        self.assertIsNone(sensor["value"])
        self.assertTrue(sensor["stale"])

    def test_contract_primary_falls_back_to_first_temperature(self):
        (self.daemon.tree.cpu / "name").write_text("other-driver")
        data = self.subscribe()
        first = next(item for item in data["sensors"] if item["kind"] == "temp")
        self.assertEqual(data["primary"], first["id"])


class FanHeadersContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-fan-headers-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.table = json.loads((REPO / "data/fan-headers.json").read_text())
        self.entry = self.table["entries"][0]
        self.launches = 0

    def launch(self, *, vendor=None, board=None, chip="nct6687", content=None,
               missing=False, fifo=False, environment=None):
        self.launches += 1
        directory = self.root / str(self.launches)
        self.dmi = DmiTree(directory / "dmi",
                           self.entry["dmi_vendor"] if vendor is None else vendor,
                           self.entry["dmi_boards"][0] if board is None else board)
        self.data = directory / "data"
        self.data.mkdir()
        path = self.data / "fan-headers.json"
        if fifo:
            os.mkfifo(path)
        elif not missing:
            path.write_bytes(json.dumps(self.table).encode() if content is None else content)
        daemon = Daemon(directory, clock=True, environment=environment, extra=[
            "--data-dir", str(self.data), "--dmi-root", str(self.dmi.root),
        ])
        self.addCleanup(daemon.close)
        daemon.tree.add("hwmon18", chip, "platform/nct6687", {
            **{f"fan{number}_input": "900" for number in range(1, 9)},
            "temp1_input": "42000", "fan5_label": "Untrusted sysfs label",
            "pwm1": "38", "pwm1_enable": "2",
        })
        client = daemon.client()
        self.addCleanup(client.close)
        return daemon, client

    def sensors(self, client):
        sensors = client.request("sensors")["result"]["sensors"]
        for sensor in sensors:
            self.assertEqual(sensor["channel"], sensor["id"].rsplit(":", 1)[1])
            self.assertIsInstance(sensor["header"], str)
        return {sensor["channel"]: sensor for sensor in sensors
                if ":platform/nct6687:" in sensor["id"]}

    def assert_fallback(self, client):
        sensors = self.sensors(client)
        self.assertEqual(len(sensors), 9)
        for number in range(1, 9):
            self.assertEqual(sensors[f"fan{number}"]["label"], f"Fan {number}")
            self.assertEqual(sensors[f"fan{number}"]["header"], "")

    def assert_ignored(self, content=None, **options):
        daemon, client = self.launch(content=content, **options)
        self.assert_fallback(client)
        daemon.close()
        self.assertIn("warning: fan-headers.json", daemon.stderr)
        self.assertIn("ignoring the entire table", daemon.stderr)
        self.assertEqual(daemon.stderr.count("warning: fan-headers.json"), 1)

    def test_verified_ms_7d98_headers_unlisted_channel_and_stable_ids(self):
        daemon, client = self.launch()
        before = daemon.tree.snapshot()
        sensors = self.sensors(client)
        expected = {"fan1": "CPU_FAN1", "fan2": "PUMP_FAN1", "fan3": "SYS_FAN1",
                    "fan4": "SYS_FAN2", "fan5": "SYS_FAN3", "fan6": "SYS_FAN4",
                    "fan7": "SYS_FAN5"}
        for channel, header in expected.items():
            self.assertEqual(sensors[channel]["header"], header)
            self.assertEqual(sensors[channel]["label"], header)
            self.assertEqual(sensors[channel]["id"], f"nct6687:platform/nct6687:{channel}")
        self.assertEqual(sensors["fan8"]["label"], "Fan 8")
        self.assertEqual(sensors["fan8"]["header"], "")
        self.assertEqual(sensors["temp1"]["header"], "")
        self.assertEqual(daemon.tree.snapshot(), before)

    def test_other_msi_board_and_other_vendor_fall_back(self):
        for options in ({"board": "OTHER MSI (MS-1234)"}, {"vendor": "Other Vendor"},
                        {"board": self.entry["dmi_boards"][0].lower()},
                        {"vendor": " " + self.entry["dmi_vendor"]},
                        {"vendor": ""}, {"board": ""}):
            with self.subTest(options=options):
                daemon, client = self.launch(**options)
                self.assert_fallback(client)
                daemon.close()
                self.assertNotIn("warning: fan-headers.json", daemon.stderr)

    def test_chip_match_is_exact(self):
        for chip in ("nct6683", "nct6687d", "nct6687-extra"):
            with self.subTest(chip=chip):
                _daemon, client = self.launch(chip=chip)
                self.assert_fallback(client)

    def test_source_derived_entry_is_valid_but_never_applied(self):
        self.entry["status"] = "source-derived"
        daemon, client = self.launch()
        self.assert_fallback(client)
        daemon.close()
        self.assertNotIn("warning: fan-headers.json", daemon.stderr)

    def test_board_can_match_any_exact_list_member(self):
        self.entry["dmi_boards"].insert(0, "Other Board")
        _daemon, client = self.launch(board="B760 GAMING PLUS WIFI (MS-7D98)")
        self.assertEqual(self.sensors(client)["fan5"]["header"], "SYS_FAN3")

    def test_invalid_source_derived_entry_also_discards_whole_table(self):
        invalid = json.loads(json.dumps(self.entry))
        invalid["status"] = "source-derived"
        invalid["headers"]["fan5"] = "<b>CPU</b>"
        self.table["entries"].append(invalid)
        self.assert_ignored()

    def test_missing_invalid_utf8_json_and_nonregular_table_are_ignored(self):
        self.assert_ignored(missing=True)
        self.assert_ignored(fifo=True)
        for content in (b"{", b"[]", b"null", b'\xff', b'{"version":1,"entries":['):
            with self.subTest(content=content):
                self.assert_ignored(content)

    def test_maximum_file_size_is_inclusive(self):
        valid = json.dumps(self.table).encode()
        padded = valid + b" " * (256 * 1024 - len(valid))
        _daemon, client = self.launch(content=padded)
        self.assertEqual(self.sensors(client)["fan5"]["header"], "SYS_FAN3")
        self.assert_ignored(padded + b" ")

    def test_invalid_header_names_discard_even_preceding_valid_entries(self):
        for name in ("sys_fan3", "<b>CPU_FAN1</b>", "CPU_FAN1\n", "", "A" * 17, "FÄN"):
            with self.subTest(name=name):
                table = json.loads(json.dumps(self.table))
                invalid = json.loads(json.dumps(self.entry))
                invalid["headers"]["fan5"] = name
                table["entries"].append(invalid)
                self.assert_ignored(json.dumps(table).encode())

    def test_invalid_channels_discard_table(self):
        for channel in ("Fan1", "temp1", "fan", "fan100", "fan1\n", "fan-1"):
            with self.subTest(channel=channel):
                table = json.loads(json.dumps(self.table))
                table["entries"][0]["headers"][channel] = "CPU_FAN1"
                self.assert_ignored(json.dumps(table).encode())

    def test_exact_schema_types_and_required_fields(self):
        cases = []
        for field, values in {
            "chip": (None, True, 7, [], {}),
            "dmi_vendor": (None, True, 7, [], {}),
            "dmi_boards": (None, True, "board", {}, [True], [7], [None]),
            "status": (None, True, 7, [], {}, "verified"),
            "headers": (None, True, 7, [], "CPU_FAN1", {"fan1": 1}),
            "verified": (None, True, 7, [], {}),
            "sources": (None, True, 7, {}, "url", [True]),
        }.items():
            for value in values:
                table = json.loads(json.dumps(self.table))
                table["entries"][0][field] = value
                cases.append((field, value, table))
        for field in ("chip", "dmi_vendor", "dmi_boards", "status", "headers"):
            table = json.loads(json.dumps(self.table))
            del table["entries"][0][field]
            cases.append((field, "missing", table))
        for field, values in {"version": (None, True, "1", 0, 2, 1.5),
                              "entries": (None, True, {}, "entries", [True])}.items():
            for value in values:
                table = json.loads(json.dumps(self.table))
                table[field] = value
                cases.append((field, value, table))
            table = json.loads(json.dumps(self.table))
            del table[field]
            cases.append((field, "missing", table))
        for field, value, table in cases:
            with self.subTest(field=field, value=value):
                self.assert_ignored(json.dumps(table).encode())

    def test_table_and_dmi_read_once_at_start_and_environment_cannot_override_dmi(self):
        daemon, client = self.launch(environment={"DMI_ROOT": "/nonexistent",
                                                  "RGBCD_DMI_ROOT": "/nonexistent"})
        before = self.sensors(client)
        watches = [FileWatch(path) for path in (
            self.data / "fan-headers.json", self.dmi.root / "board_vendor",
            self.dmi.root / "board_name")]
        for watch in watches:
            self.addCleanup(watch.close)
        self.dmi.write("Other Vendor", "Other Board")
        (self.data / "fan-headers.json").write_text("invalid")
        for watch in watches:
            watch.drain()
        daemon.advance(1, client)
        self.assertEqual(self.sensors(client), before)
        for watch in watches:
            self.assertFalse(any(mask & (0x01 | 0x20) for mask in watch.drain()))

    def test_repository_table_uses_runtime_schema(self):
        result = subprocess.run([str(BINARY), "--self-test", "--data-dir", str(REPO / "data")],
                                capture_output=True, text=True, timeout=WAIT_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("repository fan-headers.json passes the runtime schema", result.stdout)


class OpenRgbContract(OpenRgbContractMixin, unittest.TestCase):
    pass


class ActivationAndLifetimeContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-activation-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def listener(self, name):
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(listener.close)
        listener.bind(str(self.directory / name))
        os.chmod(self.directory / name, 0o600)
        listener.listen(8)
        return listener

    def test_contract_listen_fds_pid_adoption_does_not_rebind_or_unlink(self):
        listener = self.listener("activation.sock")
        path = Path(listener.getsockname())
        inode = path.stat().st_ino
        daemon = Daemon(self.directory / "adopt", demo=True, activation=listener)
        self.addCleanup(daemon.close)
        client = daemon.client()
        self.addCleanup(client.close)
        self.assertTrue(client.request("hello")["ok"])
        self.assertEqual(path.stat().st_ino, inode)
        daemon.close()
        self.assertTrue(path.is_socket())
        self.assertEqual(path.stat().st_ino, inode)
        replacement = Daemon(self.directory / "readopt", demo=True, activation=listener)
        self.addCleanup(replacement.close)
        peer = replacement.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("hello")["ok"])
        self.assertEqual(path.stat().st_ino, inode)

    def test_contract_invalid_listen_pid_fd_count_and_non_socket_descriptors_rejected(self):
        for pid, count in (("1", "1"), ("garbage", "1"), ("", ""), ("1", "2")):
            environment = {**os.environ, "LISTEN_PID": pid, "LISTEN_FDS": count}
            result = subprocess.run([str(BINARY)], env=environment, capture_output=True,
                                    text=True, timeout=WAIT_TIMEOUT)
            self.assertNotEqual(result.returncode, 0)
        launcher = (
            "import os,sys; os.environ['LISTEN_PID']=str(os.getpid()); "
            "os.environ['LISTEN_FDS']=sys.argv[1]; "
            "os.execv(sys.argv[2],sys.argv[2:])"
        )
        for count in ("0", "2", "1", "-1", "01", "99999999999999999999999"):
            result = subprocess.run([sys.executable, "-c", launcher, count, str(BINARY)],
                                    capture_output=True, text=True, timeout=WAIT_TIMEOUT)
            self.assertNotEqual(result.returncode, 0)

    def test_contract_so_peercred_actual_uid_and_invalid_owner_gate_in_native_tests(self):
        listener = self.listener("credentials.sock")
        peer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(peer.close)
        peer.connect(listener.getsockname())
        accepted, _address = listener.accept()
        self.addCleanup(accepted.close)
        import struct
        _pid, uid, _gid = struct.unpack("3i", accepted.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        self.assertEqual(uid, os.getuid())
        # A real different-UID process requires privileges; the preload regression
        # below injects an alien UID at the kernel boundary without changing users.
        result = subprocess.run([str(BINARY), "--self-test"], capture_output=True,
                                env={**os.environ, "LD_PRELOAD": str(RUNTIME_LIBRARY)},
                                text=True, timeout=WAIT_TIMEOUT)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_contract_so_peercred_other_uid_closed_before_any_json_is_read(self):
        listener = self.listener("alien.sock")
        # Queue bytes before starting rgbcd: send cannot race the credential rejection.
        client = Client(listener.getsockname())
        self.addCleanup(client.close)
        client.socket.sendall(b'not JSON and must not receive a bad_request reply\n')
        daemon = Daemon(self.directory / "alien-uid", demo=True, alien_uid=True,
                        activation=listener)
        self.addCleanup(daemon.close)
        try:
            data = client.socket.recv(4096)
        except ConnectionResetError:
            data = b""
        self.assertEqual(data, b"")
        self.assertIsNone(daemon.process.poll())

    def test_contract_idle_30s_exit_60s_subscription_survival_and_socket_reactivation(self):
        listener = self.listener("lifetime.sock")
        inode = Path(listener.getsockname()).stat().st_ino
        private_started = time.monotonic()
        private = Daemon(self.directory / "private", demo=True)
        self.addCleanup(private.close)
        empty_started = time.monotonic()
        empty = Daemon(self.directory / "empty", demo=True, activation=listener)
        self.addCleanup(empty.close)
        idle = Daemon(self.directory / "idle", demo=True)
        self.addCleanup(idle.close)
        idle_client = idle.client()
        self.addCleanup(idle_client.close)
        idle_started = time.monotonic()
        self.assertTrue(idle_client.request("hello")["ok"])
        active = Daemon(self.directory / "active", demo=True)
        self.addCleanup(active.close)
        active_client = active.client()
        self.addCleanup(active_client.close)
        active_client.request("subscribe", {"topics": ["sensors"], "interval_ms": 10000})

        def idle_closed():
            self.assertIsNone(active.process.poll())
            if not select.select([idle_client.socket], [], [], 0)[0]:
                return False
            self.assertEqual(idle_client.socket.recv(1), b"")
            return True

        wait_until(idle_closed, timeout=90, message="idle connection to close after 30 s")
        self.assertGreaterEqual(time.monotonic() - idle_started, 29)
        def all_exited():
            self.assertIsNone(active.process.poll())
            done = True
            for daemon, started in ((private, private_started), (empty, empty_started)):
                if daemon.process.poll() is None:
                    done = False
                else:
                    self.assertEqual(daemon.process.returncode, 0)
                    self.assertGreaterEqual(time.monotonic() - started, 59)
            return done

        wait_until(all_exited, timeout=90, message="daemons without clients to exit after 60 s")
        self.assertFalse(private.path.exists())
        self.assertTrue(active_client.request("hello")["ok"])
        self.assertEqual(Path(listener.getsockname()).stat().st_ino, inode)
        replacement = Daemon(self.directory / "reactivated", demo=True, activation=listener)
        self.addCleanup(replacement.close)
        peer = replacement.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("hello")["ok"])


class PowerProfilesContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-profiles-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        # --config-file replaces --session's default config; this is a private session
        # masquerading as the system bus exclusively through the child's environment.
        self.bus = subprocess.Popen([
            "dbus-daemon", "--config-file=" + str(REPO / "tests/fakes/system-bus.conf"),
            "--nofork", "--print-address=1",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, self.bus)
        self.address = self.bus_address()
        self.environment = {"DBUS_SYSTEM_BUS_ADDRESS": self.address}
        self.fake = None
        self.start_fake()
        self.daemon = Daemon(self.directory / "core", environment=self.environment, clock=True)
        self.addCleanup(self.daemon.close)
        self.client = self.daemon.client()
        self.addCleanup(self.client.close)

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=WAIT_TIMEOUT)

    def bus_address(self):
        self.assertTrue(select.select([self.bus.stdout], [], [], WAIT_TIMEOUT)[0])
        value = self.bus.stdout.readline().decode().strip()
        self.assertTrue(value.startswith("unix:"), value)
        return value

    def line(self, process):
        self.assertTrue(select.select([process.stdout], [], [], WAIT_TIMEOUT)[0],
                        "fake did not answer")
        value = process.stdout.readline()
        self.assertTrue(value, "fake exited unexpectedly")
        return json.loads(value)

    def start_fake(self):
        self.fake = subprocess.Popen([str(POWER_PROFILES_FAKE)],
                                     env={**os.environ, **self.environment},
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE)
        self.addCleanup(self.stop, self.fake)
        self.assertEqual(self.line(self.fake), {"ready": True})

    def command(self, **value):
        self.fake.stdin.write(json.dumps(value).encode() + b"\n")
        self.fake.stdin.flush()
        return self.line(self.fake)

    def names(self):
        return set(self.command(action="names")["names"])

    def assert_error(self, response, code):
        self.assertFalse(response["ok"], response)
        self.assertEqual(response["error"]["code"], code)

    def test_get_reads_all_properties_and_profile_entries(self):
        self.command(degraded="high-operating-temperature")
        response = self.client.request("profile.get", {"profile": "performance"})
        self.assertEqual(response["result"], {
            "profile": "balanced", "available": ["power-saver", "balanced", "performance"],
            "degraded": "high-operating-temperature",
        })
        self.assertEqual(self.command()["sets"], 0)

    def test_set_each_contract_profile_and_confirm_state(self):
        for profile in ("performance", "power-saver", "balanced"):
            self.daemon.advance(1, self.client)
            response = self.client.request("profile.set", {"profile": profile})
            self.assertTrue(response["ok"], response)
            self.assertEqual(response["result"]["profile"], profile)
            self.assertEqual(self.client.request("profile.get")["result"], response["result"])
        self.assertEqual(self.command()["sets"], 3)

    def test_set_rejects_invalid_names_and_types_without_bus_interest(self):
        baseline = self.names()
        for value in (None, True, 1, [], {}, "", "turbo", "Balanced", "balanced\n"):
            self.assert_error(self.client.request("profile.set", {"profile": value}), "bad_request")
        self.assert_error(self.client.request("profile.set"), "bad_request")
        self.assertEqual(self.names(), baseline)
        self.assertEqual(self.command()["gets"], 0)

    def test_set_unavailable_profile_is_bad_request_without_write(self):
        self.command(available=["power-saver", "balanced"])
        self.assert_error(self.client.request("profile.set", {"profile": "performance"}),
                          "bad_request")
        self.assertEqual(self.command()["sets"], 0)

    def test_daemon_absent_returns_unavailable_then_recovers(self):
        self.stop(self.fake)
        for op in ("profile.get", "profile.set"):
            self.assert_error(self.client.request(op, {"profile": "balanced"}), "unavailable")
        self.start_fake()
        self.assertEqual(self.client.request("profile.get")["result"]["profile"], "balanced")

    def test_failed_bus_returns_unavailable(self):
        daemon = Daemon(self.directory / "absent-bus")
        self.addCleanup(daemon.close)
        client = daemon.client()
        self.addCleanup(client.close)
        self.assert_error(client.request("profile.get"), "unavailable")

    def test_set_response_waits_for_confirmation_and_other_requests_keep_running(self):
        self.command(hold=True)
        self.client.send({"v": 1, "id": 99, "op": "profile.set",
                          "params": {"profile": "performance"}})
        wait_until(lambda: self.command()["held"], message="Set to reach fake service")
        self.assertFalse(select.select([self.client.socket], [], [], 0)[0])
        self.assertTrue(self.client.request("hello")["ok"])
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("sensors")["ok"])
        self.command(action="release")
        response = self.client.read()
        self.assertEqual(response["id"], 99)
        self.assertEqual(response["result"]["profile"], "performance")

    def test_set_cannot_report_success_when_daemon_does_not_apply_change(self):
        self.command(ignore=True)
        self.assert_error(self.client.request("profile.set", {"profile": "performance"}),
                          "unavailable")

    def test_set_denied_returns_blocked(self):
        self.command(reject=True)
        self.assert_error(self.client.request("profile.set", {"profile": "performance"}), "blocked")

    def test_external_signal_and_invalidation_emit_profile_without_polling(self):
        self.assertTrue(self.client.request("subscribe", {"topics": ["profile"]})["ok"])
        # This read is also a barrier after the asynchronous subscription setup.
        self.client.request("profile.get")
        for invalidated, profile in ((False, "power-saver"), (True, "performance")):
            self.command(action="change", profile=profile, degraded="test", invalidated=invalidated)
            data = self.client.event("profile")["data"]
            self.assertEqual(data["profile"], profile)
            self.assertEqual(data["degraded"], "test")
            self.assertEqual(data["available"], ["power-saver", "balanced", "performance"])
        gets = self.command()["gets"]
        self.daemon.advance(60, self.client)
        time.sleep(0.7)
        self.assertEqual(self.command()["gets"], gets)
        self.assertFalse(select.select([self.client.socket], [], [], 0)[0])

    def test_set_rate_limit_is_two_per_second_per_connection(self):
        for profile in ("power-saver", "balanced"):
            self.assertTrue(self.client.request("profile.set", {"profile": profile})["ok"])
        self.assert_error(self.client.request("profile.set", {"profile": "performance"}),
                          "rate_limited")
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("profile.set", {"profile": "performance"})["ok"])
        self.daemon.advance(1, self.client)
        self.assertTrue(self.client.request("profile.set", {"profile": "balanced"})["ok"])
        self.assertEqual(self.command()["sets"], 4)

    def test_no_interest_does_not_connect_and_operations_release_the_bus(self):
        baseline = self.names()
        self.client.request("sensors")
        self.client.request("status")
        self.client.request("subscribe", {"topics": ["sensors", "devices"]})
        self.daemon.advance(2, self.client)
        time.sleep(0.2)
        self.assertEqual(self.names(), baseline)
        self.assertEqual(self.command()["gets"], 0)
        self.client.request("profile.get")
        wait_until(lambda: self.names() == baseline, message="operation bus connection released")
        self.client.request("subscribe", {"topics": ["profile"]})
        wait_until(lambda: len(self.names() - baseline) == 1, message="subscriber bus connection")
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        peer.request("subscribe", {"topics": ["profile"]})
        self.client.request("unsubscribe")
        # A request provides a barrier while the second subscriber still holds the bus.
        peer.request("profile.get")
        self.assertEqual(len(self.names() - baseline), 1)
        peer.request("unsubscribe")
        wait_until(lambda: self.names() == baseline, message="unsubscribe bus connection released")
        peer.request("subscribe", {"topics": ["profile"]})
        wait_until(lambda: len(self.names() - baseline) == 1, message="resubscription")
        peer.close()
        wait_until(lambda: self.names() == baseline, message="closed subscriber releases bus")

    def test_no_interest_never_attempts_bus_handshake_and_slow_bus_does_not_block_api(self):
        trap = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(trap.close)
        path = self.directory / "trap.sock"
        trap.bind(str(path))
        trap.listen()
        daemon = Daemon(self.directory / "slow-bus", environment={
            "DBUS_SYSTEM_BUS_ADDRESS": "unix:path=" + str(path),
        })
        self.addCleanup(daemon.close)
        client = daemon.client()
        self.addCleanup(client.close)
        client.request("subscribe", {"topics": ["sensors", "devices"], "interval_ms": 500})
        self.assertTrue(client.request("sensors")["ok"])
        self.assertFalse(select.select([trap], [], [], 0.7)[0], "unexpected D-Bus connection")
        client.send({"v": 1, "id": 99, "op": "profile.get"})
        self.assertTrue(select.select([trap], [], [], WAIT_TIMEOUT)[0])
        handshake, _address = trap.accept()
        self.addCleanup(handshake.close)
        # Leave D-Bus authentication unanswered until API responsiveness is established.
        peer = daemon.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("hello")["ok"])
        self.assertTrue(peer.request("sensors")["ok"])
        handshake.close()
        response = client.read()
        while "event" in response:
            response = client.read()
        self.assertEqual(response["id"], 99)
        self.assert_error(response, "unavailable")

    def test_disconnect_during_pending_set_is_safe(self):
        self.command(hold=True)
        self.client.send({"v": 1, "id": 99, "op": "profile.set",
                          "params": {"profile": "performance"}})
        wait_until(lambda: self.command()["held"], message="pending Set")
        self.client.close()
        self.command(action="release")
        peer = self.daemon.client()
        self.addCleanup(peer.close)
        self.assertEqual(peer.request("profile.get")["result"]["profile"], "performance")


class BootstrapContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-bootstrap-")
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.stubs = self.home / "stubs"
        self.stubs.mkdir()
        self.log = self.home / "systemctl.jsonl"
        self.environment = {
            **os.environ, "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "XDG_RUNTIME_DIR": str(self.home / "runtime"),
            "PATH": str(self.stubs) + os.pathsep + os.environ["PATH"],
            "CORE_TEST_BINARY": str(BINARY), "CORE_TEST_LOG": str(self.log),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        self.environment.pop("CXX", None)
        self.environment.pop("CXXFLAGS", None)
        self.state = self.home / "state/omarchy-rgb-cooling"
        self.units = self.home / "config/systemd/user"
        self.stub("systemctl", '''import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CORE_TEST_LOG'],'a') as output:
    output.write(json.dumps(args)+'\\n')
if os.environ.get('CORE_TEST_FAIL_SYSTEMCTL'):
    sys.exit(1)
if args == ['--user','enable','--now','omarchy-rgb-cooling.socket']:
    config=os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config'))
    units=Path(config)/'systemd/user'
    link=units/'sockets.target.wants/omarchy-rgb-cooling.socket'
    if not link.is_symlink():
        link.symlink_to(units/'omarchy-rgb-cooling.socket')
''')
        # Compile once per module. This compiler stub makes bootstrap tests fast while
        # still exercising discovery, compiler identity/version, flags and atomic publish.
        self.stub("g++", '''import os,shutil,sys
if '--version' in sys.argv:
    print('test compiler '+os.environ.get('CORE_TEST_COMPILER_VERSION','1'))
else:
    output=sys.argv[sys.argv.index('-o')+1]
    if os.environ.get('CORE_TEST_FAIL_COMPILE'):
        with open(output,'w') as stream:
            stream.write('partial output')
        sys.exit(1)
    shutil.copy2(os.environ['CORE_TEST_BINARY'],output)
''')
        self.stub("omarchy", "raise SystemExit('omarchy must never be invoked by bootstrap')\n")

    def stub(self, name, body):
        path = self.stubs / name
        path.write_text(f"#!{sys.executable}\n" + body)
        path.chmod(0o755)

    def bootstrap(self, source=REPO, *, success=True):
        result = subprocess.run([sys.executable, str(REPO / "bootstrap.py"), str(source)],
                                capture_output=True, text=True, env=self.environment, timeout=30)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual(value["ok"], success)
        self.assertEqual(set(value), {"ok"} if success else {"ok", "error"})
        return value

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def test_contract_bootstrap_exact_footprint_ledger_directories_and_socket_only_enable(self):
        self.bootstrap()
        expected_files = {
            self.state / "bin/rgbcd", self.state / ".core-version",
            self.state / ".bootstrap.lock", self.state / "installed-files",
            self.units / "omarchy-rgb-cooling.socket",
            self.units / "omarchy-rgb-cooling.service",
            self.units / "omarchy-rgb-cooling-openrgb.service",
            self.units / "sockets.target.wants/omarchy-rgb-cooling.socket",
        }
        directories = {
            self.home / "state", self.state, self.state / "bin", self.home / "config",
            self.home / "config/systemd", self.units, self.units / "sockets.target.wants",
            self.state / "openrgb",
        }
        ledger = set((self.state / "installed-files").read_text().splitlines())
        expected_ledger = {str(path) for path in expected_files}
        expected_ledger.update(str(path) + "/" for path in directories)
        self.assertEqual(ledger, expected_ledger)
        actual = {path for root in (self.home / "config", self.home / "state")
                  for path in root.rglob("*") if path.is_file() or path.is_symlink()}
        self.assertEqual(actual, expected_files)
        self.assertFalse((self.home / "runtime").exists())
        self.assertEqual(self.commands(), [
            ["--user", "daemon-reload"],
            ["--user", "enable", "--now", "omarchy-rgb-cooling.socket"],
            ["--user", "try-restart", "omarchy-rgb-cooling.service"],
        ])
        service = (self.units / "omarchy-rgb-cooling.service").read_text()
        self.assertIn(f'ExecStart=:"{self.state}/bin/rgbcd"', service)
        self.assertIn(f' --data-dir "{REPO}/data"', service)
        self.assertNotIn("[Install]", service)
        self.assertEqual(stat.S_IMODE((self.state / "installed-files").stat().st_mode), 0o600)

    def test_contract_bootstrap_openrgb_unit_in_ledger_and_never_started(self):
        self.bootstrap()
        path = self.units / "omarchy-rgb-cooling-openrgb.service"
        content = path.read_text()
        self.assertNotIn("[Install]", content)
        self.assertIn(f'ExecStart=:"{REPO}/bin/omarchy-rgb-openrgb"', content)
        self.assertIn(f'ReadWritePaths="{self.state}/openrgb"', content)
        self.assertIn(str(path), (self.state / "installed-files").read_text().splitlines())
        self.assertFalse(any("openrgb.service" in " ".join(cmd) for cmd in self.commands()))

    def test_bootstrap_user_settings_created_0700_outside_ledger_and_preserved(self):
        self.bootstrap()
        settings = self.home / "config/omarchy-rgb-cooling"
        self.assertTrue(settings.is_dir())
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o700)
        labels = settings / "labels.json"
        labels.write_text('{"v":1,"labels":{"fan":"CPU"}}')
        before = labels.read_bytes(), settings.stat().st_ino
        for permissions in (0o755, 0o777, 0o2700, 0o000):
            with self.subTest(permissions=oct(permissions)):
                settings.chmod(permissions)
                self.bootstrap()
                self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o700)
                self.assertEqual((labels.read_bytes(), settings.stat().st_ino), before)
        ledger = (self.state / "installed-files").read_text().splitlines()
        self.assertNotIn(str(settings), ledger)
        self.assertNotIn(str(settings) + "/", ledger)
        self.assertNotIn(str(labels), ledger)
        self.assertEqual(len(self.commands()), 3)

    def test_bootstrap_user_settings_symlink_file_and_foreign_owner_not_chmodded(self):
        import bootstrap

        config = self.home / "config"
        config.mkdir()
        settings = config / "omarchy-rgb-cooling"
        target = self.home / "other-data"
        target.mkdir(mode=0o755)
        target.chmod(0o755)
        settings.symlink_to(target, target_is_directory=True)
        self.bootstrap()
        self.assertTrue(settings.is_symlink())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)
        settings.unlink()
        settings.write_text("existing file")
        settings.chmod(0o644)
        self.bootstrap()
        self.assertEqual(settings.read_text(), "existing file")
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o644)
        settings.unlink()
        settings.symlink_to(self.home / "missing")
        self.bootstrap()
        self.assertTrue(settings.is_symlink())
        self.assertFalse(settings.exists())
        settings.unlink()
        settings.mkdir(mode=0o755)
        settings.chmod(0o755)
        # Simulate a directory owned by another UID without privileged chown.
        with patch.object(bootstrap.os, "getuid", return_value=settings.stat().st_uid + 1):
            bootstrap.user_directory(settings)
        self.assertEqual(stat.S_IMODE(settings.stat().st_mode), 0o755)

    def test_contract_bootstrap_idempotent_no_changes_no_systemctl_or_binary_replacement(self):
        self.bootstrap()
        binary = self.state / "bin/rgbcd"
        files = [path for path in self.state.rglob("*") if path.is_file()]
        before = {path: (path.stat().st_ino, path.stat().st_mtime_ns) for path in files}
        commands = self.commands()
        self.bootstrap()
        self.assertEqual(self.commands(), commands)
        self.assertEqual(binary.stat().st_ino, before[binary][0])
        for path in files:
            self.assertEqual((path.stat().st_ino, path.stat().st_mtime_ns), before[path])

    def test_contract_bootstrap_flock_serializes_parallel_installers(self):
        arguments = [sys.executable, str(REPO / "bootstrap.py"), str(REPO)]
        processes = [subprocess.Popen(arguments, env=self.environment, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE) for _index in range(2)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode() + stdout.decode())
            self.assertEqual(json.loads(stdout), {"ok": True})
        self.assertEqual(sum("daemon-reload" in cmd for cmd in self.commands()), 1)
        ledger = (self.state / "installed-files").read_text().splitlines()
        self.assertEqual(len(ledger), len(set(ledger)))
        self.assertIn(str(self.state) + "/", ledger)
        self.assertIn(str(self.units) + "/", ledger)
        self.assertEqual(list(self.state.glob("build-*")), [])

    def test_contract_bootstrap_failed_build_keeps_previous_binary_and_fingerprint_atomic(self):
        self.bootstrap()
        binary = self.state / "bin/rgbcd"
        before = binary.read_bytes()
        inode = binary.stat().st_ino
        marker = (self.state / ".core-version").read_text()
        commands = self.commands()
        self.environment["CXXFLAGS"] = "-DREBUILD_REQUIRED=1"
        self.environment["CORE_TEST_FAIL_COMPILE"] = "1"
        self.bootstrap(success=False)
        self.assertEqual(binary.read_bytes(), before)
        self.assertEqual(binary.stat().st_ino, inode)
        self.assertEqual((self.state / ".core-version").read_text(), marker)
        self.assertEqual(self.commands(), commands)
        self.assertEqual(list(self.state.glob("build-*")), [])

    def test_contract_bootstrap_sources_and_build_script_invalidate_fingerprint(self):
        source = self.home / "source"
        source.mkdir()
        for name in ("src", "systemd"):
            shutil.copytree(REPO / name, source / name)
        shutil.copy2(REPO / "native_build.py", source / "native_build.py")
        self.bootstrap(source)
        marker = (self.state / ".core-version").read_text()
        with (source / "src/main.cpp").open("a") as stream:
            stream.write("\n// test source change\n")
        self.bootstrap(source)
        changed = (self.state / ".core-version").read_text()
        self.assertNotEqual(marker, changed)
        with (source / "native_build.py").open("a") as stream:
            stream.write("\n# test build script change\n")
        self.bootstrap(source)
        self.assertNotEqual(changed, (self.state / ".core-version").read_text())

    def test_contract_bootstrap_compiler_version_and_effective_flags_invalidate_fingerprint(self):
        self.bootstrap()
        original = (self.state / ".core-version").read_text()
        self.environment["CORE_TEST_COMPILER_VERSION"] = "2"
        self.bootstrap()
        changed = (self.state / ".core-version").read_text()
        self.assertNotEqual(original, changed)
        self.environment["CXXFLAGS"] = "-DCORE_TEST_FLAG=1"
        self.bootstrap()
        self.assertNotEqual(changed, (self.state / ".core-version").read_text())
        for command in self.commands():
            if "enable" in command:
                self.assertEqual(command[-1], "omarchy-rgb-cooling.socket")
        self.assertEqual(sum("daemon-reload" in cmd for cmd in self.commands()), 3)

    def test_contract_bootstrap_default_xdg_paths_and_compiler_path_identity(self):
        for variable in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
            self.environment.pop(variable, None)
        self.bootstrap()
        state = self.home / ".local/state/omarchy-rgb-cooling"
        ledger = (state / "installed-files").read_text().splitlines()
        self.assertIn(str(self.home / ".local") + "/", ledger)
        self.assertIn(str(self.home / ".local/state") + "/", ledger)
        self.assertIn(str(self.home / ".config/systemd/user/omarchy-rgb-cooling.socket"), ledger)
        original = (state / ".core-version").read_text()
        shutil.copy2(self.stubs / "g++", self.stubs / "other-c++")
        self.environment["CXX"] = str(self.stubs / "other-c++")
        self.bootstrap()
        self.assertNotEqual(original, (state / ".core-version").read_text())

    def test_contract_bootstrap_preexisting_directories_not_recorded_and_failed_command_json(self):
        self.units.mkdir(parents=True)
        self.state.mkdir(parents=True)
        self.environment["CORE_TEST_FAIL_SYSTEMCTL"] = "1"
        result = self.bootstrap(success=False)
        self.assertIsInstance(result["error"], str)
        ledger = (self.state / "installed-files").read_text().splitlines()
        self.assertNotIn(str(self.units) + "/", ledger)
        self.assertNotIn(str(self.state) + "/", ledger)
        self.assertIn(str(self.state / "bin") + "/", ledger)

    def test_contract_bootstrap_safe_execstart_percent_quotes_backslash_and_reject_newlines(self):
        self.environment["XDG_STATE_HOME"] = str(self.home / 'state % " \\ $dir')
        self.bootstrap()
        service = (self.units / "omarchy-rgb-cooling.service").read_text()
        self.assertIn('%%', service)
        self.assertIn('\\"', service)
        self.assertIn('\\\\', service)
        self.assertIn('$dir', service)
        self.environment["XDG_STATE_HOME"] = str(self.home / "bad\nstate")
        result = self.bootstrap(success=False)
        self.assertIn("control characters", result["error"])
        self.assertFalse((self.home / "bad\nstate").exists())

    def test_contract_bootstrap_data_directory_escapes_plugin_path_and_rejects_newlines(self):
        plugins = self.home / ".config/omarchy/plugins"
        source = plugins / 'plugin % " \\ $data'
        source.mkdir(parents=True)
        for name in ("src", "systemd"):
            shutil.copytree(REPO / name, source / name)
        shutil.copy2(REPO / "native_build.py", source / "native_build.py")
        self.bootstrap(source)
        service = (self.units / "omarchy-rgb-cooling.service").read_text()
        expected_data = str(plugins) + r'/plugin %% \" \\ $data/data'
        expected = f'ExecStart=:"{self.state}/bin/rgbcd" --data-dir "{expected_data}"'
        self.assertIn(expected + "\n", service)
        self.assertIn("ProtectHome=read-only\n", service)
        before = self.commands()
        for character in ("\n", "\r"):
            result = self.bootstrap(plugins / ("bad" + character + "plugin"), success=False)
            self.assertIn("control characters", result["error"])
        self.assertEqual(self.commands(), before)

    def test_contract_bootstrap_unchanged_units_do_not_reenable_a_disabled_socket(self):
        self.bootstrap()
        (self.units / "sockets.target.wants/omarchy-rgb-cooling.socket").unlink()
        before = self.commands()
        self.bootstrap()
        self.assertEqual(self.commands(), before)

    def test_contract_bootstrap_failed_activation_is_retried_on_next_run(self):
        self.environment["CORE_TEST_FAIL_SYSTEMCTL"] = "1"
        self.bootstrap(success=False)
        self.assertFalse((self.state / ".core-version").exists())
        self.environment.pop("CORE_TEST_FAIL_SYSTEMCTL")
        self.bootstrap()
        self.assertTrue((self.state / ".core-version").is_file())
        self.assertEqual(sum("daemon-reload" in cmd for cmd in self.commands()), 2)

    def test_contract_bootstrap_relative_xdg_path_rejected(self):
        self.environment["XDG_CONFIG_HOME"] = "relative"
        result = self.bootstrap(success=False)
        self.assertIn("absolute", result["error"])

    def test_contract_bootstrap_units_changed_reload_try_restart_and_no_service_enable(self):
        self.bootstrap()
        destination = self.units / "omarchy-rgb-cooling.service"
        destination.write_text(destination.read_text() + "# drift\n")
        original_binary = (self.state / "bin/rgbcd").stat().st_ino
        self.bootstrap()
        self.assertNotIn("# drift", destination.read_text())
        self.assertEqual((self.state / "bin/rgbcd").stat().st_ino, original_binary)
        self.assertEqual(sum("daemon-reload" in cmd for cmd in self.commands()), 2)
        self.assertEqual(sum("try-restart" in cmd for cmd in self.commands()), 2)
        self.assertFalse(any("enable" in cmd and cmd[-1].endswith(".service")
                             for cmd in self.commands()))


if __name__ == "__main__":
    unittest.main()
