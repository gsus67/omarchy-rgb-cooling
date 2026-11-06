# Installation

## Requirements

- Omarchy 4.x with its plugin system and Quickshell.
- A working `systemd --user` session.
- Qt 6 base, a C++20 compiler, and `pkg-config` for the native core. The
  required modules are `Qt6Core`, `Qt6Network`, `Qt6DBus`, and `libudev`.
- Python 3 for the standard-library-only bootstrap and helper scripts.
- Optional: `power-profiles-daemon` for the Silent, Balanced, and Turbo
  power-profile choices. These change the system power profile, not fan
  curves.
- For RGB control: `/usr/bin/bwrap` and `/usr/bin/openrgb`. Install
  `bubblewrap` separately; after explicit approval, the Engines tab can
  install OpenRGB from the official Arch repository.

The reference system used Omarchy 4.0.6, Quickshell 0.3.2, Qt 6.12,
GCC 16.2, and systemd-libs 262.1. These are observed versions, not declared
minimum versions.

## Install

The supported installation path is Omarchy's Git plugin manager:

```sh
omarchy plugin add https://github.com/gsus67/omarchy-rgb-cooling.git --enable
```

`install.sh` is only a compatibility entry point and executes that same
command.

When the widget first loads, `bootstrap.py` builds the native core in the
user state directory, installs the three user-unit files, reloads the user
manager, and enables the API socket:

```sh
systemctl --user enable --now omarchy-rgb-cooling.socket
```

The core service is socket-activated. The OpenRGB service is installed but
is not started during bootstrap; it starts on demand only when an enabled
device needs it. If the widget does not appear, run:

```sh
omarchy restart shell
```

The core installation does not require root access. Package installation is
a separate, explicitly approved action in the Engines tab.

## Engines

Engine actions use a closed list. Unknown engine names and actions are
rejected. The implemented list currently contains only `openrgb`.

| Engine | Use | Distribution | Installation status |
|---|---|---|---|
| OpenRGB | Static USB HID lighting | Official Arch `extra`; GPL-2.0-or-later | Supported by the Engines tab |
| CoolerControl | External fan and pump engine | AUR `coolercontrol` or `coolercontrol-bin`; GPL-3.0-or-later | Not implemented in the Engines tab |

For OpenRGB, the Engines tab asks for approval and runs the equivalent of:

```sh
sudo pacman -S --needed openrgb
```

Internally, the helper uses `pkexec` with `/usr/bin/pacman`; neither the QML
process nor `rgbcd` gains privileges. The helper installs only OpenRGB;
`bubblewrap` must be installed separately. The sandboxed launcher requires
the fixed paths `/usr/bin/bwrap` and `/usr/bin/openrgb`.

CoolerControl is not in the helper's closed list. The repository identifies
its Arch packages as AUR packages, but does not verify a current AUR version
or prescribe an AUR helper. Install it outside the plugin using the current
upstream Arch instructions if a future supported cooling setup requires it.
The UI does not install AUR packages.

The helper records ownership in:

```text
$XDG_STATE_HOME/omarchy-rgb-cooling/engines.json
```

The record is mode `0600`. OpenRGB is marked `installed_by_plugin` only when
it was absent before the approved transaction. A pre-existing OpenRGB package
is never claimed or removed by the plugin.

## Uninstall

Run the uninstaller from the installed plugin directory:

```sh
bash "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.gsus67.omarchy-rgb-cooling/uninstall.sh"
```

`XDG_CONFIG_HOME` defaults to `~/.config` when it is unset.

It disables and stops the user units, asks the engine helper to remove only
packages recorded as installed by this plugin, disables and removes the
Omarchy plugin, and deletes the paths in the installation ledger. It also
removes the project state, runtime socket, and settings.

The installation ledger is:

```text
$XDG_STATE_HOME/omarchy-rgb-cooling/installed-files
```

Only project-owned state and unit paths are accepted from that ledger.

Use `--keep-settings` to retain sensor names and enabled-device choices:

```sh
bash "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/io.github.gsus67.omarchy-rgb-cooling/uninstall.sh" --keep-settings
```

If approval for engine removal is cancelled, the uninstaller continues and
reports that OpenRGB remains installed. It then removes the project state,
including `engines.json`, so the plugin-ownership record is lost and automatic
removal cannot be retried. If OpenRGB was recorded as plugin-installed, remove
it manually afterward with:

```sh
sudo pacman -Rns openrgb
```

The uninstaller never removes an OpenRGB package that was present before the
plugin installed.

## Return control to firmware or another engine

The plugin never takes PWM fan control. It reads temperatures and fan RPM,
does not write `pwm*` or hardware registers, and creates no cooling profiles.
Silent, Balanced, and Turbo select `power-profiles-daemon` profiles; they do
not replace BIOS fan curves. Therefore BIOS/firmware already retains fan
control while the plugin is running. Stopping the project units does not
restore a previously selected system power profile.

To stop the project socket and services without uninstalling them, use the
same unit operations as `uninstall.sh`:

```sh
systemctl --user disable --now omarchy-rgb-cooling.socket
systemctl --user stop omarchy-rgb-cooling.service omarchy-rgb-cooling-openrgb.service
```

Reactivate socket activation with:

```sh
systemctl --user enable --now omarchy-rgb-cooling.socket
```

Stopping the units does not unload the widget. To disable the still-loaded
Omarchy plugin as well, run:

```sh
omarchy plugin disable io.github.gsus67.omarchy-rgb-cooling
```

There is no project-created CoolerControl profile to remove. The plugin also
does not send OpenRGB's save-mode operation, so it does not deliberately save
a lighting profile to device firmware. Stopping OpenRGB ends project control,
but whether a device keeps its last visible colour is device-specific. Start
the intended lighting engine and apply its profile after the project units
have stopped.

To remove stored sensor names and enabled-device choices as well, run the
uninstaller without `--keep-settings`. A full uninstall is the final step for
returning ownership permanently; its installation ledger limits removal to
project-created files and its engine record protects pre-existing packages.

The optional `nct6683 force=1` setup in the README is monitoring-only and does
not enable fan control. If it was made persistent, reverse it with the exact
commands in [Optional hardware setup](../README.md#optional-hardware-setup).
