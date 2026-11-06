# Hardware support

Support is assigned to a specific feature, not to an entire device. A readable
sensor does not prove safe control, and support for one function does not imply
support for lighting, fan control, or firmware persistence.

## Evidence levels

The levels are progressive:

| Level | Meaning |
|---|---|
| `recognized` | The device identity or sensor path is detected. |
| `upstream-supported` | The relevant upstream engine or driver documents the exact device or function. |
| `simulation-tested` | The project adapter passed tests against simulated hardware. |
| `physically-tested` | The stated feature was exercised on the physical device. |

Only the user can confer `physically-tested` status. This project currently
claims that level only for the two results already declared in the README:
MSI B760 sensor/RPM monitoring, including the observed `fan5`/`fan6` header
association, and power-profile selection on that same system.

## Current support matrix

The highest established level below applies only to the feature in that row.
`[NV]` means not verified, matching the inventory terminology.

| Hardware or test target | Feature or path | Highest level | Limits |
|---|---|---|---|
| MSI B760 GAMING PLUS WIFI (MS-7D98), NCT6687D | Temperatures, fan RPM, and exact-board header-name table | `physically-tested` | The table entry is `user-verified`; its recorded physical observation covers only `fan5`/`fan6` as `SYS_FAN3`/`SYS_FAN4`. Monitoring only; PWM control is not supported |
| Same MSI B760 system | Silent, Balanced, and Turbo through `power-profiles-daemon` | `physically-tested` | Changes system power profile; BIOS retains fan control |
| Simulated RGB device and fake OpenRGB SDK | Discovery, protocol, static colour, and brightness paths | `simulation-tested` | Test fixtures are not evidence for a physical controller |
| MSI MYSTIC LIGHT USB `1462:7d98` | USB identity; OpenRGB candidate | `recognized` | `[NV]` Exact-board packaged support, safe modes, and physical operation |
| CORSAIR VANGUARD 96 `1b1c:2b0d` | OpenLinkHub device match | `upstream-supported` | No OpenLinkHub adapter; `[NV]` local package and operation |
| GLORIOUS Model O 2 Wireless `093a:822a` | USB identity | `recognized` | `[NV]` Chosen engine and exact-PID support |
| USBDISPLAY / Trofeo `0416:5302` | USB identity | `recognized` | Reserved for omarchy-trcc and always excluded here; no probing |
| AMD Navi 32 `1002:747e`, Sapphire `1da2:475d` | Direct hwmon temperatures and fan RPM | `recognized` | `[NV]` Exact retail model, RGB controller, and safe fan control |
| Intel CPU `coretemp.0` | Package and core temperatures | `recognized` | `[NV]` CPU fan and pump mapping |
| Two MAXIO NVMe controllers | Composite and auxiliary temperatures | `recognized` | `[NV]` Retail models; observed metadata is not a safe limit |
| Two `spd5118` nodes | RAM temperature monitoring | `recognized` | `[NV]` RAM identity and RGB support; no SMBus RGB access |
| ACPI, Intel Wi-Fi, and Realtek Ethernet hwmon nodes | Temperature monitoring | `recognized` | No lighting or cooling engine is proposed |
| Other inventoried USB devices and hubs | USB identity | `recognized` | `[NV]` Lighting and cooling support; not control candidates |

No physical OpenRGB controller, CoolerControl fan channel, or GPU fan-control
path is declared `physically-tested`.

### User-verified MSI fan-header table

The following mapping comes from the `user-verified` entry in
`data/fan-headers.json`. A header name is shown only when the chip, DMI vendor,
and DMI board match that entry exactly and its status is `user-verified`.
The recorded physical observation specifically covers only `fan5` and `fan6`
as `SYS_FAN3` and `SYS_FAN4`; it does not claim a separate physical check of
all seven mappings:

| hwmon channel | Physical header |
|---|---|
| `fan1` | `CPU_FAN1` |
| `fan2` | `PUMP_FAN1` |
| `fan3` | `SYS_FAN1` |
| `fan4` | `SYS_FAN2` |
| `fan5` | `SYS_FAN3` |
| `fan6` | `SYS_FAN4` |
| `fan7` | `SYS_FAN5` |

## Fan-control boundary

The project is read-only for cooling. `rgbcd` enumerates hwmon temperature and
fan-input files but never writes `pwm*`, changes a fan curve, or writes hardware
registers. Fan curves remain in BIOS/firmware or a separate cooling engine.

For the MSI NCT6687D path, PWM control is blocked by current kernel support:
the in-tree `nct6683` driver can expose monitoring, but the repository evidence
does not establish writable MSI PWM support in the reference kernel. The
MSI-specific write support found during research was a proposed patch, not an
established merged and released capability. CoolerControl cannot control a
motherboard channel that the loaded kernel driver does not expose as writable.

For this exact DMI board, the JSON identifies the controller as the NCT6687
family and its user-verified note records EC firmware 1.0 build 11/01/22. The
inventory independently establishes the exact MSI board identity. The
following MSI fan-control facts remain `[NV]`:

- the board's customer ID and exact writable-channel mapping;
- physical CPU, pump, and chassis-header wiring beyond the recorded
  `fan5`/`fan6` observation;
- safe duty limits and response for each channel;
- whether unloading a driver restores automatic BIOS behavior; and
- automatic-mode semantics on the running kernel.

Do not treat the external `nct6687d` DKMS module as verified for this board.
The repository does not establish that it is safer or more compatible than
the in-tree driver, and it must not be loaded alongside `nct6683` for the same
chip.

## Lighting boundary

The implemented lighting backend is OpenRGB only. It discovers candidates
from packaged udev rules without starting the engine. OpenRGB runs on demand
inside `bubblewrap` with access only to explicitly enabled, uniquely identified
USB HID nodes. I2C/SMBus devices, unenabled HID devices, and `0416:5302` are
excluded.

Lighting writes are limited to a runtime-validated static colour and
brightness. The project does not save a device mode to firmware, resize zones,
or promise that a visible colour survives engine exit or reboot. The simulated
OpenRGB coverage does not promote any inventoried physical RGB device above
its evidence level in the table.

See [Phase 1 inventory](INVENTORY.md) for the evidence behind recognized and
upstream-supported rows, and [fan-control research](FAN_CONTROL_RESEARCH.md)
for the MSI kernel and safety analysis.
