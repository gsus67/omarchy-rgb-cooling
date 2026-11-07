# Changelog

Changes are documented under
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - Unreleased

### Added

- Engines tab: install or remove OpenRGB with one button (pkexec), tracked so
  uninstalling the plugin removes exactly what it installed.
- Profiles tab: save, apply and delete up to 32 named RGB and system-power
  combinations in private per-user configuration; fan control remains with
  BIOS or CoolerControl.
- Optional Omarchy theme-colour sync, off by default and driven by theme
  change events without polling.
- Engines show SPDX license, package source, and the exact install command;
  official-repository installs require explicit confirmation.
- RGB control per enabled device: colour, brightness, effects, speed and random
  colour through sandboxed, on-demand OpenRGB; saving to the device is an explicit
  action.
- Accessible colour picker and clearer Lighting first-run and status states.
- Panel tabs: Cooling, Lighting, Profiles, Engines.
- `uninstall.sh` removes settings by default; `--keep-settings` keeps them.

- Socket-activated, unprivileged C++20 core with hwmon temperature and fan RPM
  readings.
- Omarchy bar widget and sensor panel, including user-defined sensor names.
- Silent, Balanced, and Turbo power-profile selection through
  `power-profiles-daemon`.
- Motherboard fan labels from an exact-board verified table.
- Optional demo mode and OpenRGB device discovery; RGB writes require explicit
  per-device enablement.
- User-level install footprint tracking and uninstall support.
- Security baseline, hardware inventory, and MSI B760 fan-control research.
- Architecture and lighting backend documentation.
- Installation and hardware-support documentation.
- License inventory for 12 direct and 339 required transitive runtime and build
  dependencies, verified against local package metadata.

### Changed

- OpenRGB lifecycle fixes: bounded start-up wait with manual recovery and visible
  device disable controls, SIGNALUPDATE parsing, and stable device IDs with
  recovery on re-enumeration.
- Colour picker pointer input keeps the panel keyboard shortcuts active.
- Fan channels remain read-only; fan curves stay under BIOS control.

### Fixed

- Engine removal preserves pre-existing orphaned packages and dependencies
  still required outside the recorded install set.
