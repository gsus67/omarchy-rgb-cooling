# Architecture

This document describes the implementation as it exists today. The wire
contract in [API.md](API.md) is authoritative when this overview and the API
documentation differ.

## Components

| Component | Responsibility | Boundary |
|---|---|---|
| `RgbCooling.qml` | Renders the bar widget and tabs, connects to the local API, and coordinates profiles | Runs as the logged-in user and does not access hardware directly |
| `ProfilesTab.qml` | Saves, applies, and deletes named RGB and power-mode combinations | Never stores or sends fan/PWM settings |
| `omarchy-rgb-profiles` | Validates and atomically stores the bounded per-user profile file | Mode `0600` data in a mode `0700` XDG config directory |
| `omarchy-rgb-cooling.socket` | Creates `$XDG_RUNTIME_DIR/omarchy-rgb-cooling.sock` for socket activation | Unix stream socket, mode `0600`, `Accept=no` |
| `rgbcd` | Validates API requests, reads sensors, exposes adapters, and coordinates power profiles and subscriptions | Unprivileged `systemd --user` service with a hardened unit |
| `Hwmon` / `SensorSource` | Reads temperatures and fan RPM from sysfs and builds stable sensor records | Read-only; PWM files and hardware registers are not written |
| `FanHeaders` | Applies exact-board fan header names from `data/fan-headers.json` | Only valid `user-verified` entries are applied |
| `PowerProfiles` | Reads and changes the active power profile through `power-profiles-daemon` | Uses the system D-Bus asynchronously; it does not run `powerprofilesctl` |
| `LightingAdapter` | Defines the daemon's lighting backend interface | The active implementation is selected when the server starts |
| `OpenRgbAdapter` | Discovers candidates and performs lighting operations through an OpenRGB SDK worker | Uses only numeric loopback and starts the plugin-owned user unit on demand |
| `DemoAdapter` | Supplies simulated sensors and one in-memory lighting device | Does not contact hardware or external engines |
| `omarchy-rgb-openrgb` | Resolves enabled USB identities and launches OpenRGB inside `bwrap` | Exposes only uniquely identified, enabled `/dev/hidrawN` nodes; no I2C devices |
| `omarchy-rgb-engines` | Reports, installs, and removes the closed list of optional engines | Package changes use `pkexec`; ownership is recorded before removal is allowed |

The OpenRGB launcher and package helper are separate programs. `rgbcd` asks
the systemd user manager to start the launcher unit; it never executes OpenRGB
or performs package management itself.

## Data flow

### Startup and local API

1. The systemd user socket listens before `rgbcd` is running.
2. A QML connection activates the daemon, which adopts the listening file
   descriptor from systemd.
3. Before Qt can buffer data from a new connection, `rgbcd` checks
   `SO_PEERCRED` and accepts only its own UID.
4. The UI and daemon exchange newline-delimited API v1 JSON. The daemon
   validates requests against the closed operation and parameter schemas in
   [API.md](API.md).

The daemon can create its own mode-`0600` socket with `--listen` for tests and
demo use. It refuses to replace an existing path, including an existing
socket.

### Sensors and fan names

`sensors` requests pass through `SensorSource` to `Hwmon`. The reader scans
sysfs attributes, reads temperature and RPM values, and returns API sensor
records. Recent results may be reused as specified by the API. Subscriptions
schedule further samples at the negotiated interval.

At startup, `Hwmon` asks `FanHeaders` to load the bounded JSON table. A fan
header name is applied only when chip and DMI values match exactly and the
entry is `user-verified`. Missing, invalid, oversized, or nonmatching data
leaves the generic `Fan N` label in place. User-renamed labels are a UI-only
overlay stored in the user's config directory.

### Power profiles

`profile.get` and `profile.set` are queued to a worker thread. The worker uses
`org.freedesktop.UPower.PowerProfiles` on the system bus and accepts only
`power-saver`, `balanced`, and `performance`. After a change it reads the
properties again before replying. A D-Bus connection is retained only while
requests or profile subscriptions need it; profile events follow
`PropertiesChanged`, not a polling timer.

Power profiles affect CPU power and heat generation. They do not implement
fan curves, and the Silent, Balanced, and Turbo UI names do not mean direct
fan control.

### Named profiles and theme colour

