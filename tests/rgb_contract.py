"""Phase 3c integration tests, sharing the native build and isolated daemon fixture."""
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import tempfile

from fakes.openrgb import (OpenRgbServer, controller, controller_metadata, mode, mode_bytes, packet,
                           signal_update, string, word)
from fakes.usb import UsbTree, rule


class OpenRgbContractMixin:
    def setUp(self):
        import test_core as core
        self.core = core
        temporary = tempfile.TemporaryDirectory(prefix="rgbc-3c-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.usb = UsbTree(self.root / "sys")
        self.identity = self.usb.add()
        self.usb.add(10, "0416", "5302", "trofeo")
        self.rules = self.root / "rules"
        self.rules.write_text(rule() + rule("0416", "5302", "Trofeo"))
        self.config = self.root / "config/omarchy-rgb-cooling/devices.json"
        self.config.parent.mkdir(parents=True)
        self.enable(False)
        self.bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, self.bus)
        address = self.line(self.bus, plain=True)
        self.environment = {"DBUS_SESSION_BUS_ADDRESS": address,
                            "XDG_CONFIG_HOME": str(self.root / "config")}
        self.manager = subprocess.Popen([str(core.SYSTEMD_FAKE)], env={**os.environ,
                                        **self.environment}, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, self.manager)
        self.assertEqual(self.line(self.manager), {"ready": True})
        self.fake = None
        self.daemon = None
        self.client = None

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=30)

    def line(self, process, plain=False):
        self.assertTrue(select.select([process.stdout], [], [], 30)[0], "fake did not respond")
        value = process.stdout.readline().decode().strip()
        return value if plain else json.loads(value)

    def command(self, **value):
        self.manager.stdin.write(json.dumps(value).encode() + b"\n")
        self.manager.stdin.flush()
        return self.line(self.manager)

    def enable(self, value=True):
        self.config.write_text(json.dumps({"v": 1, "enabled": {self.identity: value}}))

    def launch(self, *, enabled=True, clock=True, **options):
        self.enable(enabled)
        self.fake = OpenRgbServer(**options)
        self.addCleanup(self.fake.close)
        return self.start_daemon(clock=clock)

    def start_daemon(self, directory="core", *, clock=True):
        self.daemon = self.core.Daemon(self.root / directory, clock=clock, environment={
            **self.environment, "CORE_TEST_OPENRGB_PORT": str(self.fake.port)}, extra=[
                "--sys-root", str(self.usb.root), "--openrgb-rules", str(self.rules)])
        self.addCleanup(self.daemon.close)
        self.client = self.daemon.client()
        self.addCleanup(self.client.close)
        return self.client

    def devices(self, operation="devices"):
        reply = self.client.request(operation)
        self.assertTrue(reply["ok"], reply)
        return reply["result"]["devices"]

    def advance(self, seconds):
        # Keep the API connection active: its separate, contractual idle limit is 30 s.
        while seconds > 20:
            self.daemon.advance(20, self.client)
            seconds -= 20
        self.daemon.advance(seconds, self.client)

    def writes(self):
        return [(device, packet, payload) for device, packet, payload in self.fake.commands
                if packet >= 1000]

    def set_color(self, device, color="#123456", brightness=50):
        return self.client.request("lighting.set", {"device": device["id"], "color": color,
                                                    "brightness": brightness})

    def test_candidates_from_strict_rules_never_start_or_contact_openrgb(self):
        self.launch(enabled=False)
        self.rules.write_text(self.rules.read_text() + rule("1234", "abcd", "Unconnected")
                              + rule("1462", "7d98", "Bad").rstrip("\n") + ', RUN+="evil"\n')
        devices = self.devices()
        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual(device["id"], self.identity)
        self.assertEqual(device["usb"], self.identity)
        self.assertEqual(device["name"], "MSI_Mystic_Light")
        self.assertEqual(device["support"], "recognized")
        self.assertFalse(device["writable"])
        self.assertFalse(device["enabled"])
        self.assertEqual(self.fake.commands, [])
        self.assertEqual(self.command()["calls"], [])
        self.assertEqual(self.set_color(device)["error"]["code"], "blocked")
        self.assertEqual(self.fake.commands, [])

    def test_rules_reread_and_invalid_patterns_do_not_become_candidates(self):
        self.launch(enabled=False)
        self.rules.write_text('\n'.join([
            rule().replace('1462', '14.*'), rule().replace('usb|hidraw', 'serial|hidraw'),
            rule().replace('MSI_Mystic_Light', 'uaccess'), rule().rstrip("\n") + ' RUN+="evil"',
        ]))
        self.assertEqual(self.devices(), [])
        self.rules.write_text(rule(name="New_TAG"))
        self.advance(2.01)
        self.assertEqual(self.devices("devices.rescan")[0]["name"], "New_TAG")
        self.assertEqual(self.command()["calls"], [])

    def test_enable_disable_reread_per_scan_and_current_opt_out_blocks_write(self):
        self.launch(enabled=False)
        self.devices()
        self.enable()
        self.advance(2.01)
        device = self.devices("devices.rescan")[0]
        self.assertTrue(device["writable"])
        self.assertTrue(device["enabled"])
        self.assertEqual(device["usb"], self.identity)
        self.assertEqual(self.command()["calls"], [["StartUnit",
                         "omarchy-rgb-cooling-openrgb.service", "replace"]])
        self.enable(False)
        self.assertEqual(self.set_color(device)["error"]["code"], "blocked")
        self.assertEqual(self.writes(), [])
        self.advance(2.01)
        self.assertFalse(self.devices("devices.rescan")[0]["enabled"])

    def test_devices_json_strict_validation_fails_closed(self):
        self.launch(enabled=False)
        malformed = ['{"v":1,"enabled":{"usb:1462:7d98:unique":1}}',
                     '{"v":true,"enabled":{}}', '{"v":2,"enabled":{}}',
                     '{"v":1,"enabled":{},"extra":0}', '{"v":1,"enabled":{"bad":true}}',
                     '{"v":1,"enabled":{},"enabled":{}}', 'not json', 'x' * 262145]
        for value in malformed:
            with self.subTest(value=value[:50]):
                self.config.write_text(value)
                self.advance(2.01)
                devices = self.devices("devices.rescan")
                self.assertFalse(devices[0]["enabled"])
        self.assertEqual(self.command()["calls"], [])
        self.assertEqual(self.fake.accepted, 0)

    def test_static_update_mode_exact_bytes_native_brightness_and_readback(self):
        self.launch(fragment=True, updates="before")
        device = self.devices()[0]
        self.assertTrue(device["writable"], device)
        result = self.set_color(device, brightness=25)
        self.assertTrue(result["ok"], result)
        expected_mode = mode(flags=16 | 64 | 256, color_mode=2,
                             brightness=30, colors=[0x00563412])
        payload = word(1) + mode_bytes(expected_mode)
        payload = word(len(payload) + 4) + payload
        self.assertEqual(self.writes(), [(0, 1101, payload)])
        self.assertEqual(result["result"], {"device": device["id"], "color": "#123456",
                                          "brightness": 25, "brightness_emulated": False,
                                          "mode": "Static", "speed": None,
                                          "random": False, "saved": False})
        self.assertEqual(self.fake.commands[0], (0, 40, word(6)))
        current = self.client.request("lighting.get", {"device": device["id"]})
        self.assertEqual(current["result"], result["result"])
        self.assertFalse(any(packet in (1050, 1051, 1100, 1102)
                             for _, packet, _ in self.fake.commands))

    def assert_write_preserves_real_inventory(self, operation):
        self.launch(updates="after", device_ids=[42], descriptors=[controller(active=1)])
        before = self.devices("devices.rescan")
        self.assertEqual(len(before), 1)
        device = before[0]
        self.assertTrue(device["writable"], device)
        self.assertTrue(device["id"].startswith("openrgb:"))
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 500})
        self.devices()  # Apply the subscription on the worker before writing.
        self.client.event("devices")
        self.client.events.clear()
        params = {"brightness": 100} if operation == "lighting.set" else {}
        reply = self.client.request(operation, {"device": device["id"], **params})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(self.devices(), before)
        with self.daemon.client() as other:
            self.assertEqual(other.request("devices")["result"]["devices"], before)
        self.assertEqual(self.client.event("devices")["data"]["devices"], before)
        self.advance(0.5)
        self.assertEqual(self.client.event("devices")["data"]["devices"], before)
        self.assertEqual(self.fake.accepted, 1)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])

    def test_rescan_set_preserves_real_inventory_across_connections_and_events(self):
        self.assert_write_preserves_real_inventory("lighting.set")

    def test_rescan_save_preserves_real_inventory_across_connections_and_events(self):
        self.assert_write_preserves_real_inventory("lighting.save")

    def test_real_protocol_6_sequence_keeps_repeated_set_and_save_writable(self):
        self.launch(fragment=True, device_ids=[42], descriptors=[controller(active=1)])
        before = self.devices()
        device = before[0]
        for index, color in enumerate(("#123456", "#abcdef", "#654321")):
            for operation in ("lighting.set", "lighting.save"):
                with self.subTest(index=index, operation=operation):
                    start = len(self.fake.sent)
                    command, reason = (1101, 1) if operation == "lighting.set" else (1102, 2)
                    params = {"color": color, "brightness": 25 + index * 25}
                    reply = self.client.request(operation, {"device": device["id"],
                        **(params if operation == "lighting.set" else {})})
                    self.assertTrue(reply["ok"], reply)
                    self.assertEqual(reply["result"]["device"], device["id"])
                    self.assertEqual(reply["result"]["color"], color)
                    self.assertEqual(reply["result"]["saved"], operation == "lighting.save")
                    ack = packet(42, 10, word(command) + word(0))
                    self.core.wait_until(lambda: len(self.fake.sent) >= start + 6,
                                         message="ACK, descriptor, ACK and SIGNALUPDATE sent")
                    frames = self.fake.sent[start:]
                    write_ack = frames.index(ack)
                    descriptor = self.fake.descriptors[0]
                    # Assert the captured wire format independently of signal_update().
                    notification = word(len(descriptor) + 4) + word(reason) + descriptor[4:]
                    self.assertEqual(frames[write_ack:write_ack + 4], [ack,
                        packet(42, 1, descriptor), packet(42, 10, word(1) + word(0)),
                        packet(42, 1150, notification)])
                    current = self.client.request("lighting.get", {"device": device["id"]})
                    self.assertEqual(current["result"], reply["result"])
                    self.assertEqual(self.devices(), before)
                    if operation == "lighting.save":
                        self.assertEqual(self.fake.saved_modes[42], self.writes()[-1][2])
            self.advance(10)
        self.assertEqual(self.fake.accepted, 1)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])

    def assert_ten_writes_keep_identity(self, device, before_write=None):
        changes = [{"brightness": 50}, {"color": "#123456"},
                   {"mode": "Breathing", "color": "#abcdef", "speed": 50},
                   {"brightness": 25}, {"mode": "Static", "color": "#654321"},
                   {"brightness": 75}, {"color": "#234567"},
                   {"mode": "Breathing", "brightness": 100},
                   {"mode": "Static", "color": "#345678"}, {"brightness": 50}]
        for index, params in enumerate(changes):
            with self.subTest(write=index + 1):
                if before_write:
                    before_write(index)
                reply = self.client.request("lighting.set", {"device": device["id"], **params})
                self.assertTrue(reply["ok"], reply)
                self.assertEqual(reply["result"]["device"], device["id"])
                # Barrier behind the fake's queued full/LED SIGNALUPDATE frames.
                read = self.client.request("lighting.get", {"device": device["id"]})
                self.assertTrue(read["ok"], read)
                current = self.devices()
                self.assertEqual(len(current), 1, current)
                self.assertEqual(current[0]["id"], device["id"])
                self.assertEqual(current[0]["usb"], self.identity)
                self.assertTrue(current[0]["writable"], current)
        self.assertEqual(sum(command == 1101 for _, command, _ in self.writes()), 10)

    def lifecycle_modes(self):
        return [mode("Direct", flags=32), mode(color_mode=2, flags=16 | 64 | 256),
                mode("Breathing", flags=1 | 16 | 32 | 256, speed_max=10)]

    def test_ten_mixed_writes_keep_physical_id_and_write_gate(self):
        self.launch(fragment=True, device_ids=[42],
                    descriptors=[controller(modes=self.lifecycle_modes(), active=1)])
        device = self.devices("devices.rescan")[0]
        expected = "openrgb:" + hashlib.sha256(self.identity.encode()).hexdigest()
        self.assertEqual(device["id"], expected)
        self.assert_ten_writes_keep_identity(device)
        self.assertEqual(self.fake.accepted, 1)

    def test_third_write_after_hidraw_renumbering_keeps_cached_usb_resolution(self):
        self.launch(device_ids=[42],
                    descriptors=[controller(modes=self.lifecycle_modes(), active=1)])
        device = self.devices("devices.rescan")[0]

        def renumber(index):
            if index == 2:
                # Real MSI failure: OpenRGB retains the old HID path after sysfs
                # exposes the same physical USB device under a different number.
                (self.usb.root / "class/hidraw/hidraw9").rename(
                    self.usb.root / "class/hidraw/hidraw12")

        self.assert_ten_writes_keep_identity(device, renumber)
        self.assertEqual(self.fake.accepted, 1)

    def test_empty_location_in_signal_update_and_req_data_preserves_usb(self):
        self.launch(device_ids=[42],
                    descriptors=[controller(modes=self.lifecycle_modes(), active=1)])
        device = self.devices("devices.rescan")[0]
        empty = controller_metadata(self.fake.descriptors[0], location="")
        self.fake.send(signal_update(42, 1, empty))
        self.assertTrue(self.client.request("lighting.get", {"device": device["id"]})["ok"])
        self.assertEqual(self.devices()[0], device)

        def omit_location(index):
            if index == 2:
                # All later REQ_DATA and full SIGNALUPDATE descriptors omit it.
                self.fake.descriptors[0] = controller_metadata(
                    self.fake.descriptors[0], location="")

        self.assert_ten_writes_keep_identity(device, omit_location)
        self.advance(2.01)
        self.assertEqual(self.devices("devices.rescan")[0], device)

    def test_signal_update_with_new_hidraw_location_resolves_the_same_physical_usb(self):
        self.launch(device_ids=[42], descriptors=[controller(active=1)])
        device = self.devices("devices.rescan")[0]
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 10000})
        self.devices()  # Subscription barrier on the worker.
        self.client.event("devices")
        self.client.events.clear()
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake.descriptors[0] = controller_metadata(self.fake.descriptors[0],
                                                      location="HID: /dev/hidraw12")
        commands = len(self.fake.commands)
        self.fake.send(signal_update(42, 1, self.fake.descriptors[0]))
        # Observe the notification itself, before any REQ_DATA can refresh sysfs.
        updated = self.client.event("devices")["data"]["devices"]
        self.assertEqual(updated, [device])
        self.assertEqual(len(self.fake.commands), commands)
        self.assertTrue(self.set_color(device)["ok"])
        self.assertTrue(self.devices()[0]["writable"])

    def test_physical_id_survives_rgbcd_and_fake_restarts_and_metadata_changes(self):
        self.launch(device_ids=[42], descriptors=[controller(active=1)])
        device = self.devices("devices.rescan")[0]
        self.assertTrue(self.set_color(device)["ok"])
        self.client.close()
        self.daemon.close()
        self.start_daemon("core-restarted")
        restarted = self.devices("devices.rescan")[0]
        self.assertEqual(restarted["id"], device["id"])
        self.assertEqual(restarted["usb"], self.identity)
        self.assertTrue(restarted["writable"], restarted)
        self.assertTrue(self.set_color(device, "#abcdef")["ok"])

        # Preserve the listener's port while restarting the server and its IDs.
        listener = self.fake.listener.dup()
        self.addCleanup(listener.close)
        self.fake.close()
        self.core.wait_until(lambda: self.client.request("status")["result"]["engines"][0][
            "state"] == "unreachable", message="fake OpenRGB stopped")
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake = OpenRgbServer(listener=listener, device_ids=[99], descriptors=[controller(
            name="New SDK label", vendor="New vendor label", serial="SDK serial changed",
            description="New description", firmware="2.0", location="HID: /dev/hidraw12",
            active=1, led_colors=[0x112233, 0x445566])])
        self.addCleanup(self.fake.close)
        self.assertTrue(self.set_color(device)["ok"])
        current = self.devices()[0]
        self.assertEqual(current["id"], device["id"])
        self.assertEqual(current["usb"], self.identity)
        self.assertTrue(current["writable"], current)
        self.client.close()
        self.daemon.close()
        self.start_daemon("core-restarted-again")
        self.assertEqual(self.devices("devices.rescan")[0]["id"], device["id"])
        self.assertTrue(self.set_color(device)["ok"])

    def test_non_usb_fallback_uses_only_immutable_metadata(self):
        self.launch(descriptors=[controller(location="I2C: immutable", active=1)])
        before = self.devices("devices.rescan")
        device = next(item for item in before if item["id"].startswith("openrgb:"))
        encoded = json.dumps(["MSI RGB", "MSI", "unique", "I2C: immutable"],
                             separators=(",", ":")).encode()
        self.assertEqual(device["id"], "openrgb:" + hashlib.sha256(encoded).hexdigest())
        self.fake.descriptors = [controller(location="I2C: immutable", description="Changed",
            firmware="2.0", active=0, led_colors=[0xabcdef, 0xabcdef])]
        self.fake.send(signal_update(0, 1, self.fake.descriptors[0]))
        self.assertTrue(self.client.request("lighting.get", {"device": device["id"]})["ok"])
        self.advance(2.01)
        after = next(item for item in self.devices("devices.rescan")
                     if item["id"].startswith("openrgb:"))
        self.assertEqual(after["id"], device["id"])
        self.assertEqual(after["usb"], "")
        self.assertFalse(after["writable"])

    def test_cached_usb_binding_does_not_allow_a_reused_hidraw_or_unplugged_device(self):
        self.launch(descriptors=[controller(active=1)])
        device = self.devices("devices.rescan")[0]
        node = self.usb.root / "class/hidraw/hidraw9"
        moved = node.with_name("hidraw12")
        node.rename(moved)
        self.usb.add(13, "1234", "abcd", "replacement")
        (node.parent / "hidraw13").rename(node)
        # The SDK still refers to hidraw9. Never transfer its resolved binding
        # or write permission to the unrelated USB device now at that path.
        reply = self.set_color(device)
        self.assertFalse(reply["ok"], reply)
        self.assertIn("USB identity changed", reply["error"]["message"])
        cached = self.devices()[0]
        self.assertEqual(cached["id"], device["id"])
        self.assertEqual(cached["usb"], self.identity)
        self.assertFalse(cached["writable"])
        node.rename(node.with_name("hidraw13"))
        moved.rename(node)
        self.assertTrue(self.client.request("lighting.get", {"device": device["id"]})["ok"])
        self.assertTrue(self.set_color(device)["ok"])
        node.rename(self.root / "unplugged-hidraw")
        reply = self.set_color(device)
        self.assertFalse(reply["ok"], reply)
        self.assertIn("USB device is not present", reply["error"]["message"])
        cached = self.devices()[0]
        self.assertEqual(cached["id"], device["id"])
        self.assertEqual(cached["usb"], self.identity)
        self.assertFalse(cached["writable"])

    def test_signal_update_refreshes_inventory_without_a_descriptor_request(self):
        self.launch(device_ids=[42], descriptors=[controller(active=1)])
        before = self.devices()[0]
        commands = len(self.fake.commands)
        modes = [mode("Static", color_mode=2), mode("New effect", flags=16 | 32 | 256)]
        self.fake.descriptors = [controller(modes=modes)]
        descriptor = self.fake.descriptors[0]
        self.fake.send(packet(42, 1150,
            word(len(descriptor) + 4) + word(0xffffffff) + descriptor[4:]))
        current = self.core.wait_until(lambda: next((device for device in self.devices()
            if any(value["name"] == "New effect" for value in device["modes"])), None),
            message="SIGNALUPDATE updates inventory without polling OpenRGB")
        self.assertEqual(len(self.fake.commands), commands)
        for key in ("id", "usb", "writable", "enabled"):
            self.assertEqual(current[key], before[key])
        self.assertTrue(self.set_color(current)["ok"])
        self.assertTrue(self.save(current)["result"]["saved"])
        self.assertEqual(self.devices()[0]["id"], before["id"])
        self.assertEqual(self.fake.accepted, 1)

    def test_server_strings_and_unrelated_or_malformed_acks_never_invalidate_inventory(self):
        self.launch(device_ids=[42], descriptors=[controller(active=1)])
        before = self.devices()
        for command, payload in ((51, b"OpenRGB 1.1\0"), (51, b""),
                (51, b"unterminated\xff"), (10, b""), (10, b"x" * 7),
                (10, b"x" * 9), (10, word(1101) + word(3)),
                (10, word(1) + word(0)), (10, word(999) + word(0))):
            self.fake.send(packet(42, command, payload))
        # The readback is a barrier behind all injected packets on the SDK socket.
        self.assertTrue(self.client.request("lighting.get", {"device": before[0]["id"]})["ok"])
        self.assertEqual(self.devices(), before)
        self.assertTrue(self.set_color(before[0])["ok"])
        self.assertEqual(self.fake.accepted, 1)

    def test_new_connection_reuses_completed_openrgb_inventory(self):
        self.launch()
        before = self.devices("devices.rescan")
        self.assertTrue(before[0]["writable"], before)
        self.client.close()
        with self.daemon.client() as other:
            self.assertEqual(other.request("devices")["result"]["devices"], before)
        self.assertEqual(self.fake.accepted, 1)

    def test_transport_failure_keeps_identity_and_next_write_reconnects(self):
        self.launch(device_ids=[42])
        before = self.devices("devices.rescan")
        device = before[0]
        self.fake.send(packet(42, 1150, word(8)))  # Missing update reason.
        self.core.wait_until(lambda: self.client.request("status")["result"]["engines"][0][
            "state"] == "unreachable", message="invalid notification rejected")
        cached = self.devices()
        self.assertEqual([item["id"] for item in cached], [device["id"]])
        self.assertFalse(cached[0]["writable"])
        with self.daemon.client() as other:
            self.assertEqual(other.request("devices")["result"]["devices"], cached)
        self.fake.respond.clear()
        self.addCleanup(self.fake.respond.set)
        self.client.send({"v": 1, "id": 77, "op": "lighting.set",
                          "params": {"device": device["id"], "brightness": 100}})
        self.core.wait_until(lambda: self.fake.accepted == 2, message="SDK reconnect")
        self.client.request("subscribe", {"topics": ["devices"]})
        self.assertEqual(self.client.event("devices")["data"]["devices"], cached)
        self.fake.respond.set()
        result = self.read_response(self.client, 77)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"]["device"], device["id"])
        self.assertEqual(self.devices(), before)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])

    def test_failed_reconnect_keeps_identity_without_retrying_in_a_loop(self):
        self.launch()
        device = self.devices("devices.rescan")[0]
        self.fake.behavior = "magic"
        self.advance(2.01)
        cached = self.devices("devices.rescan")
        self.assertEqual([item["id"] for item in cached], [device["id"]])
        self.assertFalse(cached[0]["writable"])
        result = self.set_color(device)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "unavailable")
        self.assertEqual(self.fake.accepted, 3)
        self.assertEqual(self.devices(), cached)
        self.assertEqual(self.writes(), [])

    def test_signal_updates_are_validated_and_never_introduce_a_controller(self):
        self.launch(device_ids=[42])
        before = self.devices()
        # A notification alone cannot turn an unenumerated descriptor into a device.
        self.fake.send(signal_update(99, 1, controller(name="Unenumerated")))
        self.assertEqual(self.devices(), before)
        malformed = [word(8), word(10) + word(0) + b"\0\0extra",
                     word(10) + word(0) + b"\xff\xff",
                     word(9) + word(1) + b"x",
                     signal_update(42, 1, controller(name="Changed identity"))[16:]]
        for payload in malformed:
            with self.subTest(payload=payload[:16]):
                self.fake.send(packet(42, 1150, payload))
                self.core.wait_until(lambda: self.client.request("status")["result"][
                    "engines"][0]["state"] == "unreachable",
                    message="malformed SIGNALUPDATE rejected")
                self.assertEqual(self.devices()[0]["id"], before[0]["id"])
                self.assertFalse(self.devices()[0]["writable"])
                self.advance(2.01)
                self.assertEqual(self.devices("devices.rescan"), before)

    def test_mode_specific_color_and_emulated_brightness(self):
        static = mode(flags=64 | 256, color_mode=2, minimum=0, maximum=0,
                      brightness=0,
                      colors_min=2, colors_max=2, colors=[0x332211, 0x332211])
        self.launch(descriptors=[controller(modes=[mode("Direct", flags=32), static])])
        device = self.devices()[0]
        reply = self.set_color(device, "#804020", 50)
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["result"]["brightness_emulated"])
        self.assertEqual(reply["result"]["color"], "#402010")
        static["colors"] = [0x102040, 0x102040]
        body = word(1) + mode_bytes(static)
        self.assertEqual(self.writes(), [(0, 1101, word(len(body) + 4) + body)])

    def test_current_mode_and_color_are_read_from_controller_on_get(self):
        self.launch()
        device = self.devices()[0]
        changed = mode(brightness=90, color_mode=2, colors=[0x00ccbbaa])
        self.fake.descriptors = [controller(modes=[changed], active=0)]
        reply = self.client.request("lighting.get", {"device": device["id"]})
        self.assertTrue(reply["ok"], reply)
        self.assertEqual(reply["result"]["color"], "#aabbcc")
        self.assertEqual(reply["result"]["brightness"], 100)
        self.assertEqual(self.writes(), [])

    def test_write_gates_unknown_identity_duplicate_identity_and_static_flags(self):
        cases = [
            controller(location="USB:1462:7d98:unique"),
            controller(modes=[mode("Direct", flags=32)]),
            controller(modes=[mode("static", flags=32)]),
            controller(modes=[mode(flags=0)]),
            controller(modes=[mode(flags=64, colors_min=0, colors_max=0)]),
        ]
        self.launch(descriptors=cases)
        for device in self.devices():
            self.assertFalse(device["writable"], device)
            self.assertEqual(self.set_color(device)["error"]["code"], "blocked")
        self.assertEqual(self.writes(), [])

    def test_two_controllers_for_one_usb_and_two_hidraw_for_identity_block(self):
        self.launch(descriptors=[controller(), controller(name="Duplicate controller")])
        for device in self.devices():
            self.assertFalse(device["writable"])
            self.assertIn("unique", device["blocked_reason"])
        self.fake.descriptors = [controller()]
        self.usb.add(12)
        self.advance(2.01)
        for device in self.devices("devices.rescan"):
            self.assertFalse(device["writable"])
        self.assertEqual(self.writes(), [])

    def test_duplicate_controller_gate_survives_notifications_and_clears_only_on_rescan(self):
        self.launch(device_ids=[42, 99], descriptors=[controller(active=1),
                    controller(name="Duplicate controller", active=1)])
        device = self.devices("devices.rescan")[0]
        self.assertIn("not unique", device["blocked_reason"])
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake.descriptors[0] = controller_metadata(self.fake.descriptors[0],
                                                      location="HID: /dev/hidraw12")
        self.fake.send(signal_update(42, 1, self.fake.descriptors[0]))
        self.assertTrue(self.client.request("lighting.get", {"device": device["id"]})["ok"])
        self.assertIn("not unique", self.devices()[0]["blocked_reason"])
        self.assertFalse(self.set_color(device)["ok"])
        self.assertEqual(self.writes(), [])
        self.fake.descriptors = self.fake.descriptors[:1]
        self.fake.device_ids = [42]
        self.advance(2.01)
        self.assertTrue(self.devices("devices.rescan")[0]["writable"])
        self.assertTrue(self.set_color(device)["ok"])

    def test_trofeo_never_candidate_even_enabled_and_descriptor_never_writable(self):
        self.launch(descriptors=[controller(),
                                 controller(name="Other", location="HID: /dev/hidraw10")])
        self.config.write_text(json.dumps({"v": 1, "enabled": {
            self.identity: True, "usb:0416:5302:trofeo": True}}))
        devices = self.devices()
        trofeo = next(device for device in devices if device["excluded"])
        self.assertFalse(trofeo["writable"])
        self.assertEqual(trofeo["capabilities"], [])
        self.assertIn("omarchy-trcc", trofeo["blocked_reason"])
        self.assertEqual(self.set_color(trofeo)["error"]["code"], "blocked")
        self.config.write_text('{"v":1,"enabled":{"usb:0416:5302:trofeo":true}}')
        self.advance(2.01)
        self.assertFalse(any(device["excluded"] for device in self.devices("devices.rescan")))
        self.assertEqual(self.writes(), [])

    def test_start_failure_and_failed_job_do_not_contact_sdk_or_write(self):
        self.command(result="failed")
        self.launch()
        self.assertFalse(self.devices()[0]["writable"])
        self.assertEqual(self.fake.accepted, 0)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.advance(10)
        self.devices()
        self.assertEqual(len(self.command()["calls"]), 1)

    def test_start_is_async_concurrent_requests_join_and_api_remains_responsive(self):
        self.command(hold=True)
        self.launch()
        self.client.send({"v": 1, "id": 77, "op": "devices"})
        self.core.wait_until(lambda: self.command()["held"], message="StartUnit held")
        with self.daemon.client() as other:
            self.assertTrue(other.request("hello")["ok"])
            other.send({"v": 1, "id": 78, "op": "devices.rescan"})
            self.command(action="release", hold=False)
            self.assertTrue(self.client.read()["ok"])
            self.assertTrue(other.read()["ok"])
        self.assertEqual(len(self.command()["calls"]), 1)
        self.assertEqual(self.fake.accepted, 1)

    def connection_attempts(self):
        path = self.root / "sdk-connects"
        data = path.read_bytes() if path.exists() else b""
        return [stamp for (stamp,) in struct.iter_unpack("q", data)]

    def connection_rounds(self):
        # Qt can issue multiple native connect calls in one SDK connection attempt.
        return list(dict.fromkeys(self.connection_attempts()))

    def wait_for_attempts(self, count):
        self.core.wait_until(lambda: len(self.connection_rounds()) == count,
                             message=f"SDK connection attempt {count}")
        # Let the API and worker process connection errors at this clock value.
        self.assertTrue(self.client.request("hello")["ok"])

    def read_response(self, client, expected):
        while True:
            reply = client.read()
            if "event" in reply:
                client.events.append(reply)
            else:
                self.assertEqual(reply["id"], expected)
                return reply

    def test_startup_wait_joins_requests_and_publishes_writable_device_after_1500_ms(self):
        self.environment["CORE_TEST_OPENRGB_CONNECTS"] = str(self.root / "sdk-connects")
        self.launch(enabled=False, defer_listen=True)
        self.assertFalse(self.devices()[0]["writable"])
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 10000})
        self.enable()
        self.advance(2.01)
        self.client.send({"v": 1, "id": 77, "op": "devices.rescan"})
        self.wait_for_attempts(1)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])
        device_id = "openrgb:" + hashlib.sha256(self.identity.encode()).hexdigest()
        with self.daemon.client() as other:
            for number, operation, params in (
                    (78, "devices", {}), (79, "devices.rescan", {}),
                    (80, "lighting.get", {"device": device_id}),
                    (81, "lighting.set", {"device": device_id, "color": "#123456",
                                          "brightness": 50})):
                other.send({"v": 1, "id": number, "op": operation, "params": params})
            self.assertTrue(other.request("hello")["ok"])
            self.assertEqual(other.stashed, [], "Startup requests must remain pending")
            for attempt in range(2, 7):
                self.advance(0.25)
                self.wait_for_attempts(attempt)
                self.assertEqual(self.client.stashed, [], "No premature candidate reply")
                self.assertEqual(self.fake.accepted, 0)
            # StartUnit completed at t=0; OpenRGB opens its SDK listener at t=1.5 s.
            self.daemon.clock.advance(0.25)
            self.fake.start_listening()
            self.client.request("hello")
            result = self.read_response(self.client, 77)
            self.assertTrue(result["ok"], result)
            device = result["result"]["devices"][0]
            self.assertTrue(device["writable"], device)
            self.assertEqual(device["id"], device_id)
            for number in (78, 79):
                joined = self.read_response(other, number)
                self.assertEqual(joined["result"]["devices"], [device])
            self.assertTrue(self.read_response(other, 80)["ok"])
            written = self.read_response(other, 81)
            self.assertTrue(written["ok"], written)
            self.assertEqual(written["result"]["color"], "#123456")
        data = self.core.wait_event(self.client, "devices", lambda data: any(
            item["writable"] for item in data["devices"]), message="startup devices event")
        self.assertEqual(data["devices"][0]["id"], device_id)
        attempts = self.connection_rounds()
        self.assertEqual([stamp - attempts[0] for stamp in attempts],
                         [index * 250_000_000 for index in range(7)])
        native_attempts = self.connection_attempts()
        self.advance(10)
        self.assertEqual(self.client.request("status")["result"]["engines"][0]["state"],
                         "ready", "Successful connection must cancel the startup deadline")
        self.assertEqual(self.connection_attempts(), native_attempts)

    def test_startup_wait_expires_at_10_seconds_without_background_retries(self):
        self.environment["CORE_TEST_OPENRGB_CONNECTS"] = str(self.root / "sdk-connects")
        self.launch(defer_listen=True)
        self.client.send({"v": 1, "id": 77, "op": "devices.rescan"})
        self.wait_for_attempts(1)
        for attempt in range(2, 41):
            self.advance(0.25)
            self.wait_for_attempts(attempt)
        self.advance(0.249)
        self.assertEqual(self.client.stashed, [], "No failure before the 10 s deadline")
        self.advance(0.001)
        result = self.read_response(self.client, 77)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["devices"][0]["writable"])
        engine = self.client.request("status")["result"]["engines"][0]
        self.assertEqual(engine["state"], "unreachable")
        self.assertIn("10 s after StartUnit", engine["reason"])
        attempts = self.connection_rounds()
        self.assertEqual([stamp - attempts[0] for stamp in attempts],
                         [index * 250_000_000 for index in range(40)])
        native_attempts = self.connection_attempts()
        self.advance(30)
        self.assertFalse(self.devices()[0]["writable"])
        self.assertEqual(self.connection_attempts(), native_attempts)
        # A rescan of the already running unit gets one attempt, no new startup window.
        self.assertFalse(self.devices("devices.rescan")[0]["writable"])
        self.assertEqual(len(self.connection_rounds()), 41)
        native_attempts = self.connection_attempts()
        self.advance(10)
        self.assertEqual(self.connection_attempts(), native_attempts)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])

    def test_sensors_subscriber_does_not_prevent_idle_stop_at_120_seconds(self):
        self.launch()
        self.devices()
        self.client.request("subscribe", {"topics": ["sensors"], "interval_ms": 10000})
        self.devices()  # Worker barrier before advancing the controlled clock.
        self.advance(119.9)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.advance(0.1)
        calls = self.core.wait_until(lambda: self.command()["calls"]
                                    if len(self.command()["calls"]) == 2 else None,
                                    message="StopUnit despite sensors subscriber at 120 s")
        self.assertEqual(calls[-1], ["StopUnit", "omarchy-rgb-cooling-openrgb.service",
                                    "replace"])

    def test_stop_after_exact_120_seconds_and_lighting_activity_extends_deadline(self):
        self.launch()
        device = self.devices()[0]
        self.advance(119.9)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.assertTrue(self.set_color(device)["ok"])
        self.assertTrue(self.client.request("lighting.save", {"device": device["id"]})["ok"])
        self.advance(119.9)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.advance(0.11)
        calls = self.core.wait_until(lambda: self.command()["calls"]
                                    if len(self.command()["calls"]) == 2 else None,
                                    message="StopUnit at 120 seconds")
        self.assertEqual(calls[-1], ["StopUnit", "omarchy-rgb-cooling-openrgb.service", "replace"])
        self.assertTrue(self.set_color(device)["ok"])
        self.assertEqual(self.command()["calls"][-1][0], "StartUnit")

    def test_subscribers_prevent_idle_stop_until_last_unsubscribe(self):
        self.launch()
        self.devices()
        self.client.request("subscribe", {"topics": ["devices"], "interval_ms": 10000})
        self.devices()  # Worker barrier: subscription is applied before advancing its clock.
        self.advance(121)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.client.request("unsubscribe")
        self.devices()  # Worker barrier for the unsubscribe deadline.
        self.advance(119.9)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.advance(0.11)
        self.core.wait_until(lambda: len(self.command()["calls"]) == 2,
                             message="StopUnit after subscribers leave")

    def test_no_interest_no_start_scan_cache_rescan_rate_limit_no_polling(self):
        self.launch()
        self.client.request("hello")
        self.client.request("status")
        self.advance(10)
        self.assertEqual(self.command()["calls"], [])
        before = self.devices()
        self.assertEqual(self.devices(), before)
        self.assertEqual(self.fake.accepted, 1)
        self.assertEqual(self.client.request("devices.rescan")["error"]["code"], "rate_limited")
        self.advance(2.01)
        self.devices("devices.rescan")
        self.assertEqual(self.fake.accepted, 2)
        self.assertEqual(len(self.command()["calls"]), 1)

    def test_bad_packets_and_all_truncated_descriptors_fail_closed(self):
        self.launch(descriptors=[controller()[:-1]])
        self.assertFalse(self.devices()[0]["writable"])
        for descriptor in (controller() + b"extra", b"\\xff" * 50,
                           controller()[:8] + b"\\xff\\xff" + controller()[10:]):
            self.fake.descriptors = [descriptor]
            self.advance(2.01)
            self.assertFalse(self.devices("devices.rescan")[0]["writable"])
        for behavior in ("huge", "magic", "huge_count", "wrong_id", "wrong_command"):
            self.fake.behavior = behavior
            self.advance(2.01)
            self.assertFalse(self.devices("devices.rescan")[0]["writable"])
        self.assertEqual(self.writes(), [])

    def test_sdk_timeout_async_and_failure_cached_without_retries(self):
        self.launch(behavior="timeout", clock=False)
        self.client.send({"v": 1, "id": 77, "op": "devices"})
        self.core.wait_until(lambda: self.fake.commands, message="SDK request pending")
        with self.daemon.client() as other:
            self.assertTrue(other.request("hello")["ok"])
        self.assertTrue(self.client.read()["ok"])
        self.assertFalse(self.devices()[0]["writable"])
        self.assertEqual(self.fake.accepted, 1)
        self.assertEqual(self.writes(), [])

    def test_hotplug_scans_only_while_a_device_subscriber_exists(self):
        fifo = self.root / "udev.fifo"
        ack = self.root / "ack.fifo"
        os.mkfifo(fifo)
        os.mkfifo(ack)
        descriptor = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        acknowledge = os.open(ack, os.O_RDWR | os.O_NONBLOCK)
        self.addCleanup(os.close, descriptor)
        self.addCleanup(os.close, acknowledge)
        self.environment.update(CORE_TEST_UDEV_FIFO=str(fifo), CORE_TEST_UDEV_ACK_FIFO=str(ack))
        self.launch(enabled=False)

        def hotplug():
            os.write(descriptor, b"+")

            def consumed():
                try:
                    return os.read(acknowledge, 1) == b"+"
                except BlockingIOError:
                    return False
            self.core.wait_until(consumed, message="udev callback consumed")
            self.client.request("hello")

        hotplug()
        self.assertEqual(self.fake.accepted, 0)
        self.client.request("subscribe", {"topics": ["devices"]})
        self.enable()
        hotplug()
        self.core.wait_until(lambda: self.fake.accepted == 1, message="subscribed hotplug scan")
        self.devices()
        self.client.request("unsubscribe")
        hotplug()
        self.assertEqual(self.fake.accepted, 1)

    def test_legacy_sdk_is_read_only_and_never_sends_update_mode(self):
        self.launch(advertised=1, descriptors=[controller(version=1)])
        device = self.devices()[0]
        self.assertFalse(device["writable"])
        self.assertIn("protocol 3 or later", device["blocked_reason"])
        self.assertTrue(self.client.request("lighting.get", {"device": device["id"]})["ok"])
        self.assertEqual(self.set_color(device)["error"]["code"], "blocked")
        self.assertEqual(self.writes(), [])

    def test_missing_mode_color_count_and_truncated_update_inputs_never_write(self):
        self.launch(descriptors=[controller(with_lighting=False, modes=[mode()])])
        device = self.devices()[0]
        self.assertFalse(device["writable"])
        self.assertEqual(self.set_color(device)["error"]["code"], "blocked")
        for params in ({"device": device["id"], "color": "#123456", "brightness": 101},
                       {"device": device["id"], "color": "#12345", "brightness": 50}):
            self.assertEqual(self.client.request("lighting.set", params)["error"]["code"],
                             "bad_request")
        self.assertEqual(self.writes(), [])

    def test_disconnected_bus_never_claims_ownership_or_touches_sdk(self):
        self.environment["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/nonexistent/rgbc-unit-bus"
        self.launch()
        device = self.devices()[0]
        self.assertFalse(device["writable"])
        self.assertEqual(self.fake.commands, [])
        self.assertEqual(self.command()["calls"], [])

    def test_changed_opt_in_restarts_unit_with_new_device_allowlist(self):
        self.launch()
        self.devices()
        second = self.usb.add(12, "1234", "abcd", "other")
        self.rules.write_text(self.rules.read_text() + rule("1234", "abcd", "Other"))
        self.fake.descriptors.append(controller(name="Other", location="HID: /dev/hidraw12"))
        self.config.write_text(json.dumps({"v": 1, "enabled": {
            self.identity: True, second: True}}))
        self.advance(2.01)
        devices = self.devices("devices.rescan")
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(device["writable"] for device in devices))
        self.assertEqual([call[0] for call in self.command()["calls"]],
                         ["StartUnit", "StopUnit", "StartUnit"])

    def test_stable_identity_follows_usb_across_hidraw_renumbering(self):
        self.launch()
        before = self.devices()[0]
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake.descriptors = [controller(location="HID: /dev/hidraw12")]
        self.advance(2.01)
        after = self.devices("devices.rescan")[0]
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["usb"], before["usb"])
        self.assertTrue(after["enabled"])
        self.assertTrue(after["writable"])
        self.assertEqual([call[0] for call in self.command()["calls"]],
                         ["StartUnit", "StopUnit", "StartUnit"])

    def test_failed_idle_stop_releases_queued_operations_without_retry(self):
        self.launch()
        device = self.devices()[0]
        self.command(hold=True, reject=True)
        self.advance(120.01)
        self.core.wait_until(lambda: self.command()["held"], message="StopUnit held")
        self.client.send({"v": 1, "id": 77, "op": "lighting.get",
                          "params": {"device": device["id"]}})
        with self.daemon.client() as other:
            self.assertTrue(other.request("hello")["ok"])
        self.command(action="release", hold=False)
        reply = self.client.read()
        self.assertEqual(reply["id"], 77)
        self.assertTrue(reply["ok"], reply)
        self.assertEqual([call[0] for call in self.command()["calls"]],
                         ["StartUnit", "StopUnit"])

    def test_protocol_6_nonconsecutive_controller_ids_and_empty_descriptor_request(self):
        self.launch(device_ids=[42])
        device = self.devices()[0]
        self.assertTrue(self.set_color(device)["ok"])
        self.assertEqual(self.writes()[0][0:2], (42, 1101))
        descriptors = [(device, payload) for device, command, payload in self.fake.commands
                       if command == 1]
        self.assertTrue(descriptors)
        self.assertTrue(all(device == 42 and payload == b"" for device, payload in descriptors))

    def test_protocol_6_rejected_write_ack_is_not_reported_as_success(self):
        self.launch(behavior="write_rejected")
        device = self.devices()[0]
        self.assertFalse(self.set_color(device)["ok"])
        self.assertEqual([command for _, command, _ in self.writes()], [1101])
        self.assertTrue(self.devices()[0]["writable"])
        self.fake.behavior = "normal"
        self.assertTrue(self.set_color(device)["ok"])
        self.assertEqual(self.fake.accepted, 1)

    def test_protocol_6_malformed_write_ack_is_rejected(self):
        self.launch(behavior="bad_write_ack")
        device = self.devices()[0]
        self.assertFalse(self.set_color(device)["ok"])
        self.assertEqual([command for _, command, _ in self.writes()], [1101])
        self.assertTrue(self.devices()[0]["writable"])
        self.fake.behavior = "normal"
        self.assertTrue(self.set_color(device)["ok"])
        self.assertEqual(self.fake.accepted, 1)

    def test_per_led_static_exact_bytes_uniform_buffer_native_brightness_and_readback(self):
        modes = [mode("Direct", flags=32), mode()]
        self.launch(fragment=True, device_ids=[42], descriptors=[controller(modes=modes)])
        device = self.devices()[0]
        # A fresh read must replace the cached count; old LED colours may differ.
        self.fake.descriptors = [controller(modes=modes, led_colors=[1, 2, 3])]
        before = len(self.fake.commands)
        result = self.set_color(device, brightness=25)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], {"device": device["id"], "color": "#123456",
                                          "brightness": 25, "brightness_emulated": False,
                                          "mode": "Static", "speed": None,
                                          "random": False, "saved": False})
        expected = mode(brightness=30, colors=[])
        body = word(1) + mode_bytes(expected)
        leds = struct.pack("<IH3I", 18, 3, 0x563412, 0x563412, 0x563412)
        self.assertEqual(self.writes(), [(42, 1101, word(len(body) + 4) + body),
                                         (42, 1050, leds)])
        self.assertEqual([command for _, command, _ in self.fake.commands[before:]],
                         [1, 1101, 1050, 1])
        self.assertEqual(set(struct.unpack_from("<3I", self.writes()[1][2], 6)), {0x563412})
        current = self.client.request("lighting.get", {"device": device["id"]})["result"]
        self.assertEqual(current, result["result"])

    def test_per_led_emulated_brightness_and_validated_led_count_boundaries(self):
        static = mode(flags=32, minimum=0, maximum=0, brightness=0, colors=[])
        self.launch(descriptors=[controller(modes=[static])])
        device = self.devices()[0]
        for count, brightness, packed in ((1, 0, 0), (4, 50, 0x102040), (4096, 100, 0x204080)):
            with self.subTest(count=count, brightness=brightness):
                self.fake.descriptors = [controller(modes=[static], led_colors=[1] * count)]
                before = len(self.writes())
                result = self.set_color(device, "#804020", brightness)
                self.assertTrue(result["ok"], result)
                self.assertTrue(result["result"]["brightness_emulated"])
                expected_color = {0: "#000000", 50: "#402010", 100: "#804020"}[brightness]
                self.assertEqual(result["result"]["color"], expected_color)
                body = word(0) + mode_bytes(static)
                expected_leds = struct.pack("<IH", 6 + 4 * count, count) + word(packed) * count
                self.assertEqual(self.writes()[before:], [
                    (0, 1101, word(len(body) + 4) + body), (0, 1050, expected_leds)])
                values = struct.unpack_from(f"<{count}I", self.writes()[-1][2], 6)
                self.assertEqual(len(values), count)
                self.assertEqual(set(values), {packed})

    def test_per_led_invalid_counts_mismatches_and_truncation_never_write(self):
        valid = controller(modes=[mode()])
        marker = struct.pack("<H", 1) + string("LED") + struct.pack("<HI", 1, 0x332211)
        self.assertEqual(valid.count(marker), 1)
        offset = valid.index(marker)
        malformed = [controller(modes=[mode()], led_colors=[]),
                     controller(modes=[mode()], led_colors=[1] * 4097),
                     valid[:offset] + b"\xff\xff" + valid[offset + 2:],
                     valid.replace(marker, marker[:-6] + struct.pack("<HI", 2, 0x332211)),
                     valid[:-1]]
        self.launch(descriptors=[valid])
        for descriptor in malformed:
            with self.subTest(size=len(descriptor)):
                self.fake.descriptors = [valid]
                self.advance(2.01)
                device = self.devices("devices.rescan")[0]
                self.assertTrue(device["writable"])
                self.fake.descriptors = [descriptor]
                self.assertFalse(self.set_color(device)["ok"])
                self.assertEqual(self.writes(), [])

    def test_per_led_rejected_malformed_and_missing_ack_never_succeed(self):
        self.launch(descriptors=[controller(modes=[mode()])])
        for behavior in ("led_write_rejected", "bad_led_ack", "missing_led_ack"):
            with self.subTest(behavior=behavior):
                self.fake.behavior = behavior
                self.advance(2.01)
                device = self.devices("devices.rescan")[0]
                result = self.set_color(device)
                self.assertFalse(result["ok"], result)
                self.assertEqual(result["error"]["code"], "unavailable")

    def test_successful_ack_without_applying_static_is_rejected_on_readback(self):
        self.launch(behavior="write_ignored")
        device = self.devices()[0]
        reply = self.set_color(device)
        self.assertFalse(reply["ok"], reply)
        self.assertEqual(reply["error"]["code"], "unsupported")

    def test_per_led_successful_ack_without_updating_leds_is_rejected_on_readback(self):
        self.launch(behavior="led_write_ignored", descriptors=[controller(modes=[mode()])])
        device = self.devices()[0]
        reply = self.set_color(device)
        self.assertFalse(reply["ok"], reply)
        self.assertEqual(reply["error"]["code"], "unsupported")
        self.assertEqual([command for _, command, _ in self.writes()], [1101, 1050])

    def test_native_brightness_must_match_readback_even_if_static_color_matches(self):
        self.launch(behavior="brightness_ignored")
        device = self.devices()[0]
        reply = self.set_color(device)
        self.assertFalse(reply["ok"], reply)
        self.assertEqual(reply["error"]["code"], "unsupported")
        current = self.client.request("lighting.get", {"device": device["id"]})["result"]
        self.assertEqual(current["color"], "#123456")
        self.assertNotEqual(current["brightness"], 50)

    def effect(self, device, **params):
        return self.client.request("lighting.set", {"device": device["id"], **params})

    def save(self, device):
        return self.client.request("lighting.save", {"device": device["id"]})

    def launch_msi(self, version=4, modes=None):
        from fakes.openrgb import msi_modes
        modes = msi_modes() if modes is None else modes
        self.launch(advertised=version, descriptors=[controller(
            version=version, modes=modes, active=1, led_colors=[0x332211] * 3)])
        return self.devices()[0], modes

    def test_msi_modes_come_from_real_descriptors_in_order_without_direct(self):
        device, modes = self.launch_msi()
        self.assertTrue(device["writable"], device)
        self.assertEqual([item["name"] for item in device["modes"]],
                         [item["name"] for item in modes[1:]])
        for descriptor, actual in zip(modes[1:], device["modes"]):
            flags = descriptor["flags"]
            self.assertEqual(actual, {
                "name": descriptor["name"], "speed": bool(flags & 1),
                "brightness": bool(flags & 16),
                "color": "single" if flags & (32 | 64) else "none",
                "random": bool(flags & 128), "savable": bool(flags & (256 | 512))})
        current = self.client.request("lighting.get", {"device": device["id"]})["result"]
        self.assertEqual((current["mode"], current["speed"], current["random"], current["saved"]),
                         ("Static", None, False, True))

    def test_msi_effects_exact_update_and_save_bytes_protocol_4_and_uniform_leds(self):
        device, modes = self.launch_msi()
        cases = [
            (1, {"color": "#123456", "brightness": 25}, 0, 30, 1, True),
            (2, {"color": "#abcdef", "brightness": 75, "speed": 25}, 1, 70, 1, True),
            (3, {"brightness": 50, "speed": 100, "random": True}, 2, 50, 3, False),
            (7, {"brightness": 0, "speed": 50, "random": True}, 1, 10, 3, False),
        ]
        for index, params, speed, brightness, color_mode, per_led in cases:
            with self.subTest(mode=modes[index]["name"]):
                before = len(self.writes())
                result = self.effect(device, mode=modes[index]["name"], **params)
                self.assertTrue(result["ok"], result)
                expected = {**modes[index], "speed": speed, "brightness": brightness,
                            "color_mode": color_mode}
                if per_led:
                    expected["colors"] = []
                body = word(index) + mode_bytes(expected, 4)
                payload = word(len(body) + 4) + body
                writes = [(0, 1101, payload)]
                if per_led:
                    rgb = params["color"]
                    packed = int(rgb[5:7] + rgb[3:5] + rgb[1:3], 16)
                    writes.append((0, 1050, struct.pack("<IH", 18, 3) + word(packed) * 3))
                self.assertEqual(self.writes()[before:], writes)
                lighting = result["result"]
                self.assertEqual(lighting["mode"], modes[index]["name"])
                self.assertEqual(lighting["random"], color_mode == 3)
                self.assertFalse(lighting["saved"])
                saved = self.save(device)
                self.assertTrue(saved["ok"], saved)
                self.assertTrue(saved["result"]["saved"])
                self.assertEqual(self.writes()[-1], (0, 1102, payload))
                self.assertEqual(self.fake.saved_modes[0], payload)
                self.advance(10)
        self.assertFalse(any(command in (1051, 1100) for _, command, _ in self.fake.commands))

    def test_per_led_mode_without_color_does_not_send_updateleds_and_omissions_keep_values(self):
        device, modes = self.launch_msi(6)
        first = self.effect(device, mode="Breathing", color="#abcdef", brightness=25, speed=100)
        self.assertTrue(first["ok"], first)
        before = len(self.writes())
        result = self.effect(device)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["result"], first["result"])
        expected = {**modes[2], "brightness": 30, "speed": 2, "colors": []}
        body = word(2) + mode_bytes(expected)
        payload = word(len(body) + 4) + body
        self.assertEqual(self.writes()[before:], [(0, 1101, payload)])
        self.assertTrue(self.save(device)["ok"])
        self.assertEqual(self.writes()[-1], (0, 1102, payload))

    def test_mode_validation_and_save_capabilities_fail_without_writes(self):
        device, _ = self.launch_msi()
        for params in ({"mode": "Direct"}, {"mode": "missing"}, {"mode": "Static", "speed": 0},
                       {"mode": "Static", "random": False},
                       {"mode": "Color ring", "color": "#123456"},
                       {"speed": True}, {"speed": 101}, {"speed": -1}, {"speed": 1.5},
                       {"mode": None}, {"mode": ""}, {"random": 0}, {"random": "true"}):
            with self.subTest(params=params):
                reply = self.effect(device, **params)
                self.assertEqual(reply["error"]["code"], "bad_request", reply)
                self.assertEqual(self.writes(), [])
                # Parameter type validation and the connection's write quota are independent.
                self.advance(0.11)
        self.fake.descriptors = [controller(version=4, modes=[mode(flags=32)], active=0)]
        self.assertEqual(self.save(device)["error"]["code"], "unsupported")
        self.assertEqual(self.writes(), [])

    def test_save_rate_limit_is_per_device_across_connections_and_exact_ten_seconds(self):
        device, _ = self.launch_msi()
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        self.assertTrue(self.save(device)["result"]["saved"])
        self.assertTrue(self.effect(device, brightness=25)["ok"])
        self.assertFalse(self.client.request("lighting.get", {"device": device["id"]})[
            "result"]["saved"])
        before = len(self.writes())
        with self.daemon.client() as other:
            self.assertEqual(other.request("lighting.save", {"device": device["id"]})[
                "error"]["code"], "rate_limited")
        self.advance(9.999)
        self.assertEqual(self.save(device)["error"]["code"], "rate_limited")
        self.assertEqual(len(self.writes()), before)
        self.advance(0.001)
        self.assertTrue(self.save(device)["result"]["saved"])
        self.assertEqual(len(self.writes()), before + 1)

    def test_reversed_mode_ranges_rounding_and_get_percent(self):
        from fakes.openrgb import msi_modes
        modes = msi_modes()
        modes[2].update(speed_min=2, speed_max=0, brightness_min=90, brightness_max=10)
        device, _ = self.launch_msi(modes=modes)
        for percent, speed, brightness in ((0, 2, 90), (25, 2, 70), (50, 1, 50),
                                           (75, 1, 30), (100, 0, 10)):
            result = self.effect(device, mode="Breathing", speed=percent, brightness=percent)
            self.assertTrue(result["ok"], result)
            expected = {**modes[2], "speed": speed, "brightness": brightness}
            body = word(2) + mode_bytes(expected, 4)
            self.assertEqual(self.writes()[-1], (0, 1101, word(len(body) + 4) + body))
            self.assertEqual(result["result"]["speed"], (2 - speed) * 50)
            self.assertEqual(result["result"]["brightness"], percent)

    def test_unsaved_changes_cancel_idle_timer_until_explicit_save(self):
        device, _ = self.launch_msi()
        self.advance(119.9)
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        self.advance(240)
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit"])
        self.assertTrue(self.save(device)["result"]["saved"])
        self.advance(119.999)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.advance(0.001)
        self.core.wait_until(lambda: len(self.command()["calls"]) == 2,
                             message="StopUnit after saved idle deadline")
        self.assertEqual(self.command()["calls"][-1][0], "StopUnit")

    def test_unsaved_state_survives_rescan_and_disable_allows_unit_stop(self):
        device, _ = self.launch_msi()
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        self.advance(2.01)
        self.devices("devices.rescan")
        self.assertFalse(self.client.request("lighting.get", {"device": device["id"]})[
            "result"]["saved"])
        self.advance(121)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.enable(False)
        self.devices("devices.rescan")
        self.assertEqual([call[0] for call in self.command()["calls"]], ["StartUnit", "StopUnit"])

    def test_save_limit_failure_keeps_dirty_state_and_no_idle_stop(self):
        device, _ = self.launch_msi()
        self.assertTrue(self.save(device)["ok"])
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        self.assertEqual(self.save(device)["error"]["code"], "rate_limited")
        current = self.client.request("lighting.get", {"device": device["id"]})
        self.assertFalse(current["result"]["saved"])
        self.advance(121)
        self.assertEqual(len(self.command()["calls"]), 1)

    def test_all_enabled_devices_must_be_saved_and_save_limits_are_independent(self):
        second = self.usb.add(12, "1234", "abcd", "other")
        self.rules.write_text(self.rules.read_text() + rule("1234", "abcd", "Other"))
        self.launch(descriptors=[controller(active=1), controller(
            name="Other", location="HID: /dev/hidraw12", active=1)])
        self.config.write_text(json.dumps({"v": 1, "enabled": {
            self.identity: True, second: True}}))
        devices = self.devices()
        self.assertEqual(len(devices), 2)
        self.assertTrue(all(device["writable"] for device in devices))
        for device in devices:
            self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        self.assertTrue(self.save(devices[0])["ok"])
        self.advance(121)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.assertTrue(self.save(devices[1])["ok"])
        # Both devices can be saved at exactly the same monotonic timestamp.
        self.assertTrue(self.save(devices[0])["ok"])
        self.advance(120)
        self.core.wait_until(lambda: len(self.command()["calls"]) == 2,
                             message="StopUnit once every enabled device is saved")

    def test_rejected_save_ack_never_marks_unsaved_changes_as_saved(self):
        device, _ = self.launch_msi(6)
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        applied = self.writes()[-2][2]
        self.fake.behavior = "write_rejected"
        self.assertFalse(self.save(device)["ok"])
        self.assertNotIn(0, self.fake.saved_modes)
        self.assertEqual(self.writes()[-1], (0, 1102, applied))
        self.fake.behavior = "normal"
        self.advance(10)
        self.devices("devices.rescan")
        self.assertFalse(self.client.request("lighting.get", {"device": device["id"]})[
            "result"]["saved"])
        self.advance(121)
        self.assertEqual(len(self.command()["calls"]), 1)

    def test_omitted_native_fields_preserve_raw_values_without_requantizing(self):
        from fakes.openrgb import msi_modes
        modes = msi_modes()
        modes[2].update(speed_max=1000, speed=333, brightness_max=1000, brightness=337)
        self.launch(advertised=4, descriptors=[controller(version=4, modes=modes, active=2)])
        device = self.devices()[0]
        result = self.effect(device)
        self.assertTrue(result["ok"], result)
        body = word(2) + mode_bytes(modes[2], 4)
        self.assertEqual(self.writes(), [(0, 1101, word(len(body) + 4) + body)])

    def test_random_false_restores_per_led_or_intrinsic_color_mode(self):
        device, _ = self.launch_msi()
        self.assertTrue(self.effect(device, mode="Flashing", random=True)["ok"])
        result = self.effect(device, random=False, color="#abcdef")
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["random"])
        self.assertEqual([command for _, command, _ in self.writes()], [1101, 1101, 1050])
        self.assertTrue(self.effect(device, mode="Color ring", random=True)["ok"])
        result = self.effect(device, random=False)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["result"]["random"])
        self.assertEqual(self.writes()[-1][1], 1101)

    def test_unsaved_state_and_save_limit_follow_physical_usb_after_hidraw_renumber(self):
        device, modes = self.launch_msi()
        self.assertTrue(self.effect(device, color="#abcdef")["ok"])
        applied = self.writes()[0][2]
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake.descriptors = [controller(version=4, modes=modes, active=1,
                                            location="HID: /dev/hidraw12")]
        self.advance(2.01)
        renamed = self.devices("devices.rescan")[0]
        self.assertEqual(device["id"], renamed["id"])
        self.assertFalse(self.client.request("lighting.get", {"device": renamed["id"]})[
            "result"]["saved"])
        self.assertTrue(self.save(renamed)["result"]["saved"])
        self.assertEqual(self.writes()[-1], (0, 1102, applied))
        self.advance(120)
        self.core.wait_until(lambda: len(self.command()["calls"]) == 4,
                             message="StopUnit after saving renamed physical device")

    def test_failed_set_is_saved_from_actual_active_descriptor_not_rejected_attempt(self):
        original = mode(flags=16 | 64 | 256, color_mode=2)
        self.launch(behavior="write_ignored", descriptors=[controller(active=1)])
        device = self.devices()[0]
        self.assertEqual(self.effect(device, color="#abcdef")["error"]["code"], "unsupported")
        self.fake.behavior = "normal"
        self.assertTrue(self.save(device)["result"]["saved"])
        body = word(1) + mode_bytes(original)
        self.assertEqual(self.writes()[-1], (0, 1102, word(len(body) + 4) + body))
