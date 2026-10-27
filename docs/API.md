# rgbcd API and footprint (contract, API v1)

This is the contract between the QML UI and `rgbcd`. Both sides are built
against it in parallel; change it only through a PR that updates both.

## Transport

- Unix stream socket `$XDG_RUNTIME_DIR/omarchy-rgb-cooling.sock`, created by
  the systemd user socket unit (`Accept=no`, `SocketMode=0600`). `rgbcd`
  adopts it from `LISTEN_FDS`; with `--listen <path>` (tests and demo only)
  it binds its own socket at `0600` and refuses to replace a non-socket file.
- Every accepted connection is checked with `SO_PEERCRED`; a UID other than
  `rgbcd`'s own is closed before any byte is read.
- Framing: one JSON object per line, UTF-8, `\n` terminated. A line over
  64 KiB closes the connection with `too_large`. At most 8 concurrent
  connections; a connection idle for 30 s without a subscription is closed.

## Messages

Request:

```json
{"v": 1, "id": 7, "op": "sensors", "params": {}}
```

`id` is an integer from 1 to 9007199254740991 (2^53 - 1, exact in JSON and
QML) chosen by the client and echoed back; anything else is `bad_request`
with `id: null`. Unknown
fields are ignored; wrong types are `bad_request`.

Responses:

```json
{"v": 1, "id": 7, "ok": true, "result": {}}
{"v": 1, "id": 7, "ok": false, "error": {"code": "blocked", "message": "..."}}
```

Error codes: `bad_request`, `unknown_op`, `too_large`, `unsupported`,
`blocked`, `unavailable`, `rate_limited`, `internal`. `message` is plain
text for humans; the UI never interprets it as markup.

Events (only on a subscribed connection; no `id`):

```json
{"v": 1, "event": "sensors", "data": {"sensors": [], "primary": "..."}}
{"v": 1, "event": "devices", "data": {"devices": []}}
{"v": 1, "event": "profile", "data": {"profile": "balanced", "available": [], "degraded": ""}}
```

## Operations (closed set)

| op | params | result |
|---|---|---|
| `hello` | — | `{"version": "0.1.0", "api": 1, "demo": false}` |
| `status` | — | `{"engines": [Engine], "uptime_s": 12}` |
| `sensors` | — | `{"sensors": [Sensor], "primary": "<sensor id or empty>"}`; reads hwmon on request (results younger than 500 ms are reused), so it never needs a subscription |
| `devices` | — | `{"devices": [Device]}` |
| `subscribe` | `{"topics": ["sensors", "devices", "profile"], "interval_ms": 2000}` | `{}`; `interval_ms` is clamped to 500–10000 |
| `unsubscribe` | — | `{}` |
| `devices.rescan` | — | `{"devices": [Device]}` after one fresh scan of every engine; `rate_limited` if the last scan was under 2 s ago |
| `profile.get` | — | `{"profile": "power-saver"\|"balanced"\|"performance", "available": ["..."], "degraded": ""}`; `unavailable` if power-profiles-daemon is not running |
| `profile.set` | `{"profile": "power-saver"\|"balanced"\|"performance"}` | same as `profile.get` after the change; the profile must be in `available`; rate limited to 2 per second per connection |
| `lighting.get` | `{"device": "<id>"}` | `Lighting` |
| `lighting.set` | `{"device": "<id>", "mode": "<mode name>", "color": "#rrggbb", "brightness": 0-100, "speed": 0-100, "random": bool}` (only `device` is required; omitted fields keep their current value) | `Lighting` after applying; `blocked` / `unsupported` / `unavailable` otherwise |
| `lighting.save` | `{"device": "<id>"}` | `Lighting` with `saved: true` after `SAVEMODE`; `unsupported` if the mode cannot be saved; `rate_limited` if the device was saved less than 10 s ago |

`lighting.set` is rate limited to 10 per second per connection.

