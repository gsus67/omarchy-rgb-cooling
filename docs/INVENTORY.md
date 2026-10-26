# Phase 1 inventory and decision

Observation date: 2026-10-26 (America/Chicago). Scope: the common block and Phase 1 of [PROMPT.md](PROMPT.md), associated with issue #1. [V] The local prompt was read; the [remote issue](https://github.com/gsus67/omarchy-rgb-cooling/issues/1) could not be retrieved [NV]. No Phase 2 work was performed.

## Evidence and limits

- **[V] Verified:** directly observed locally, or explicitly stated in the cited upstream source. Verification applies to that specific claim, not to successful operation on this machine.
- **[I] Inferred:** a proposed choice or conclusion from the stated evidence.
- **[NV] Not verified:** unavailable evidence, unresolved version/identity, or an untested capability. Absence from the observed inventory is not proof of absence from the machine.
- [V] Device progression required by [PROMPT.md](PROMPT.md): `recognized` → `upstream-supported` → `simulation-tested` → `physically-tested`. No device is simulation-tested here, and only the user may confer physically-tested status. Reading a sensor does not establish tested control.
- [V] Only this document was written. Inspection used package queries, source reads, compiler preprocessing through stdin/stdout, pkg-config, PCI enumeration, sysfs reads and web retrieval. No installation, engine execution, service activation, I²C/SMBus scan, hardware write or sysfs write was performed. Existing I²C sensor attributes were only read.
- [V] `lsusb` returned `unable to initialize libusb: -99`. USB descriptors below come from `/sys/bus/usb/devices/*`; `lspci -nnk` succeeded. No USB device was opened through an engine. Shell network retrieval failed DNS resolution; web browsing provided the external sources. AUR pages returned Anubis access denial and its RPC endpoint was inaccessible [NV].
- [V] `pacman -Si` evidence describes the **local sync database**, without refreshing it; it does not prove current remote mirror state. All package observations below are dated 2026-10-26. Mutable web branch references were inspected as available; a release/commit binding is explicitly unresolved where noted.

## Installed platform and build prerequisites

[V] Source: `pacman -Q omarchy quickshell gcc clang pkgconf qt6-base python systemd-libs`; module evidence: `pkg-config --modversion Qt6Core Qt6Network Qt6Test libudev`.

| Component | Observed version / result |
|---|---|
| Omarchy | [V] `4.0.6-1` |
| Quickshell | [V] `0.3.2.r7.g2b4501a-1` |
| GCC / Clang | [V] `16.2.1+r23+gd564253eb6c8-1` / `23.1.3-4` |
| pkgconf | [V] `3.0.10-1`; `/usr/bin/pkg-config` exists |
| Qt base | [V] `6.12.0-3`; Qt6Core and Qt6Network both resolve to `6.12.0` |
| Python | [V] `3.14.8-1`; stdlib-only bootstrap remains the required approach |
| libudev | [V] pkg-config `262`, systemd-libs package `262.1-1` |
| C++20 | [V] `/usr/bin/g++ -std=c++20 -dM -E -x c++ -` accepts empty stdin and reports `__cplusplus 202002L`. No binary/object was produced. [NV] Complete Qt C++20 compile/link/run was deliberately not performed under the single-file write restriction. |
| Test dependencies (separate) | [V] Qt6Test `6.12.0`; CMake `4.4.4-1`; `ctest` on PATH. [NV] Tests were not run. These are not bootstrap prerequisites. |
| ShellCheck / Go | [V] Neither installed under those package names; ShellCheck not found by `command -v`. No Bash implementation or Go dependency was introduced. |

[V] All seven engine package names queried with `pacman -Q` were absent (`openrgb`, `coolercontrol`, `coolercontrold`, `liquidctl`, `openlinkhub`, `ckb-next`, `gloriousctl`, plus `rgb_keyboard`). [NV] This is not an exhaustive search for custom binaries or differently named variants and does not establish that no engine process exists.

### Observed plugin contract

