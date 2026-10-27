# Changelog

Changes are documented under [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - unreleased

### Added

- Engines tab: install or remove OpenRGB with one button (pkexec), tracked so
  uninstalling the plugin removes exactly what it installed.
- RGB control per enabled device: static colour and brightness through a
  sandboxed, on-demand OpenRGB that sees only the enabled devices.
- Panel tabs: Cooling, Lighting, Engines.
- `uninstall.sh` removes settings by default; `--keep-settings` keeps them.

- Socket-activated, unprivileged C++20 core with hwmon temperature and fan RPM readings.
- Omarchy bar widget and sensor panel, including user-defined sensor names.
- Silent, Balanced, and Turbo power-profile selection through `power-profiles-daemon`.
- Motherboard fan labels from an exact-board verified table.
- Optional demo mode and OpenRGB device discovery; RGB writes remain blocked.
- User-level install footprint tracking and uninstall support.
- Security baseline, hardware inventory, and MSI B760 fan-control research.

### Changed

- Fan channels remain read-only; fan curves stay under BIOS control.
