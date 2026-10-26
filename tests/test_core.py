"""API.md contract regressions; stdlib-only and isolated from the user's hardware."""
# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import select
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from fakes.hwmon import FileWatch, HwmonTree
from fakes.openrgb import OpenRgbServer, controller

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
BUILD_DIRECTORY = None
BINARY = None
PEERCRED_LIBRARY = None


def setUpModule():
    """Compile exactly once for this module, in a disposable directory."""
    global BUILD_DIRECTORY, BINARY, PEERCRED_LIBRARY
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
    result = subprocess.run([
        compiler, "-std=c++20", "-shared", "-fPIC", str(REPO / "tests/fakes/peercred.cpp"),
        "-ldl", "-o", str(PEERCRED_LIBRARY),
    ], capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)


def tearDownModule():
    if BUILD_DIRECTORY is not None:
        BUILD_DIRECTORY.cleanup()


class Client:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(4)
        self.socket.connect(str(path))
        self.input = b""
        self.sequence = 0
        self.events = []

    def send(self, value):
        self.socket.sendall(json.dumps(value).encode() + b"\n")

    def read(self, timeout=4):
        deadline = time.monotonic() + timeout
        while b"\n" not in self.input:
            self.socket.settimeout(max(0.001, deadline - time.monotonic()))
            chunk = self.socket.recv(65536)
            if not chunk:
                raise EOFError("Core closed the connection")
            self.input += chunk
        line, self.input = self.input.split(b"\n", 1)
        return json.loads(line)

    def request(self, operation, params=None):
        self.sequence += 1
        self.send({"v": 1, "id": self.sequence, "op": operation, "params": params or {}})
        while True:
            response = self.read()
            if "event" in response:
                self.events.append(response)
                continue
            if response["id"] != self.sequence:
                raise AssertionError(response)
            return response

    def event(self, topic):
        for index, event in enumerate(self.events):
            if event["event"] == topic:
                return self.events.pop(index)
        while True:
            event = self.read()
            if event.get("event") == topic:
                return event

    def close(self):
        self.socket.close()


class Daemon:
    def __init__(self, directory, *, demo=False, activation=None, extra=None, alien_uid=False):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.tree = HwmonTree(self.directory / "hwmon")
        self.path = self.directory / "core.sock"
        environment = os.environ.copy()
        for variable in ("LISTEN_FDS", "LISTEN_PID", "LISTEN_FDNAMES"):
            environment.pop(variable, None)
        if alien_uid:
            environment["LD_PRELOAD"] = str(PEERCRED_LIBRARY)
        arguments = [str(BINARY), "--hwmon-root", str(self.tree.root)]
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
        deadline = time.monotonic() + 10
        while not self.path.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                self.close()
                raise RuntimeError("rgbcd did not create its socket: " + self.stderr)
            time.sleep(0.02)
        self.stderr = ""

    def client(self):
        return Client(self.path)

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
        try:
            _stdout, stderr = self.process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            _stdout, stderr = self.process.communicate()
        self.stderr = stderr.decode(errors="replace")


class CoreContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-api-")
        self.addCleanup(self.temporary.cleanup)
        self.daemon = Daemon(self.temporary.name, demo=True)
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
        for identifier in (1, 2**32, 2**53 + 1, 2**63 - 1, 2**64):
            self.client.send({"v": 1, "id": identifier, "op": "hello"})
            response = self.client.read()
            self.assertTrue(response["ok"])
            self.assertEqual(response["id"], identifier)

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
                                    capture_output=True, text=True, timeout=5)
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
                                          "source", "stale"})
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
        time.sleep(1.05)
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
        started = time.monotonic()
        self.client.event("sensors")
        self.assertGreaterEqual(time.monotonic() - started, 0.35)
        self.assertEqual(self.client.request("unsubscribe")["result"], {})
        self.client.events.clear()
        self.assertEqual(self.client.input, b"")
        self.assertEqual(select.select([self.client.socket], [], [], 0.6)[0], [])
        self.client.request("subscribe", {"topics": ["sensors"], "interval_ms": 999999999})
        self.client.event("sensors")
        started = time.monotonic()
        self.client.event("sensors")
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 9.5)
        self.assertLess(elapsed, 12)


class HwmonContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-hwmon-")
        self.addCleanup(self.temporary.cleanup)
        self.fake = OpenRgbServer(descriptors=[])
        self.addCleanup(self.fake.close)
        self.daemon = Daemon(self.temporary.name)
        self.addCleanup(self.daemon.close)
        self.client = self.daemon.client()
        self.addCleanup(self.client.close)

    def subscribe(self):
        self.assertTrue(self.client.request("subscribe", {
            "topics": ["sensors"], "interval_ms": 500,
        })["ok"])
        return self.client.event("sensors")["data"]

    def test_contract_hwmon_read_only_only_with_sensor_subscribers_primary_cpu_and_units(self):
        watch = FileWatch(self.daemon.tree.cpu / "temp1_input")
        self.addCleanup(watch.close)
        before = self.daemon.tree.snapshot()
        watch.drain()
        self.assertEqual(self.client.request("sensors")["result"], {"sensors": [], "primary": ""})
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 500})
        self.client.event("devices")
        self.assertEqual(watch.drain(), [])
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
        time.sleep(0.7)
        self.client.request("sensors")
        self.assertEqual(watch.drain(), [])
        self.assertEqual(before, self.daemon.tree.snapshot())

    def test_contract_hwmon_stable_ids_never_hwmon_number_and_rescan_hotplug(self):
        initial = self.subscribe()
        target = self.daemon.tree.cpu
        replacement = target.with_name("hwmon99")
        target.rename(replacement)
        (replacement / "temp1_input").write_text("43000")
        (self.daemon.tree.root / "hwmon8").unlink()
        (self.daemon.tree.root / "hwmon99").symlink_to(replacement, target_is_directory=True)
        deadline = time.monotonic() + 3
        while True:
            data = self.client.event("sensors")["data"]
            sensor = next(item for item in data["sensors"] if item["id"] == initial["primary"])
            if sensor["value"] == 43:
                break
            self.assertLess(time.monotonic(), deadline)
        self.assertEqual(data["primary"], initial["primary"])
        self.assertFalse(any("hwmon" in item["id"] for item in data["sensors"]))

    def test_contract_hwmon_nan_missing_failed_read_null_and_stale_after_three_intervals(self):
        data = self.subscribe()
        primary = data["primary"]
        for invalid in ("NaN", "inf", "-inf", "not a number", ""):
            (self.daemon.tree.cpu / "temp1_input").write_text(invalid)
            data = self.client.event("sensors")["data"]
            sensor = next(item for item in data["sensors"] if item["id"] == primary)
            self.assertIsNone(sensor["value"])
        (self.daemon.tree.cpu / "temp1_input").unlink()
        deadline = time.monotonic() + 3
        while True:
            data = self.client.event("sensors")["data"]
            sensor = next(item for item in data["sensors"] if item["id"] == primary)
            self.assertIsNone(sensor["value"])
            if sensor["stale"]:
                break
            self.assertLess(time.monotonic(), deadline)
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