[V] Sources: `/usr/share/omarchy/bin/omarchy-plugin-add`, `/usr/share/omarchy/bin/omarchy-plugin-validate`, `/usr/share/omarchy/shell/services/PluginRegistry.qml`, `/usr/share/omarchy/shell/plugins/README.md` and `/usr/share/omarchy/shell/Ui/Panel.qml`.

- [V] `omarchy-plugin-add` stages a Git clone, validates it before moving it under `~/.config/omarchy/plugins/<id>`, requests a shell rescan, and optionally enables it. It warns that plugins execute unsandboxed in the shell. It was read, not executed.
- [V] `omarchy plugin validate <folder>` expects numeric `schemaVersion: 1`, required `id`, `name`, `version`, `kinds`, `entryPoints`, safe existing relative entry points, a nonreserved ID and no plugin symlinks outside the skipped `.git` tree. Kind mappings include `bar-widget` → `barWidget`, `panel` → `panel`, `service` → `service`. This validates structure, not hardware behavior or daemon security.
- [V] A manifest QML `service` is an in-shell component; it is not a systemd service declaration. Services and keep-loaded panels mount at shell startup; other panels load on demand.
- [V] `Panel.qml` supplies `bar`, `moduleName`, `settings`, `ipcTarget`, `manageIpc`, `opened` and open/close/toggle lifecycle. A bar widget can use this base for its button and popup; a separate `panel` manifest kind is not necessary merely to show that popup.

| Local reference | Manifest / source observed |
|---|---|
| `~/Work/omarchy-tool` | [V] Commit `d3239c9300312d13f4523520300129cae78070c7`; v0.0.36, MIT, schema 1, `bar-widget`, `ToolPanel.qml`; imports `qs.Ui` / `qs.Commons`, uses `Panel` and its own IPC handler. |
| `~/Work/omarchy-trcc` | [V] Commit `692eb2978f0d8dcd2e071414e100d5fc67fe0a12`; v0.0.9, GPL-3.0-or-later, schema 1, `bar-widget`, `Trofeo.qml`; defaults to `0416:5302`. |
| `~/Work/omarchy-taskbar` | [V] Commit `b555ac8d35a9715ed9a3e5c2c558a8079afc8358`; v0.0.6, MIT, schema 1, `panel`, `keepLoaded: true`, `Taskbar.qml`; root `Item` receives `shell`, `manifest`, `omarchyPath`. |

[V] `omarchy-trcc/native_build.py` discovers a compiler and pkg-config modules, directly builds without CMake, and currently uses C++17. `bootstrap.py` uses `flock`, a source/module-version hash, temporary build directory, atomic binary replacement and `$XDG_STATE_HOME/omarchy-trcc/bin`. Its digest does **not** explicitly include compiler version/path or flags as separate tool identity inputs; hashing the build script captures script changes. [I] The future C++20 implementation should strengthen the fingerprint with tool identities/versions and effective flags, and retain locking/atomic replacement. [V] TRCC enables a persistent user service; [PROMPT.md](PROMPT.md) explicitly requires socket activation instead for this project. No reference bootstrap was imported or run.

## Hardware → engine → status

[V] Local hardware sources: `lspci -nnk`, `/sys/bus/usb/devices`, `/sys/class/drm/card1/device`, `/sys/class/dmi/id/{board_vendor,board_name,board_version,product_name}` and `/sys/class/hwmon`. DMI reports MSI B760 GAMING PLUS WIFI (MS-7D98), board version 3.0, system MS-7D98. USB topology and PCI BDF below identify this observation, not universally permanent identities.

