# Omarchy RGB & Cooling

Native Omarchy plugin (Quickshell/QML + unprivileged C++/Qt6 core) to monitor cooling and control RGB lighting from the bar.

**Status: phase 1 (inventory). Nothing works yet — do not install.**

Design principles:

- The UI is unprivileged and never touches hardware; it talks to `rgbcd`, a socket-activated `systemd --user` service.
- `rgbcd` never writes PWM or hardware registers. Fan control is delegated to an engine with its own safety (CoolerControl) or left to BIOS/firmware.
- Base telemetry comes from `/sys/class/hwmon`, so it needs no extra packages.
- The plugin never installs packages itself; it shows the exact command and you run it.

The development plan lives in [docs/PROMPT.md](docs/PROMPT.md) (Spanish), tracked by the phase issues. Security rules and CI checks: [SECURITY.md](SECURITY.md); workflow: [CONTRIBUTING.md](CONTRIBUTING.md).

License: GPL-3.0-or-later.