The Profiles tab combines the selected device's current OpenRGB settings with
one of the three validated system power modes. It calls
`omarchy-rgb-profiles` with a closed action list to save, list, delete, or
toggle `sync-theme` for at most 32 profiles. Names are 1–48 characters. The
helper rejects unknown fields, duplicate JSON keys, non-finite or out-of-range
values, links and oversized files. JSON files are opened with `O_NOFOLLOW` and
checked with `fstat` on the opened descriptor, so symlink-based configuration
layouts are intentionally unsupported. A malformed or schema-invalid profile
store is moved to a `.corrupt` backup and reset with a warning. Orphaned
`.profiles-*` staging files are removed while holding the store lock. The
helper atomically replaces
`$XDG_CONFIG_HOME/omarchy-rgb-cooling/profiles.json`; the directory is mode
`0700` and the file mode `0600`.

Applying a profile uses the existing `lighting.set` and `profile.set` API
operations. There is no cooling operation: firmware or CoolerControl remains
responsible for fan curves and PWM.

Theme-colour sync is optional and stored off by default. Its source is
`Commons.Color.accent`. The current shell implementation in
`/usr/share/omarchy/shell/Commons/Color.qml` loads that role from
`$HOME/.local/state/omarchy/current/theme/colors.toml`; it does not consult
`XDG_STATE_HOME`. QML reacts to the singleton's change notification when
Omarchy applies a theme; it has no polling timer. If the accent role is absent,
the panel foreground is the fallback. When sync is on, the live theme colour
overrides the saved profile colour and disables random colour when the mode
supports it. The device, mode, brightness, speed and system power mode keep
their saved values.

### Lighting discovery and control

Normal discovery reads connected USB HID identities and OpenRGB's packaged
udev rules without starting OpenRGB. A candidate is initially read-only. The
UI can enable it only through a confirmation dialog, then stores the choice in
`devices.json`; `rgbcd` only reads that file.

When a scan or lighting operation needs the engine, the OpenRGB worker asks
the systemd user manager to start `omarchy-rgb-cooling-openrgb.service`. The
launcher resolves each enabled USB identity to its current hidraw node and
builds a bubblewrap sandbox containing only unique enabled nodes. OpenRGB
listens on `127.0.0.1:6742`; the worker exchanges SDK protocol 6 packets over
that numeric loopback endpoint.

The worker marks a device writable only after all gates in [API.md](API.md)
pass. A lighting update selects the runtime `Static` mode and sends the
documented uniform colour and brightness representation. It then reads the
controller again to confirm the result. OpenRGB is stopped after its idle
window when there are no subscribers keeping it active.

### Optional engine packages

The Engines tab runs `omarchy-rgb-engines` with fixed arguments. The helper
knows only the closed engine list, currently OpenRGB. It queries pacman as the
user and invokes pacman through `pkexec` for an approved install or removal.
It removes an engine only when its mode-`0600` state record says the plugin
installed it.

## Security boundaries

- The QML process is an unprivileged API client. Hardware access belongs to
  the daemon or the separately sandboxed OpenRGB process.
- Socket mode `0600` limits pathname access, and `SO_PEERCRED` independently
  verifies every accepted peer before any bytes are read.
- The API is a closed set with type validation, bounded frames, connection
  limits, idle handling, and per-operation rate limits.
- `rgbcd` runs as a user service with no capabilities, no privilege gain, a
  read-only home view, a strict system view, and systemd syscall and namespace
  restrictions.
- OpenRGB receives only explicitly enabled, uniquely identified USB HID
  nodes. `0416:5302` is always excluded, and I2C/SMBus nodes are not present in
  its sandbox.
- Lighting writes require both UI opt-in and runtime capability gates. Device
  and engine text is treated as plain text by the UI.
- Package elevation is isolated in `omarchy-rgb-engines` and requires the
  user's `pkexec` approval. Neither QML nor `rgbcd` runs as root.

## Non-goals and write limits

- No PWM fan control: the project does not write `pwm*`, change fan curves, or
  write hardware registers. Fan control remains in firmware or CoolerControl.
- No general hardware-control proxy: API v1 exposes only the operations in
  [API.md](API.md).
- No broad OpenRGB discovery: the sandbox omits I2C/SMBus and all USB HID
  devices that the user did not enable.
- No explicit firmware persistence: the implementation does not send
  `SAVEMODE`, `SETCUSTOMMODE`, `UPDATEZONELEDS`, zone resize requests, or
  nonuniform LED buffers. Its only lighting writes are the `UPDATEMODE` and,
  for a per-LED Static mode, uniform `UPDATELEDS` sequence documented in
  [API.md](API.md). Persistence is device-specific and is not promised.
- No background engine polling or automatic retry loop. Engine access follows
  API requests, an explicit rescan, or relevant hotplug events while a client
  subscribes to devices.

