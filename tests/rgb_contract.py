"""Phase 3c integration tests, sharing the native build and isolated daemon fixture."""
import json
import os
from pathlib import Path
import select
import subprocess
import tempfile

from fakes.openrgb import OpenRgbServer, controller, mode, mode_bytes, word
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
        self.daemon = self.core.Daemon(self.root / "core", clock=clock, environment={
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
        self.launch(fragment=True)
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
                                          "brightness": 25, "brightness_emulated": False})
        self.assertEqual(self.fake.commands[0], (0, 40, word(6)))
        current = self.client.request("lighting.get", {"device": device["id"]})
        self.assertEqual(current["result"], result["result"])
        self.assertFalse(any(packet in (1050, 1051, 1100, 1102)
                             for _, packet, _ in self.fake.commands))

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

    def test_stop_after_exact_120_seconds_and_lighting_activity_extends_deadline(self):
        self.launch()
        device = self.devices()[0]
        self.advance(119.9)
        self.assertEqual(len(self.command()["calls"]), 1)
        self.assertTrue(self.set_color(device)["ok"])
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
        self.assertIn("protocol 6", device["blocked_reason"])
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
        # Controller identity is based on metadata/location in legacy SDKs; USB is the
        # stable physical identity exposed to the panel across every scan.
        (self.usb.root / "class/hidraw/hidraw9").rename(
            self.usb.root / "class/hidraw/hidraw12")
        self.fake.descriptors = [controller(location="HID: /dev/hidraw12")]
        self.advance(2.01)
        after = self.devices("devices.rescan")[0]
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

    def test_protocol_6_malformed_write_ack_is_rejected(self):
        self.launch(behavior="bad_write_ack")
        device = self.devices()[0]
        self.assertFalse(self.set_color(device)["ok"])
        self.assertEqual([command for _, command, _ in self.writes()], [1101])

    def test_upstream_per_led_static_keeps_led_buffer_and_reports_failure_honestly(self):
        self.launch(descriptors=[controller(modes=[mode("Direct", flags=32), mode()])])
        device = self.devices()[0]
        result = self.set_color(device, brightness=25)
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["error"]["code"], "unsupported")
        self.assertIn("per-LED", result["error"]["message"])
        expected = mode(brightness=30, colors=[0x563412])
        body = word(1) + mode_bytes(expected)
        self.assertEqual(self.writes(), [(0, 1101, word(len(body) + 4) + body)])
        current = self.client.request("lighting.get", {"device": device["id"]})["result"]
        self.assertEqual(current["color"], "#112233")
        self.assertEqual(current["brightness"], 25)
