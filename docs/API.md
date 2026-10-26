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
```

## Operations (closed set)

| op | params | result |
|---|---|---|
| `hello` | — | `{"version": "0.1.0", "api": 1, "demo": false}` |
| `status` | — | `{"engines": [Engine], "uptime_s": 12}` |
| `sensors` | — | `{"sensors": [Sensor], "primary": "<sensor id or empty>"}`; reads hwmon on request (results younger than 500 ms are reused), so it never needs a subscription |
| `devices` | — | `{"devices": [Device]}` |
| `subscribe` | `{"topics": ["sensors", "devices"], "interval_ms": 2000}` | `{}`; `interval_ms` is clamped to 500–10000 |
| `unsubscribe` | — | `{}` |
| `lighting.get` | `{"device": "<id>"}` | `Lighting` |
| `lighting.set` | `{"device": "<id>", "color": "#rrggbb", "brightness": 0-100}` | `Lighting` after applying; `blocked` / `unsupported` / `unavailable` otherwise |

`lighting.set` is rate limited to 10 per second per connection.

### Types

```text
Engine   {id: "openrgb", state: "absent"|"unreachable"|"ready"|"blocked", reason: string}
Sensor   {id: string, label: string, device: string, kind: "temp"|"fan",
          value: number|null, unit: "C"|"rpm", source: "hwmon"|"demo", stale: bool}
Device   {id: string, name: string, vendor: string, engine: string,
          support: "recognized"|"upstream-supported"|"simulation-tested"|"physically-tested",
          writable: bool, blocked_reason: string, excluded: bool,
          capabilities: ["lighting.read", "lighting.write", "brightness"]}
Lighting {device: string, color: "#rrggbb", brightness: 0-100, brightness_emulated: bool}
```

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

`uninstall.sh` stops and disables the socket and service, removes every path
in the ledger plus the fixed list above, removes the plugin through
`omarchy plugin remove`, and removes `$XDG_STATE_HOME/omarchy-rgb-cooling`
and the runtime socket. `uninstall.sh --purge` also removes
`$XDG_CONFIG_HOME/omarchy-rgb-cooling` (user settings). Nothing outside these
paths is touched, and nothing needs `sudo`.

Tests drive `bootstrap.py` and `uninstall.sh` in a throwaway `HOME` with stub
`systemctl` and `omarchy` executables first on `PATH`.