class OpenRgbContract(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rgbcd-sdk-")
        self.addCleanup(self.temporary.cleanup)
        self.counter = 0

    def launch(self, **options):
        fake = OpenRgbServer(**options)
        self.addCleanup(fake.close)
        self.counter += 1
        daemon = Daemon(Path(self.temporary.name) / str(self.counter))
        self.addCleanup(daemon.close)
        client = daemon.client()
        self.addCleanup(client.close)
        return fake, daemon, client

    def wait_state(self, client, expected, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            engine = client.request("status")["result"]["engines"][0]
            if engine["state"] == expected:
                return engine
            time.sleep(0.03)
        self.fail(f"Expected {expected}, got {engine}")

    def test_contract_openrgb_negotiates_version_fragments_and_blocks_all_real_writes(self):
        fake, daemon, client = self.launch(fragment=True)
        self.wait_state(client, "blocked")
        self.assertFalse(client.request("hello")["result"]["demo"])
        before = daemon.tree.snapshot()
        device = client.request("devices")["result"]["devices"][0]
        self.assertEqual(device["support"], "recognized")
        self.assertFalse(device["writable"])
        for gate in ("identity", "ownership", "exclusions", "support"):
            self.assertIn(gate, device["blocked_reason"])
        self.assertEqual(device["capabilities"], ["lighting.read"])
        lighting = client.request("lighting.get", {"device": device["id"]})["result"]
        self.assertEqual(lighting, {"device": device["id"], "color": "#112233",
                                    "brightness": 100, "brightness_emulated": False})
        response = client.request("lighting.set", {
            "device": device["id"], "color": "#ffffff", "brightness": 100,
        })
        self.assertEqual(response["error"]["code"], "blocked")
        self.assertEqual(before, daemon.tree.snapshot())
        self.assertEqual(fake.commands[0][1:], (40, b"\x01\x00\x00\x00"))
        self.assertTrue(all(command in (0, 1, 40) for _device, command, _payload in fake.commands))

    def test_contract_trofeo_0416_5302_excluded_never_opened_and_no_capabilities(self):
        fake, _daemon, client = self.launch(descriptors=[
            controller(), controller("Trofeo", "USB:0416:5302:port2"),
        ])
        self.wait_state(client, "blocked")
        devices = client.request("devices")["result"]["devices"]
        excluded = next(device for device in devices if device["excluded"])
        self.assertFalse(excluded["writable"])
        self.assertEqual(excluded["capabilities"], [])
        self.assertIn("omarchy-trcc", excluded["blocked_reason"])
        for operation in ("lighting.get", "lighting.set"):
            response = client.request(operation, {
                "device": excluded["id"], "color": "#000000", "brightness": 0,
            })
            self.assertEqual(response["error"]["code"], "blocked")
        # Enumeration is descriptor-only; no open, detection or write SDK command is sent.
        self.assertTrue(all(command in (0, 1, 40) for _device, command, _payload in fake.commands))

    def test_contract_openrgb_unsupported_without_static_read_capability(self):
        _fake, _daemon, client = self.launch(descriptors=[controller(with_lighting=False)])
        self.wait_state(client, "blocked")
        device = client.request("devices")["result"]["devices"][0]
        response = client.request("lighting.get", {"device": device["id"]})
        self.assertEqual(response["error"]["code"], "unsupported")

    def test_contract_openrgb_stable_identity_across_reordered_protocol_indices(self):
        first = controller()
        second = controller("Other RGB", "USB:1234:abcd:port2", "other")
        fake, _daemon, client = self.launch(descriptors=[first, second])
        self.wait_state(client, "blocked")
        before = client.request("devices")["result"]
        fake.hotplug([second, first])
        self.wait_state(client, "unreachable")
        self.wait_state(client, "blocked", timeout=6)
        self.assertEqual(client.request("devices")["result"], before)

    def test_contract_openrgb_bad_magic_lengths_counts_ids_commands_timeout_unreachable(self):
        for behavior in ("magic", "huge", "huge_count", "wrong_id", "wrong_command", "timeout"):
            with self.subTest(behavior=behavior):
                fake, daemon, client = self.launch(behavior=behavior)
                started = time.monotonic()
                self.assertTrue(client.request("hello")["ok"])
                self.assertLess(time.monotonic() - started, 0.5)
                engine = self.wait_state(client, "unreachable")
                self.assertTrue(engine["reason"])
                self.assertEqual(client.request("devices")["result"], {"devices": []})
                self.assertTrue(client.request("hello")["ok"])
                client.close()
                daemon.close()
                fake.close()

    def test_contract_openrgb_strict_descriptor_inner_lengths_and_truncation(self):
        valid = controller()
        for descriptor in (valid[:-1], valid + b"extra", b"\xff" * 50,
                           valid[:8] + b"\xff\xff" + valid[10:]):
            with self.subTest(length=len(descriptor)):
                fake, daemon, client = self.launch(descriptors=[descriptor])
                self.wait_state(client, "unreachable")
                self.assertEqual(client.request("devices")["result"], {"devices": []})
                client.close()
                daemon.close()
                fake.close()

    def test_contract_openrgb_v0_server_and_absent_server_are_normal_engine_states(self):
        fake, daemon, client = self.launch(advertised=0, descriptors=[controller(version=0)])
        self.wait_state(client, "blocked")
        client.close()
        daemon.close()
        fake.close()
        absent = Daemon(Path(self.temporary.name) / "absent")
        self.addCleanup(absent.close)
        client = absent.client()
        self.addCleanup(client.close)
        engine = self.wait_state(client, "absent")
        self.assertTrue(engine["reason"])
        self.assertTrue(client.request("devices")["ok"])


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
                                    text=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
        launcher = (
            "import os,sys; os.environ['LISTEN_PID']=str(os.getpid()); "
            "os.environ['LISTEN_FDS']=sys.argv[1]; "
            "os.execv(sys.argv[2],sys.argv[2:])"
        )
        for count in ("0", "2", "1", "-1", "01", "99999999999999999999999"):
            result = subprocess.run([sys.executable, "-c", launcher, count, str(BINARY)],
                                    capture_output=True, text=True, timeout=5)
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
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_contract_so_peercred_other_uid_closed_before_any_json_is_read(self):
        daemon = Daemon(self.directory / "alien-uid", demo=True, alien_uid=True)
        self.addCleanup(daemon.close)
        client = daemon.client()
        self.addCleanup(client.close)
        client.socket.sendall(b'not JSON and must not receive a bad_request reply\n')
        try:
            data = client.socket.recv(4096)
        except ConnectionResetError:
            data = b""
        self.assertEqual(data, b"")
        self.assertIsNone(daemon.process.poll())

    def test_contract_idle_30s_exit_60s_subscription_survival_and_socket_reactivation(self):
        listener = self.listener("lifetime.sock")
        inode = Path(listener.getsockname()).stat().st_ino
        empty = Daemon(self.directory / "empty", demo=True, activation=listener)
        self.addCleanup(empty.close)
        idle = Daemon(self.directory / "idle", demo=True)
        self.addCleanup(idle.close)
        idle_client = idle.client()
        self.addCleanup(idle_client.close)
        self.assertTrue(idle_client.request("hello")["ok"])
        active = Daemon(self.directory / "active", demo=True)
        self.addCleanup(active.close)
        active_client = active.client()
        self.addCleanup(active_client.close)
        active_client.request("subscribe", {"topics": ["sensors"], "interval_ms": 10000})
        started = time.monotonic()
        idle_closed = False
        while time.monotonic() - started < 62:
            readable = select.select([idle_client.socket], [], [], 0.2)[0]
            if readable and not idle_closed:
                self.assertEqual(idle_client.socket.recv(1), b"")
                elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, 29)
                self.assertLess(elapsed, 34)
                idle_closed = True
            self.assertIsNone(active.process.poll())
            if empty.process.poll() is not None:
                break
            time.sleep(0.1)
        self.assertTrue(idle_closed)
        self.assertEqual(empty.process.poll(), 0)
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 59)
        self.assertLess(elapsed, 63)
        self.assertTrue(active_client.request("hello")["ok"])
        self.assertEqual(Path(listener.getsockname()).stat().st_ino, inode)
        replacement = Daemon(self.directory / "reactivated", demo=True, activation=listener)
        self.addCleanup(replacement.close)
        peer = replacement.client()
        self.addCleanup(peer.close)
        self.assertTrue(peer.request("hello")["ok"])


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
            self.units / "sockets.target.wants/omarchy-rgb-cooling.socket",
        }
        directories = {
            self.home / "state", self.state, self.state / "bin", self.home / "config",
            self.home / "config/systemd", self.units, self.units / "sockets.target.wants",
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
        self.assertNotIn("[Install]", service)
        self.assertEqual(stat.S_IMODE((self.state / "installed-files").stat().st_mode), 0o600)

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