| Physical device / observation | Engine or access path | Support evidence and current state |
|---|---|---|
| [V] MSI MYSTIC LIGHT USB `1462:7d98`, port `1-11` | [I] OpenRGB candidate, USB path only | [V] Recognized locally. [V] Upstream has a [matching motherboard issue](https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4012) and a [PID-specific mode correction proposal](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3453). [NV] Exact-board support in packaged 1.1, merge/release inclusion and safe modes remain unresolved; do not promote to upstream-supported for this exact board. |
| [V] CORSAIR VANGUARD 96 USB `1b1c:2b0d`, `1-8` | [V] OpenLinkHub | Upstream-supported: [device list](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/docs/supported-devices.md) explicitly lists VANGUARD 96 / `2b0d`. [NV] Availability of that driver in a pinned packaged release, and local permissions/operation. ckb-next 0.6.2 [model table](https://github.com/ckb-next/ckb-next/blob/v0.6.2/src/daemon/usb.c) does not list VANGUARD [V]; OpenRGB exact-PID support [NV]. |
| [V] GLORIOUS Model O 2 Wireless USB `093a:822a`, `1-7` | [NV] No chosen engine | Recognized. [V] gloriousctl's [supported list](https://github.com/enkore/gloriousctl) names `258a:0033` and `258a:0036`, not this product. [NV] OpenRGB support for this exact connection mode/PID. Do not equate Model O with Model O 2 Wireless. |
| [V] USBDISPLAY / Trofeo USB `0416:5302`, `1-6.3` | [V] Reserved exclusively for omarchy-trcc | Recognized; explicit exclusion in [PROMPT.md](PROMPT.md), backed by local TRCC manifest. No integration or probing. [NV] Exclusion before enumeration/control in any proposed engine has not been established. |
| [V] AMD Navi 32 `1002:747e`, subsystem Sapphire `1da2:475d`, PCI `0000:03:00.0`, driver `amdgpu` | [V] Direct hwmon monitoring; [I] CoolerControl only in a later phase | Recognized; edge/junction/memory temperature and fan RPM readable. [V] CoolerControl documents [AMD GPU support and RDNA3 limitations](https://docs.coolercontrol.org/devices/gpus). [NV] Exact retail GPU model, RGB controller and safe fan-control support on this card. No GPU overdrive or boot changes proposed. |
| [V] Intel CPU sensors, platform `coretemp.0` | [V] Direct hwmon | Recognized; package and six core temperatures readable. No separate engine needed [I]. CPU fan/pump mapping [NV]. |
| [V] Two NVMe controllers: `04:00.0` MAXIO `1e4b:1602`, `05:00.0` MAXIO `1e4b:1202`, driver `nvme` | [V] Direct hwmon | Recognized; composite and two auxiliary temperatures each. SSD retail models [NV]. |
| [V] Two `spd5118` sensors at existing kernel nodes `8-0051`, `8-0053` | [V] Direct hwmon | Recognized temperature sensors; RAM manufacturer/RGB controller/support [NV]. Existing sysfs readings do not justify RGB SMBus access. |
| [V] ACPI `acpitz`, Intel Wi-Fi `8086:7a70` / `iwlwifi`, Realtek Ethernet `10ec:8125` / `r8169` | [V] Direct hwmon | Recognized, temperature readings available. No RGB engine proposed [I]. |
| [V] USB EDIFIER R20BT `2d99:a134` (`1-3`), Intel Bluetooth `8087:0033` (`1-14`), Genesys hubs `05e3:0608` (`1-5`, `1-6`), Realtek hub `0bda:5411` (`1-5.2`), root hubs `1d6b:0002/0003` | [I] None in scope | Recognized. Lighting/cooling control support [NV]; not candidates. |

[V] Remaining PCI enumeration (no engine proposed [I]): Intel host `00:00.0 8086:4650`; PCI bridges `00:01.0 8086:460d`, `00:06.0 8086:464d`, `00:1a.0 8086:7a48`, `00:1c.0 8086:7a38` (`pcieport`); accelerator `00:08.0 8086:464f`; monitoring `00:0a.0 8086:467d` (`intel_vsec`); USB `00:14.0 8086:7a60` (`xhci_hcd`); SRAM `00:14.2 8086:7a27`; management `00:16.0 8086:7a68` (`mei_me`); SATA `00:17.0 8086:7a62` (`ahci`); ISA `00:1f.0 8086:7a06`; audio `00:1f.3 8086:7a50` (`snd_hda_intel`); SMBus `00:1f.4 8086:7a23` (`i801_smbus`); SPI `00:1f.5 8086:7a24` (`intel-spi`); AMD bridges `01:00.0 1002:1478`, `02:00.0 1002:1479` (`pcieport`); GPU audio `03:00.1 1002:ab30` (`snd_hda_intel`). Engine support for additional functions is [NV]; no bus was scanned beyond PCI enumeration.

### Readable hwmon snapshot

[V] Sources: the respective `/sys/class/hwmon/hwmon*/name`, `temp*_input`, `temp*_label`, `fan*_input`, `pwm*` files. Numbers are one snapshot, not thermal validation. Temperatures below are input values divided by 1000. All listed inputs were readable as the current user.

| Observed node / stable parent cue | Temperatures °C | RPM / PWM attributes (read only) |
|---|---|---|
| [V] hwmon0 `acpitz`, `thermal_zone0` | temp1 27.8 | None observed |
| [V] hwmon1 `nvme`, PCI `05:00.0` | Composite 34.85; Sensor 1 34.85; Sensor 2 39.85 | None observed |
| [V] hwmon2 `nvme`, PCI `04:00.0` | Composite 38.85; Sensor 1 38.85; Sensor 2 32.85 | None observed |
| [V] hwmon3 `amdgpu`, PCI `03:00.0` | edge 46; junction 58; mem 72 | `fan1_input=646`, `fan1_enable=0`, fan min/max `0/3600`; `pwm1=38`, `pwm1_enable=2`, PWM min/max `0/255` |
| [V] hwmon4 `spd5118`, `00:1f.4/i2c-8/8-0051` | temp1 31.5 | None observed |
| [V] hwmon5 `spd5118`, `00:1f.4/i2c-8/8-0053` | temp1 30.75 | None observed |
| [V] hwmon6 `r8169_0_600:00`, PCI `06:00.0` MDIO parent | temp1 40 | None observed |
| [V] hwmon7 `iwlwifi_1`, `thermal_zone1` | temp1 32 | None observed |
| [V] hwmon8 `coretemp`, `/sys/devices/platform/coretemp.0` | Package id 0 31; cores 0–5: 25, 39, 25, 27, 31, 26 | None observed |

[V] No motherboard CPU/chassis fan RPM, pump RPM or motherboard PWM channel was exposed in this observed tree. [NV] Their physical existence, wiring and firmware behavior are unknown. `pwm1_enable=2` and fan attributes are recorded as raw values, not proof of a safe control mode. [V] NVMe auxiliary `temp2_max/temp3_max` reported `65261850` and minima `-273150`; these implausible metadata values must not become validated operating limits [I]. No duty minimum, pump minimum or recovery procedure has been validated [NV].

[I] Resolve sensors by canonical parent + driver/name + channel/label, and reconcile after hotplug; never persist `hwmonN`, `cardN` or engine list indices as identity. [V] MSI and Corsair USB serial attributes exist and are nonempty; the Glorious node has no serial attribute. Values are intentionally omitted. [I] USB identity should combine VID/PID, serial when reliable, physical port/topology and interface identity; without a unique serial, require topology/user confirmation and block ambiguous writes. PCI identity needs BDF/topology plus vendor/device/subsystem IDs; existing I²C nodes need controller topology/address/driver, without scanning.

## Engines, licenses and distribution

[V] Package metadata source: local `pacman -Si`; upstream sources linked per row. [NV] A branch name is not an immutable commit. Rows without a pinned version cannot satisfy a release-specific license/support sign-off yet. The table distinguishes exact SPDX evidence from generic GPL badges; no transitive-license audit is claimed.

| Engine / inspected version or ref | SPDX license evidence | Package classification as of observation date | Without GUI / interface / overlap |
|---|---|---|---|
| OpenRGB; sync package `1.1-1`, upstream `master` | [V] `GPL-2.0-or-later` in package metadata and [source SPDX header](https://github.com/CalcProgrammer1/OpenRGB/blob/master/NetworkProtocol.h); [LICENSE](https://github.com/CalcProgrammer1/OpenRGB/blob/master/LICENSE). [NV] Full source binding of packaged 1.1. | [V] Official **extra**, `openrgb 1.1-1`, build 2026-10-17; not installed. | [V] [Upstream README](https://github.com/CalcProgrammer1/OpenRGB) supports headless server/CLI; [SDK](https://openrgb.org/sdk.html) is a network protocol. [V] Current header defines binary packets, default `127.0.0.1:6742`, protocol 6. [I] Must negotiate and validate, never assume protocol 5 from older docs. [I] Potential overlap with all RGB engines on shared devices. |
| CoolerControl / coolercontrold; current docs, `main` daemon README | [V] `GPL-3.0-or-later` explicitly in [daemon README](https://gitlab.com/coolercontrol/coolercontrol/-/blob/main/coolercontrold/README.md). [NV] Exact current release/commit binding. | [V] Official project [Arch instructions](https://docs.coolercontrol.org/installation/arch) identify **AUR** `coolercontrol` and `coolercontrol-bin`; service name is `coolercontrold`. [NV] Current AUR versions; neither coolercontrol nor coolercontrold found in local sync DB. | [V] Independent [daemon](https://docs.coolercontrol.org/daemon/); [REST/OpenAPI](https://docs.coolercontrol.org/development/rest) defaults to localhost:11987 and documents session/Bearer authentication. [V] Arch docs use liquidctl for USB devices. [I] Do not run standalone liquidctl concurrently; may overlap OpenLinkHub/OpenRGB on shared coolers or LEDs. |
| liquidctl `v1.16.0` | [V] `GPL-3.0-or-later` explicit in [versioned module](https://github.com/liquidctl/liquidctl/blob/v1.16.0/liquidctl/__init__.py), with [license text](https://github.com/liquidctl/liquidctl/blob/v1.16.0/LICENSE.txt). | [V] Official **extra**, `liquidctl 1.16.0-1`, build 2026-03-04; package's legacy license field is `GPL3`. | [V] Versioned module documents Python API and CLI; no GUI required. [I] Not a separate project adapter: delegate through CoolerControl. [NV] No exact local cooler/controller match established; Trofeo is not authorized. |
| OpenLinkHub `main` | [V] `GPL-3.0-or-later` grant in [device source](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/src/devices/devices.go) and [LICENSE](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/LICENSE). [NV] Exact release/commit binding. | [V] No `openlinkhub` in local sync DB. [V] Upstream offers [release/source and other-distribution routes](https://github.com/jurkovic-nikola/OpenLinkHub). [NV] AUR `openlinkhub` page inaccessible; existence/version of that package or a `-bin` variant not established. | [V] [Configuration](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/README.md) allows frontend off, loopback HTTP :27003, `manual:false`, exclusions by uint16 ID. `manual:true` disables thermal monitoring/automatic speeds and is forbidden here. [V] [HTTP implementation](https://github.com/jurkovic-nikola/OpenLinkHub/blob/main/src/server/server.go) exposes JSON device APIs. [I] Overlaps ckb-next/OpenRGB and CoolerControl/liquidctl on shared Corsair hardware. |
| ckb-next `v0.6.2` | [V] Package declares `GPL-2.0-only`; [versioned LICENSE](https://github.com/ckb-next/ckb-next/blob/v0.6.2/LICENSE) contains GPLv2. [NV] Repository-wide exceptions/transitive grants. | [V] Official **extra**, `ckb-next 0.6.2-4`, build 2026-05-28; not installed. | [V] [Daemon IPC source](https://github.com/ckb-next/ckb-next/blob/v0.6.2/src/daemon/devnode.c) creates `/dev/input/ckb*/cmd` and notification FIFOs plus model/serial files. [I] Daemon can be driven without GUI, but permission/security setup needs review; FIFO number is not identity. [I] Exclusive ownership required against OpenLinkHub/OpenRGB. |
| gloriousctl `latest` (upstream branch) | [V] `EUPL-1.2`, [LICENSE](https://github.com/enkore/gloriousctl/blob/latest/LICENSE). [NV] Immutable current commit binding. | [V] No `gloriousctl` in local sync DB. [NV] AUR page denied; package version/classification beyond upstream source distribution unverified. | [V] [CLI](https://github.com/enkore/gloriousctl) supports settings/info and effects, [source](https://github.com/enkore/gloriousctl/blob/latest/gloriousctl.c) uses hidapi. [NV] No daemon API verified. [I] Overlap with OpenRGB or other mouse configurators if targeting the same mouse. |
| rgb_keyboard (dokutan), `master` | [V] `GPL-3.0-or-later`, explicit grant in [source](https://github.com/dokutan/rgb_keyboard/blob/master/rgb_keyboard.cpp), despite less precise badges elsewhere. [NV] Immutable current commit/release binding. | [V] [Upstream README](https://github.com/dokutan/rgb_keyboard/blob/master/README.md) links **AUR** `rgb_keyboard-git`; not in local sync DB. [NV] Current AUR version. | [V] Headless CLI plus optional GUI; USB/libusb implementation, flags for color/brightness/profiles. Published keyboards use VID `0c45`; no local Corsair support demonstrated. [I] Potential overlap with OpenRGB on supported keyboards; no local use proposed. |

[I] Engine ownership is per physical device, not per lighting versus fan function. CoolerControl using liquidctl is one ownership chain, not permission for a second standalone liquidctl instance. Shared-device engines need explicit exclusions before detection as well as before control. No exclusions were configured in this phase [V].

### Trofeo exclusion and write gates

[V] [PROMPT.md](PROMPT.md) always reserves `0416:5302` for TRCC and blocks coexistence if exclusion cannot be guaranteed. [NV] OpenRGB's exact 1.1 detector configuration and enumeration behavior for this device remain unverified; ignoring it only in the adapter is insufficient. OpenLinkHub's published exclusion field describes product IDs, not a complete persistent physical-identity scheme [V]. [NV] That alone does not prove exclusion before opening/probing every interface. Neither engine is approved to start by this inventory.

[I] For a later approved implementation, default-deny hardware writes until identity, ownership, engine exclusions and supported capabilities are resolved. Limit engine connections to numeric loopback or Unix sockets; store any credentials in 0600 files, never URLs/argv. For fan/pump control, additionally require channel mapping, physical safe limits and engine/firmware behavior on exit, crash, lost sensor, suspend and disconnect, plus a control-return procedure. All such channel-level validations remain [NV]; Phase 1 offers no cooling writes. These requirements come from [PROMPT.md](PROMPT.md), not a claimed engine guarantee.

### OpenMouse / mouse-protocol — notes only

[V] [OpenMouse](https://github.com/OpenMouse-Project/openmouse) is a browser control panel using WebHID; [mouse-protocol](https://github.com/OpenMouse-Project/mouse-protocol) contains codecs and WebHID drivers. The [project listing](https://github.com/OpenMouse-Project) identifies AGPL-3.0 licensing. [NV] Exact `AGPL-3.0-only` versus `AGPL-3.0-or-later` grants for pinned current commits were not established. [V] They are explicitly excluded from integration by [PROMPT.md](PROMPT.md). No code, bridge or browser hardware session was used.

## Marketplace policy

[V] Published policy is accessible: [SECURITY.md](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md), [SUBMISSION.md](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md), inspected 2026-10-26. These mutable pages were not bound to a commit [NV].

[V] The security baseline treats service management, bundled executable binaries, privileges, installers, package-manager use and remote builds as review capabilities, not automatic prohibitions. It flags unsafe remote execution and dangerous passwordless privilege patterns. Binary capability detection is not behavioral inspection. Complete exact-commit evidence and explicit maintainer approval govern publication; incomplete scans fail closed. [V] Submission requires a public root repository, root manifest, README with install/removal, root license and documented external dependencies. [I] This project's native daemon and user service need disclosure/review at publication; policy does not justify rejecting the monitoring MVP. No submission or external message was made.

## MVP proposal

[I] **Preferred Phase 2 candidate:** native QML bar temperature/popup, unprivileged C++20/Qt6 `rgbcd`, direct hwmon telemetry, and one OpenRGB-controlled **MSI MYSTIC LIGHT `1462:7d98` on USB `1-11`**, conditional on the gates below. No implementation is approved by this document.

- [I] Main bar sensor: `coretemp` / `/sys/devices/platform/coretemp.0`, label `Package id 0`, currently `hwmon8/temp1_input` (31 °C observed). Dashboard: GPU edge/junction/memory and **GPU fan `fan1_input` at PCI `0000:03:00.0`** (646 RPM observed), plus the other readable temperatures. Re-resolve hwmon paths at runtime. No additional telemetry package is needed [I], because these reads succeeded [V]. CPU/chassis fans and pump remain unavailable [NV].
- [I] RGB scope: one static color and capability-checked brightness; label RGB scaling if brightness is emulated. Do not resize unknown LED zones, select Direct mode, control RAM/GPU RGB or scan SMBus as a shortcut. [V] The [upstream 7d98 proposal](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3453) reports shared PID across board SKUs and a Direct-mode failure on another SKU. [NV] Its merged status, packaged inclusion and applicability to this exact DMI board are unresolved. This prevents unconditional RGB approval.
- [V] Minimum additional engine package for that candidate is available in the local sync DB as **`openrgb 1.1-1` in extra**. [I] Only after approval and release/support/exclusion verification, the user could install it with `sudo pacman -S openrgb` (documented only; not executed). Recheck the version before installation. Do not add i2c-tools, CoolerControl, liquidctl or extra engines for this MVP. Current Core/Network/Python/build dependencies are already present [V]; complete Qt linking remains [NV].
- [I] Start with simulation and monitoring while the RGB gates are unresolved. Before any engine starts, prove Trofeo exclusion at detection and control, USB-only detection scope, single owner, exact board/mode support and loopback binding. A successful API response alone is insufficient. Hardware testing belongs to the user and cannot be claimed now.
- [I] Alternative if MSI support cannot be established: **VANGUARD 96 `1b1c:2b0d` via OpenLinkHub**, the clearest exact upstream RGB match [V]. This needs explicit scope approval because [PROMPT.md](PROMPT.md) places extra adapters in Phase 4, plus a pinned release, verified Arch installation route, safe startup/exclusions, API schemas and `manual:false`. [NV] No minimal version-verified install command can yet be offered for that route. Do not use upstream download-to-shell installers.
- [V] Required future architecture remains that in [PROMPT.md](PROMPT.md): UI never accesses hardware; `rgbcd` never writes PWM/registers; systemd user `.socket`, `Accept=no`, `ListenStream=%t/omarchy-rgb-cooling.sock`, `SocketMode=0600`; validate `LISTEN_PID`/`LISTEN_FDS`, adopt with `QLocalServer::listen(qintptr)` and check `SO_PEERCRED` before requests. No relink/unlink of systemd's socket. A same-UID peer check does not isolate same-user processes. Plain-text QML for device/engine strings, fixed validated operations, stdlib bootstrap and GPL-3.0-or-later own code are mandatory. No units or code were created.

## Decisions needed from the user

1. [I] Approve or reject the preferred scope: CPU package temperature, GPU temperatures/RPM and one **conditional MSI RGB** device. Accept that RGB stays disabled until exact support/mode and Trofeo exclusion are established; monitoring/demo can proceed only after Phase 2 approval.
2. [I] If MSI cannot meet those gates, choose whether to defer physical RGB or explicitly bring the OpenLinkHub VANGUARD 96 adapter forward from Phase 4. Its current package/release binding is still [NV].
3. [NV] Confirm which case/header lights are physically connected to the MSI controller, and whether any other configurator owns the MSI/Corsair/mouse/GPU. No ownership or wiring was assumed from VID:PID.
4. [I] Keep all fan/pump control with existing firmware/owner for this MVP. A later cooling phase requires the user's channel identification and physical validation; this inventory has no safe cooling-write candidate.

[V] Phase 1 ends here. No engine installation/start, hardware test, publication or next phase is authorized or performed by this document.