### Power profiles (the panel's Silent / Balanced / Turbo modes)

rgbcd talks to power-profiles-daemon on the system D-Bus
(`org.freedesktop.UPower.PowerProfiles`, property `ActiveProfile`); it never
runs `powerprofilesctl`. The modes change how much heat the CPU produces; fan
curves stay in the BIOS. A `profile` event is sent to subscribers when the
daemon emits `PropertiesChanged` (also when the profile is changed elsewhere,
such as the Omarchy menu), never by polling. rgbcd only connects to the
system bus while some connection uses a `profile.*` operation or subscribes
to `profile`.

Motherboard Super I/O sensors (`nct6683`, `nct6687`, `nct6775`, `nct6779`,
`it87`, `it8xxx`) use the device name `Motherboard`; their fans are listed with
`Fan N` labels. Fan channels are read-only in rgbcd regardless of sysfs
permissions.

### Fan header names (data/fan-headers.json)

Motherboard fan channels get the board's real header name only from
`data/fan-headers.json`, never from code. An entry matches when the hwmon
`name` equals `chip` and `/sys/class/dmi/id/board_vendor` and `board_name`
equal `dmi_vendor` and one of `dmi_boards` exactly (no wildcards: the same chip
is wired differently on other boards, and newer MSI boards with the NCT6687D-R
variant use another order). `headers` maps sysfs channels (`fan1`…) to names;
channels not listed keep `Fan N`. `status` is `user-verified` (someone checked
the headers in the BIOS or on the board) or `source-derived`; only
`user-verified` entries are applied. Names must match `^[A-Z0-9_]{1,16}$`.

rgbcd reads the file once at start from `--data-dir <plugin>/data` (set by
bootstrap in `ExecStart`); a missing, oversized (> 256 KiB) or invalid file is
ignored with a warning and every fan keeps `Fan N`.

Sensors gain two fields: `channel` (the sysfs attribute stem, e.g. `fan5`,
`temp1`) and `header` (the matched header name, or empty). When `header` is
set, `label` equals it.

### User fan names (panel only)

The panel can rename any sensor. Names are stored by the UI, not rgbcd, in
`$XDG_CONFIG_HOME/omarchy-rgb-cooling/labels.json` as
`{"v": 1, "labels": {"<sensor id>": "<name>"}}`, at most 32 characters each,
shown as plain text. bootstrap creates `$XDG_CONFIG_HOME/omarchy-rgb-cooling`
with `0700` permissions (it is user data, so it is not in the ledger);
`uninstall.sh` removes it unless `--keep-settings` is given. rgbcd stays read-only.

### Engines (install from the panel)

The panel's Engines tab installs or removes an engine with one button. Only a
closed list is supported; today that is `openrgb` (Arch package `openrgb`,
needed for RGB on supported boards). The panel never builds commands itself: it
runs `bin/omarchy-rgb-engines` with fixed arguments.

`bin/omarchy-rgb-engines <command>` (Python stdlib, runs as the user) prints one
JSON line:

| command | effect |
|---|---|
| `status` | `{"engines": [{"id": "openrgb", "installed": bool, "installed_by_plugin": bool, "version": "", "size": "9.5 MiB", "purpose": "..."}]}` |
| `install openrgb` | records which packages are new (`pacman -S --print --needed`), then `pkexec /usr/bin/pacman -S --needed --noconfirm openrgb`; marks it `installed_by_plugin` only if it was not installed before |
| `uninstall openrgb` | only if `installed_by_plugin`: `pkexec /usr/bin/pacman -Rns --noconfirm openrgb` (removes its dependencies only when nothing else needs them); otherwise refuses |
| `uninstall-all` | uninstalls every engine the plugin installed; used by `uninstall.sh` |

