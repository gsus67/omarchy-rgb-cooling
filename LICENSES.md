# License inventory

`[V]` means checked against the linked license file or project source.
`[NV]` means the precise license or inclusion has not been verified.

## This project

| Component | SPDX | Status and source |
|---|---|---|
| Project code | `GPL-3.0-or-later` | [V] [`LICENSE`](LICENSE) and source headers. |

## Runtime and build dependencies

| Component | SPDX | Use | Status and source |
|---|---|---|---|
| Qt 6 base (`QtCore`, `QtNetwork`, `QtDBus`) | `LGPL-3.0-only OR GPL-3.0-only` | Build and runtime shared libraries | [V] [Qt licensing](https://doc.qt.io/qt-6/licensing.html); Qt identifies LGPL v3 as the community license and notes some components are GPL-only. |
| systemd-libs / libudev | `LGPL-2.1-or-later` | Build and runtime shared library | [V] [systemd licensing](https://github.com/systemd/systemd/blob/main/LICENSES/README.md) identifies libudev's license. |
| power-profiles-daemon | `GPL-3.0-or-later` | Optional runtime service, accessed over system D-Bus | [V] [Upstream COPYING](https://gitlab.freedesktop.org/upower/power-profiles-daemon/-/blob/main/COPYING). |
| OpenRGB | `GPL-2.0-or-later` | Optional external RGB engine, accessed through its network protocol | [V] [OpenRGB license](https://gitlab.com/CalcProgrammer1/OpenRGB/-/blob/master/LICENSE). RGB writes are currently blocked. |
| Quickshell | `LGPL-3.0-only` | Runtime shell hosting the QML widget | [V] [Upstream license](https://git.outfoxxed.me/quickshell/quickshell/src/branch/master/LICENSE). |
| Omarchy | `MIT` | Runtime plugin host and installer | [V] [Upstream license](https://github.com/basecamp/omarchy/blob/quattro/LICENSE). |

The project does not copy or statically link third-party code. External engines
are used through IPC (D-Bus or the OpenRGB network protocol). Qt and libudev
are system shared libraries.

These entries cover the direct components listed here, not every transitive
dependency of a user's system packages.

- [NV] Transitive package dependencies are not inventoried here.
- [NV] OpenRGB's installation and operation on a given system are not verified;
  only its license and optional protocol integration are documented.