The record lives in `$XDG_STATE_HOME/omarchy-rgb-cooling/engines.json`
(`{"v": 1, "engines": {"openrgb": {"installed_by_plugin": true, "packages": [...],
"new_dependencies": [...], "installed_at": "..."}}}`, mode `0600`). A cancelled
or failed `pkexec` changes nothing and reports `{"ok": false, "error": ...}`.
`uninstall.sh` runs `uninstall-all` before deleting the state directory; if the
user cancels, it prints the exact manual command and continues.

### OpenRGB, sandboxed and on demand

rgbcd never runs OpenRGB itself. bootstrap installs a second user unit,
`omarchy-rgb-cooling-openrgb.service` (in the ledger), whose `ExecStart` runs
`bin/omarchy-rgb-openrgb`. That launcher:

- reads the devices the user enabled (below) and resolves each to its current
  `/dev/hidrawN` through sysfs (USB vendor, product and serial);
- refuses `0416:5302` and any device that is not a USB HID node;
- starts `/usr/bin/openrgb --server --server-host 127.0.0.1 --server-port 6742
  --noautoconnect --config $XDG_STATE_HOME/omarchy-rgb-cooling/openrgb` inside
  `bwrap`, with a minimal `/dev` that contains only those hidraw nodes (no I²C,
  no other HID devices), read-only `/usr`, `/etc`, `/sys`, `/run/udev`, its own
  config directory writable, network shared (loopback only);
- exits with an error if `bwrap` or `openrgb` is missing or nothing is enabled.

Discovery never runs OpenRGB, because some OpenRGB detectors send
initialisation commands to a device as soon as they open it. Instead rgbcd
lists **candidates**: connected USB HID devices whose `VID:PID` appears in
OpenRGB's packaged udev rules (`/usr/lib/udev/rules.d/60-openrgb.rules`, read
once per scan), never `0416:5302`. Candidates appear in `devices` with
`engine: "openrgb"`, `support: "recognized"`, `enabled: false`,
`writable: false` and the name from the rules comment or `VID:PID`. OpenRGB
only starts once at least one device is enabled, and it sees only those.

rgbcd starts the unit through the systemd user manager on D-Bus
(`StartUnit`) only when a scan or lighting operation needs OpenRGB. After a
successful start, an asynchronous, bounded startup wait retries the SDK connection
every 250 ms for at most 10 s while OpenRGB detects hardware. Pending `devices`,
`devices.rescan` and `lighting.*` requests wait for the real scan result; a
successful scan also emits a `devices` event. If the deadline expires, the engine
becomes `unreachable` with an explicit reason and makes no further attempts until
another operation requests a scan; there is no background polling.
Udev re-enumeration of an enabled USB device is debounced for 1 s and
asynchronously restarts the unit to refresh sandbox HID nodes, reporting
“Device reconnected; restarting OpenRGB” while deferring lighting writes for up
to 15 s and retrying an unacknowledged write once (acknowledged writes are never
replayed).

rgbcd stops the unit (`StopUnit`) after 120 s without lighting activity or
subscribers to `devices` (the open panel). Only `lighting.get`, `lighting.set`
and `devices` subscriptions count as use; `sensors` and `profile` subscriptions
do not keep OpenRGB running. The 120 s deadline restarts when the last `devices`
subscriber unsubscribes or disconnects, or on lighting activity.

### Enabling RGB control per device

Writes are off until the user enables a device in the panel and confirms a
warning. The UI stores the choice in
`$XDG_CONFIG_HOME/omarchy-rgb-cooling/devices.json` as
`{"v": 1, "enabled": {"usb:1462:7d98:<serial>": true}}`. rgbcd only reads it.
A device record gains `usb` (`usb:VID:PID:SERIAL` from the hidraw node OpenRGB
reports, empty when unknown) and `enabled`.

A device is `writable` only when all of these hold: it is enabled, its `usb`
identity is known and unique, it is not `0416:5302`, OpenRGB runs through the
plugin's own unit, and it has a `Static` mode with a mode-specific or per-LED
colour. `lighting.set` then sends `UPDATEMODE` with that `Static` mode and the
colour; brightness uses the mode's own range when it has one, otherwise the
colour is scaled and `brightness_emulated` is true. When the `Static` mode
uses per-LED colours (`MODE_COLORS_PER_LED`, as on MSI Mystic Light), the
colour is applied with `UPDATELEDS` carrying the **same** colour for every LED
of that controller, right after `UPDATEMODE` selects `Static`; with
mode-specific colours it travels inside `UPDATEMODE`. rgbcd never sends
`SAVEMODE`, `SETCUSTOMMODE`, `UPDATEZONELEDS`, zone resizes, or LED buffers
with different colours, and re-reads the controller to confirm the change.

### Effects and saving to the device

`modes` lists the controller's OpenRGB modes in OpenRGB's order, except
`Direct` (software per-LED streaming, not a panel effect). Flags map as:
`speed` = `MODE_FLAG_HAS_SPEED`; `brightness` = `MODE_FLAG_HAS_BRIGHTNESS`;
`color: "single"` when the mode takes per-LED or mode-specific colours,
`"none"` when it only animates its own colours; `random` =
`MODE_FLAG_HAS_RANDOM_COLOR`; `savable` = `MODE_FLAG_MANUAL_SAVE` or
`MODE_FLAG_AUTOMATIC_SAVE`.

`lighting.set` validates every field against the chosen mode (a colour for a
`"none"` mode, a speed for a mode without speed, `random` without the flag are
`bad_request`). `speed` and `brightness` are 0-100 on the API and mapped onto
the mode's own range (rounded; reversed when OpenRGB's minimum is larger than
its maximum). The write is `UPDATEMODE` with the chosen mode, then, only when
the mode uses per-LED colours and a colour is set, `UPDATELEDS` with that same
colour for every LED. `random: true` selects `MODE_COLORS_RANDOM`.

`lighting.save` sends `SAVEMODE` for the active mode exactly as last applied,
only when the user presses the panel's **Save to device** button. It writes the
device's own memory, so the effect survives OpenRGB stopping and reboots; it is
never sent automatically and is limited to once per 10 s per device.

`saved` is false after any `lighting.set` until the next `lighting.save`
(true at start: nothing has been changed yet). Many devices, such as MSI
Mystic Light, fall back to their saved state when OpenRGB stops, so the idle
stop only happens when every enabled device is `saved`; with unsaved changes
OpenRGB keeps running and the panel says so.

### Engine scans (no background polling)

rgbcd never polls engines on its own. An engine is contacted only by:

- the first `devices`, `lighting.get` or `lighting.set` after start (one scan,
  then the result is reused);
- `devices.rescan` (the panel's Scan button, and once each time the panel opens);
- a udev hotplug event while some connection is subscribed to `devices`.

A failed scan leaves the engine `absent` or `unreachable` until the next one;
there are no retries after the bounded startup wait described above.
The UI subscribes to `devices` only while the
panel is open, so with the panel closed nothing contacts OpenRGB.

### Types

```text
Engine   {id: "openrgb", state: "absent"|"unreachable"|"ready"|"blocked", reason: string}
Sensor   {id: string, label: string, device: string, kind: "temp"|"fan",
          value: number|null, unit: "C"|"rpm", source: "hwmon"|"demo", stale: bool}
Device   {id: string, name: string, vendor: string, engine: string,
          support: "recognized"|"upstream-supported"|"simulation-tested"|"physically-tested",
          writable: bool, blocked_reason: string, excluded: bool, modes: [Mode],
          capabilities: ["lighting.read", "lighting.write", "brightness"]}
Lighting {device: string, mode: string, color: "#rrggbb", brightness: 0-100,
          brightness_emulated: bool, speed: 0-100 | null, random: bool, saved: bool}
Mode     {name: string, speed: bool, brightness: bool,
          color: "single" | "none", random: bool, savable: bool}
```

- `device` is a short human name for the physical device, never a sysfs path:
  `CPU` (with the vendor when known, e.g. `Intel CPU`), `AMD GPU` / `NVIDIA GPU` /
  `Intel GPU`, `NVMe 1`, `NVMe 2`… (numbered by PCI address order), `RAM`, `Wi-Fi`,
  `Ethernet`, `ACPI`; anything else uses the hwmon `name`. `label` is the hwmon
  `*_label` when present (e.g. `Package id 0`, `edge`), otherwise `Temperature`,
  `Temperature 2`… or `Fan`, `Fan 2`… Both are plain text.
- RAM sensors from several hwmon devices (`spd5118`, `jc42`, `ee1004`) are
  labelled `DIMM 1`, `DIMM 2`… in I²C bus/address order, never repeated
  `Temperature` rows.
- Ethernet matching uses the hwmon name prefix (`r8169_0_600:00` is Ethernet)
  or a network-class parent device.
- When a device has more than one fan channel, every fan is labelled with its
  sysfs channel number (`Fan 1`, `Fan 5`, `Fan 10`), so the first one is never a
  bare `Fan`. Sensors are listed per device in natural order (`Fan 2` before
  `Fan 10`), temperatures before fans.
- Sensor ids are stable: `<hwmon name>:<canonical parent device path>:<channel>`
  (for example `coretemp:platform/coretemp.0:temp1`), never `hwmonN`.
- `value` is `null` when the reading is missing, non-finite or failed; `stale`
  is true when it is older than three intervals.
- `primary` is the CPU package temperature when present, otherwise the first
  temperature.
- Devices that are excluded (Trofeo `0416:5302`) are listed with
  `excluded: true`, `writable: false` and are never opened.
- `writable` is false unless every write gate is met (identity, single owner,
  engine exclusions, verified support); `blocked_reason` says which gate failed.

## Demo mode

`rgbcd --demo` (or the plugin setting `demo`) serves simulated sensors and one
simulated RGB device (`demo:rgb0`, `support: "simulation-tested"`, writable).
Demo data never touches real hardware or engines.

## Footprint (what the plugin adds to a system)

`bootstrap.py <plugin dir>` creates only these paths, and records every one in
`$XDG_STATE_HOME/omarchy-rgb-cooling/installed-files` (one absolute path per line):

- `$XDG_STATE_HOME/omarchy-rgb-cooling/bin/rgbcd`
- `$XDG_STATE_HOME/omarchy-rgb-cooling/.core-version`, `.bootstrap.lock`
- `$XDG_CONFIG_HOME/systemd/user/omarchy-rgb-cooling.socket`
- `$XDG_CONFIG_HOME/systemd/user/omarchy-rgb-cooling.service`
- the enablement symlink `systemctl --user enable` creates for the socket
- each of these directories that did not exist before, recorded with a
  trailing `/` (for example `$XDG_CONFIG_HOME/systemd/user/sockets.target.wants/`),
  so uninstall removes it again only if it is empty

It runs `systemctl --user daemon-reload` and `enable --now omarchy-rgb-cooling.socket`
(never the service). It prints one JSON line: `{"ok": true}` or
`{"ok": false, "error": "<plain text>"}`.

`uninstall.sh` stops the units, removes the engines the plugin installed
(`bin/omarchy-rgb-engines uninstall-all`, which asks for the password through
pkexec), removes the plugin through `omarchy plugin remove`, every path in the
ledger plus the fixed list above, `$XDG_STATE_HOME/omarchy-rgb-cooling`, the
runtime socket and the user settings in `$XDG_CONFIG_HOME/omarchy-rgb-cooling`
(sensor names, enabled devices). `uninstall.sh --keep-settings` keeps those
settings. Nothing outside these paths is touched, and only the engines step
needs a password.

Tests drive `bootstrap.py` and `uninstall.sh` in a throwaway `HOME` with stub
`systemctl` and `omarchy` executables first on `PATH`.
