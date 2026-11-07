# License inventory

This document is a factual package inventory, not legal advice.

## Verification basis

- Recorded: 2026-11-06.
- Reference system: Omarchy 4.5.0 on x86_64.
- Package database: pacman 7.1.0 with libalpm 16.0.1.
- [V] means the package name, version, and license came from the local
  `pacman -Qi` database, or the stated local license file.
- [NV] means local evidence is absent; the entry says exactly what is
  missing.
- The label "SPDX (pacman)" reproduces the local pacman `Licenses` items in
  their recorded order; it does not normalize or validate them. Some package
  metadata uses inherited names rather than normalized SPDX expressions,
  including `Apache`, `BSD`, `GPL`, `LGPL`, `MIT`, `GPL3`, `custom`, and
  `custom:none`. Line wrapping changes presentation only.
- This inventory covers direct and required transitive dependencies for both
  runtime and build. "Optional dependency edges" means relationships listed in
  pacman's `Optional Deps` field; those edges are excluded.
- The transitive closure follows required `Depends On` relationships
  recursively and resolves each dependency and `Provides` token in full,
  including its version, operator, and ABI suffix; base-name-only matches are
  not used.
- When a token has multiple installed non-`lib32` candidates, all are included.
  This applies, for example, to `ttf-font`, `ca-certificates`, and `dbus-units`.
  A matching non-`lib32` provider excludes `lib32-*` candidates; an
  unversioned token already satisfied by a 64-bit package in the closure does
  not pull in its 32-bit counterpart.

## This project

- [V] `omarchy-rgb-cooling`
  SPDX: `GPL-3.0-or-later`
  Evidence: `LICENSE` contains the GPL version 3 text, and SPDX identifiers
  support `GPL-3.0-or-later` in the files that carry them. The 15 tracked
  Python, QML, and shell files with no `SPDX-License-Identifier` line are
  recorded as pending; no header is inferred for them here.

## Direct runtime and build dependencies

The 12 direct packages below include required and explicitly documented
optional components.

- [V] `qt6-base` `6.12.0-3`
  SPDX (pacman): `GPL-3.0-only`, `LGPL-3.0-only`, `LicenseRef-Qt-Commercial`,
  `Qt-GPL-exception-1.0`
  Use: QtCore, QtNetwork, and QtDBus build and runtime libraries.
  Additional local evidence: `/usr/share/licenses/qt6-base/` contains the four
  files named by the package license metadata.

- [V] `systemd-libs` `262.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`, `CC0-1.0`, `GPL-2.0-or-later WITH
  Linux-syscall-note`
  Use: libudev build and runtime library.

- [V] `openrgb` `1.1-1`
  SPDX (pacman): `GPL-2.0-or-later`
  Use: optional runtime RGB engine launched on demand.

- [V] `bubblewrap` `0.13.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`
  Use: sandbox used by `bin/omarchy-rgb-openrgb`.

- [V] `omarchy-power-profiles-daemon` `0.30-3` (provider for
  `power-profiles-daemon`)
  SPDX (pacman): `GPL-3.0-only`
  Use: optional runtime system D-Bus service used for power profiles.

The project does not copy or statically link OpenRGB or
`power-profiles-daemon`. OpenRGB is an optional external engine accessed
through its network protocol; `power-profiles-daemon` is accessed over D-Bus.

- [V] `quickshell` `0.3.2.r7.g2b4501a-1`
  SPDX (pacman): `LGPL-3.0-only`
  Use: runtime host for the QML bar widget and panel.
  Additional local evidence: `/usr/share/licenses/quickshell/LICENSE` contains
  LGPL version 3.

- [V] `omarchy` `4.5.0-3`
  SPDX (pacman): `MIT`
  Use: plugin host and the `omarchy plugin add` installer.

- [V] `python` `3.14.8-1`
  SPDX (pacman): `PSF-2.0`
  Use: runtime for project scripts with `python3` shebangs.

- [V] `systemd` `262.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`, `CC0-1.0`, `GPL-2.0-or-later`, `MIT-0`
  Use: runtime manager for the installed user service and socket units.

- [V] `polkit` `128-1`
  SPDX (pacman): `LGPL-2.0-or-later`
  Use: runtime provider of `pkexec` for `bin/omarchy-rgb-engines`.

- [V] `gcc` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`,
  `GFDL-1.3-or-later`
  Use: `gcc` is the documented compiler; `native_build.py` accepts `g++`,
  `clang++`, or `c++`.

- [V] `pkgconf` `3.0.10-1`
  SPDX (pacman): `ISC`
  Use: build-time `pkg-config` implementation used by `native_build.py`.

## Required transitive runtime and build dependencies

The union below contains 339 installed packages. Direct packages are not
repeated.

- [V] `abseil-cpp` `20260817.0-2`
  SPDX (pacman): `Apache-2.0`

- [V] `acl` `2.4.0-1`
  SPDX (pacman): `LGPL-2.1-or-later AND GPL-2.0-or-later`

- [V] `adwaita-cursors` `51.0-1`
  SPDX (pacman): `CC-BY-SA-3.0 OR LGPL-3.0-only`

- [V] `adwaita-fonts` `51.0-2`
  SPDX (pacman): `OFL-1.1`

- [V] `adwaita-icon-theme` `51.0-1`
  SPDX (pacman): `CC-BY-SA-3.0 OR LGPL-3.0-only`

- [V] `adwaita-icon-theme-legacy` `46.2-3`
  SPDX (pacman): `CC-BY-SA-3.0 OR LGPL-3.0-only`

- [V] `aquamarine` `0.15.1-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `at-spi2-core` `2.62.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `attr` `2.6.0-1`
  SPDX (pacman): `LGPL-2.1-or-later AND GPL-2.0-or-later`

- [V] `audit` `4.2.1-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.0-or-later`

- [V] `avahi` `1:0.9rc5-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `bash` `5.3.20-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `binutils` `2.47-4`
  SPDX (pacman): `GPL-2.0-or-later`, `GPL-3.0-or-later`, `LGPL-2.0-or-later`,
  `LGPL-3.0-or-later`, `GFDL-1.3`, `FSFAP`

- [V] `boost-libs` `1.92.0-1`
  SPDX (pacman): `BSL-1.0`

- [V] `brotli` `1.2.0-1`
  SPDX (pacman): `MIT`

- [V] `btrfs-progs` `7.1-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `bzip2` `1.0.8-6`
  SPDX (pacman): `BSD`

- [V] `ca-certificates` `20240618-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `ca-certificates-mozilla` `3.131.1-1`
  SPDX (pacman): `MPL-2.0`

- [V] `ca-certificates-utils` `20240618-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `cairo` `1.18.6-1`
  SPDX (pacman): `LGPL-2.1-only OR MPL-1.1`

- [V] `coreutils` `9.12-2`
  SPDX (pacman): `GPL-3.0-or-later`, `GFDL-1.3-or-later`

- [V] `cpptrace` `1.0.4-2`
  SPDX (pacman): `MIT`

- [V] `cryptsetup` `2.8.8-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `curl` `8.23.0-1`
  SPDX (pacman): `curl`

- [V] `dav1d` `1.5.4-1`
  SPDX (pacman): `BSD-2-Clause`

- [V] `db5.3` `5.3.28-7`
  SPDX (pacman): `Sleepycat`

- [V] `dbus` `1.16.2-2`
  SPDX (pacman): `AFL-2.1 OR GPL-2.0-or-later`

- [V] `dbus-broker` `37-3`
  SPDX (pacman): `Apache-2.0`

- [V] `dbus-broker-units` `37-3`
  SPDX (pacman): `Apache-2.0`

- [V] `dbus-units` `37-3`
  SPDX (pacman): `CC0-1.0`

- [V] `dconf` `51.0-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `default-cursors` `3-1`
  SPDX (pacman): `CC0-1.0`

- [V] `desktop-file-utils` `0.28-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `device-mapper` `2.03.43-2`
  SPDX (pacman): `GPL-2.0-only`, `LGPL-2.1-only`

- [V] `diffutils` `3.12-2`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `double-conversion` `3.4.0-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `duktape` `2.7.0-7`
  SPDX (pacman): `MIT`

- [V] `e2fsprogs` `1.47.4-1`
  SPDX (pacman): `GPL`, `LGPL`, `MIT`

- [V] `efibootmgr` `18-4`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `efivar` `39-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `elfutils` `0.197-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `expat` `2.9.0-1`
  SPDX (pacman): `MIT`

- [V] `fakeroot` `1:1.37.2-3`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `file` `5.48-1`
  SPDX (pacman): `BSD-2-Clause-Darwin`

- [V] `filesystem` `2025.10.12-1`
  SPDX (pacman): `0BSD`

- [V] `findutils` `4.11.0-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `fontconfig` `2:2.18.3-2`
  SPDX (pacman): `HPND AND Unicode-DFS-2016`

- [V] `freetype2` `2.15.0-1`
  SPDX (pacman): `FTL OR GPL-2.0-or-later`

- [V] `fribidi` `1.0.17-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `fuse-common` `3.18.3-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `fuse3` `3.18.3-1`
  SPDX (pacman): `GPL-2.0-only`, `LGPL-2.1-only`

- [V] `gawk` `5.4.1-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `gcc-libs` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `gcr` `3.41.2-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gcr-4` `4.4.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gdbm` `1.26-2`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `gdk-pixbuf2` `2.44.8-1`
  SPDX (pacman): `LGPL-2.0-or-later`

- [V] `gettext` `1.0-2`
  SPDX (pacman): `GFDL-1.2-only`, `GPL-2.0-only`, `GPL-2.0-or-later`,
  `LGPL-2.0-only`

- [V] `giflib` `6.1.3-2`
  SPDX (pacman): `MIT`

- [V] `git` `2.56.0-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `glib-networking` `1:2.90.0-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `glib2` `2.90.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `glibc` `2.44+r50+g1848099f063e-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.1-or-later`

- [V] `glslang` `1:1.4.363.0-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `glycin` `2.2.3-1`
  SPDX (pacman): `MPL-2.0 OR LGPL-2.1-or-later`

- [V] `gmp` `6.3.0-3`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-3.0-or-later`

- [V] `gnome-keyring` `1:51.1-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.1-or-later`

- [V] `gnulib-l10n` `20241231-1`
  SPDX (pacman): `LGPL-2.0-or-later`

- [V] `gnupg` `2.4.9-3`
  SPDX (pacman): `BSD-2-Clause`, `BSD-3-Clause`, `BSD-4-Clause`, `CC0-1.0`,
  `GPL-2.0-or-later`, `GPL-3.0-or-later`, `LGPL-2.1-or-later`,
  `LGPL-3.0-or-later OR GPL-2.0-or-later`, `MIT`, `Unicode-TOU`

- [V] `gnutls` `3.8.13-3`
  SPDX (pacman): `GPL-3.0-or-later AND LGPL-2.1-or-later`

- [V] `gperftools` `2.19.1-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `gpgme` `2.2.0-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.0-or-later`, `LGPL-2.1-or-later`,
  `MIT`

- [V] `graphene` `1.10.8-2`
  SPDX (pacman): `MIT`

- [V] `graphite` `1:1.3.15-1`
  SPDX (pacman): `LGPL-2.1-or-later OR MPL-2.0 OR GPL-2.0-or-later`

- [V] `grep` `3.12-2`
  SPDX (pacman): `GPL3`

- [V] `gsettings-desktop-schemas` `51.0-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gsettings-system-schemas` `51.0-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gst-plugins-base-libs` `1.28.8-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gstreamer` `1.28.8-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gtest` `1.18.0-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `gtk-update-icon-cache` `1:4.24.1-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gtk3` `1:3.24.52-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `gum` `2.0.2-1`
  SPDX (pacman): `MIT`

- [V] `gzip` `1.15-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `harfbuzz` `14.6.0-1`
  SPDX (pacman): `MIT`

- [V] `hicolor-icon-theme` `0.18-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `hidapi` `0.15.0-1`
  SPDX (pacman): `GPL3`, `BSD`, `custom`

- [V] `highway` `1.4.0-1`
  SPDX (pacman): `Apache-2.0 OR BSD-3-Clause`

- [V] `hwdata` `0.412-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `hyprcursor` `0.1.13-7`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprgraphics` `0.5.1-4`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprland` `0.56.2-4`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprland-guiutils` `0.2.2-4`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprlang` `0.6.8-5`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprtoolkit` `0.6.0-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprutils` `0.14.2-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `hyprwire` `0.3.1-3`
  SPDX (pacman): `BSD-3-Clause`

- [V] `iana-etc` `20260617-1`
  SPDX (pacman): `custom:none`

- [V] `icu` `78.3-1`
  SPDX (pacman): `LicenseRef-Unicode-3.0`, `BSD-2-Clause`, `BSD-3-Clause`,
  `NAIST-2003`

- [V] `iniparser` `4.3.2-1`
  SPDX (pacman): `MIT`

- [V] `iso-codes` `4.20.1-1`
  SPDX (pacman): `LGPL-2.1-only`

- [V] `jansson` `2.15.1-1`
  SPDX (pacman): `MIT`

- [V] `jbigkit` `2.2-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `jemalloc` `1:5.4.0-1`
  SPDX (pacman): `BSD-2-Clause`

- [V] `jq` `1.8.2-1`
  SPDX (pacman): `MIT`

- [V] `json-c` `0.19-1`
  SPDX (pacman): `MIT`

- [V] `json-glib` `1.10.8-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `kbd` `2.10.0-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `keyutils` `1.6.3-4`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.1-or-later`

- [V] `kmod` `34.2-1`
  SPDX (pacman): `LGPL-2.1-or-later`, `GPL-2.0-or-later`

- [V] `krb5` `1.22.2-1`
  SPDX (pacman): `custom`

- [V] `lcms2` `2.19.1-1`
  SPDX (pacman): `MIT`

- [V] `leancrypto` `1.9.1-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LicenseRef-BSDvariant`,
  `LicenseRef-leancrypto`

- [V] `libarchive` `3.8.10-1`
  SPDX (pacman): `BSD-2-Clause`, `BSD-4-Clause-UC`, `Apache-2.0 OR CC0-1.0 OR
  OpenSSL`

- [V] `libasan` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libassuan` `3.0.0-1`
  SPDX (pacman): `FSFULLR`, `GPL-2.0-or-later`, `LGPL-2.1-or-later`

- [V] `libatomic` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libb2` `0.98.1-3`
  SPDX (pacman): `CC0-1.0`

- [V] `libcap` `2.78-1`
  SPDX (pacman): `BSD-3-Clause OR GPL-2.0-only`

- [V] `libcap-ng` `0.9.6-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-2.1-or-later`

- [V] `libcloudproviders` `0.4.1-1`
  SPDX (pacman): `LGPL-3.0-or-later`

- [V] `libcolord` `1.4.8-2`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `libcups` `2:2.4.20-1`
  SPDX (pacman): `Apache-2.0 WITH LLVM-exception AND BSD-3-Clause AND Zlib AND
  BSD-2-Clause`

- [V] `libdaemon` `0.14-6`
  SPDX (pacman): `LGPL`

- [V] `libdatrie` `0.2.14-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libdecor` `0.2.5-1`
  SPDX (pacman): `MIT`

- [V] `libdeflate` `1.26-1`
  SPDX (pacman): `MIT`

- [V] `libdisplay-info` `0.3.0-1`
  SPDX (pacman): `MIT`

- [V] `libdrm` `2.4.134-1`
  SPDX (pacman): `MIT`

- [V] `libdwarf` `1:2.3.3-1`
  SPDX (pacman): `LGPL-2.1-only`, `GPL-2.0-only`, `BSD-2-Clause`,
  `BSD-3-Clause`, `LicenseRef-libdwarf-public-domain`

- [V] `libedit` `20260512_3.1-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libei` `1.6.0-2`
  SPDX (pacman): `MIT`

- [V] `libelf` `0.197-1`
  SPDX (pacman): `GPL-2.0-or-later OR LGPL-3.0-or-later`

- [V] `libepoxy` `1.5.10-3`
  SPDX (pacman): `MIT`

- [V] `libevdev` `1.14.0-1`
  SPDX (pacman): `MIT`

- [V] `libevent` `2.1.13-2`
  SPDX (pacman): `BSD-3-Clause-Modification`

- [V] `libffi` `3.8.0-1`
  SPDX (pacman): `MIT`

- [V] `libfontenc` `1.1.9-1`
  SPDX (pacman): `MIT`

- [V] `libgcc` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libgcrypt` `1.12.4-1`
  SPDX (pacman): `BSD-3-Clause`, `BSD-3-Clause OR GPL-2.0-only`,
  `GPL-2.0-or-later`, `LGPL-2.0-or-later`, `LGPL-2.1-or-later`, `X11`,
  `LicenseRef-scancode-public-domain`, `LicenseRef-OCB1`

- [V] `libgfortran` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libglvnd` `1.7.0-3`
  SPDX (pacman): `custom:BSD-like`

- [V] `libgomp` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libgpg-error` `1.61-1`
  SPDX (pacman): `LGPL-2.1-or-later`, `BSD-3-Clause OR LGPL-2.1-or-later`,
  `FSFULLR`, `GPL-2.0-or-later`

- [V] `libgudev` `238-4`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libhwasan` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libice` `1.1.2-1`
  SPDX (pacman): `MIT-open-group`

- [V] `libidn2` `2.3.8-1`
  SPDX (pacman): `GPL2`, `LGPL3`

- [V] `libimobiledevice` `1.4.0-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libimobiledevice-glue` `1.3.2-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libinih` `62-2`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libinput` `1.32.0-1`
  SPDX (pacman): `MIT`

- [V] `libisl` `0.28-1`
  SPDX (pacman): `MIT`

- [V] `libjpeg-turbo` `3.2.0-2`
  SPDX (pacman): `BSD-3-Clause`, `IJG`

- [V] `libjxl` `0.12.0-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libksba` `1.8.1-1`
  SPDX (pacman): `GPL-2.0-only`, `GPL-3.0-only`, `LGPL-3.0-only`

- [V] `libldap` `2.7.1-1`
  SPDX (pacman): `custom`

- [V] `liblsan` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libmakepkg-dropins` `20-2`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `libmpc` `1.4.1-1`
  SPDX (pacman): `LGPL-3.0-only`

- [V] `libnghttp2` `1.70.0-1`
  SPDX (pacman): `MIT`

- [V] `libnghttp3` `1.18.0-1`
  SPDX (pacman): `MIT`

- [V] `libngtcp2` `1.25.0-1`
  SPDX (pacman): `MIT`

- [V] `libnotify` `0.8.9-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libnsl` `2.0.1-2`
  SPDX (pacman): `LGPL-2.1-only`

- [V] `libobjc` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libp11-kit` `0.26.5-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libpciaccess` `0.19-1`
  SPDX (pacman): `LicenseRef-libpciaccess`

- [V] `libpipewire` `1:1.6.9-1`
  SPDX (pacman): `MIT`

- [V] `libplist` `2.7.0-3`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libpng` `1.6.59-1`
  SPDX (pacman): `libpng-2.0`

- [V] `libproxy` `0.5.12-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libpsl` `0.21.5-2`
  SPDX (pacman): `MIT`

- [V] `libquadmath` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `librsvg` `2:2.63.3-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libsasl` `2.1.28-5`
  SPDX (pacman): `BSD-3-Clause-Attribution`

- [V] `libseccomp` `2.6.0-1`
  SPDX (pacman): `LGPL-2.1-only`

- [V] `libsecret` `0.21.8.2-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libsm` `1.2.6-1`
  SPDX (pacman): `MIT`, `MIT-open-group`

- [V] `libsoup3` `3.8.0-1`
  SPDX (pacman): `LGPL-2.0-or-later`

- [V] `libssh2` `1.11.1-7`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libstdc++` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libstemmer` `3.1.1-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libsysprof-capture` `51.0-1`
  SPDX (pacman): `BSD-2-Clause-Patent`

- [V] `libtasn1` `4.21.0-1`
  SPDX (pacman): `GPL-3.0-or-later`, `LGPL-2.1-or-later`, `GFDL-1.3-or-later`

- [V] `libtatsu` `1.0.5-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libthai` `0.1.30-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libtiff` `4.7.2-2`
  SPDX (pacman): `libtiff`

- [V] `libtirpc` `1.3.8-1`
  SPDX (pacman): `SISSL`, `BSD-3-Clause`

- [V] `libtsan` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libubsan` `16.2.1+r23+gd564253eb6c8-1`
  SPDX (pacman): `GPL-3.0-or-later WITH GCC-exception-3.1`, `GFDL-1.3-or-later`

- [V] `libunistring` `1.4.2-1`
  SPDX (pacman): `GPL-2.0-or-later`, `LGPL-3.0-or-later`

- [V] `libunwind` `1.8.3-1`
  SPDX (pacman): `MIT`

- [V] `liburing` `2.15-1`
  SPDX (pacman): `GPL-2.0-only WITH Linux-syscall-note OR MIT`,
  `LGPL-2.0-or-later`, `MIT`

- [V] `libusb` `1.0.30-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `libusbmuxd` `2.1.1-2`
  SPDX (pacman): `GPL-2.0-or-later AND LGPL-2.1-or-later`

- [V] `libverto` `0.3.2-6`
  SPDX (pacman): `MIT`

- [V] `libwacom` `2.20.0-1`
  SPDX (pacman): `MIT`

- [V] `libwebp` `1.6.0-2`
  SPDX (pacman): `BSD-3-Clause`

- [V] `libwireplumber` `0.5.18-1`
  SPDX (pacman): `MIT`

- [V] `libx11` `1.8.14-1`
  SPDX (pacman): `MIT AND X11`

- [V] `libxau` `1.0.12-1`
  SPDX (pacman): `MIT-open-group`

- [V] `libxcb` `1.17.0-1`
  SPDX (pacman): `X11`

- [V] `libxcomposite` `0.4.7-1`
  SPDX (pacman): `MIT`, `HPND-sell-variant`

- [V] `libxcrypt` `4.5.2-1`
  SPDX (pacman): `LGPL`

- [V] `libxcursor` `1.2.3-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxcvt` `0.1.3-1`
  SPDX (pacman): `MIT`, `HPND-sell-variant`

- [V] `libxdamage` `1.1.7-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxdmcp` `1.1.5-2`
  SPDX (pacman): `MIT-open-group`

- [V] `libxext` `1.3.7-1`
  SPDX (pacman): `LicenseRef-libxext`

- [V] `libxfixes` `6.0.2-1`
  SPDX (pacman): `MIT`, `HPND-sell-variant`

- [V] `libxfont2` `2.0.9-1`
  SPDX (pacman): `BSD-2-Clause`, `BSD-4-Clause-UC`, `HPND-sell-variant`,
  `MIT-open-group`, `SMLNJ`, `X11`

- [V] `libxft` `2.3.9-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxi` `1.8.4-1`
  SPDX (pacman): `MIT-open-group`, `SMLNJ`, `MIT`

- [V] `libxinerama` `1.1.6-1`
  SPDX (pacman): `MIT`, `MIT-open-group`, `X11`

- [V] `libxkbcommon` `1.13.2-1`
  SPDX (pacman): `MIT`

- [V] `libxkbcommon-x11` `1.13.2-1`
  SPDX (pacman): `MIT`

- [V] `libxkbfile` `1.2.0-1`
  SPDX (pacman): `LicenseRef-libxkbfile`

- [V] `libxml2` `2.15.4-1`
  SPDX (pacman): `MIT`

- [V] `libxmu` `1.3.1-1`
  SPDX (pacman): `MIT-open-group AND SMLNJ AND X11 AND ISC`

- [V] `libxrandr` `1.5.5-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxrender` `0.9.13-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxshmfence` `1.3.3-1`
  SPDX (pacman): `HPND-sell-variant`

- [V] `libxt` `1.3.1-1`
  SPDX (pacman): `MIT`, `HPND-sell-variant`, `SMLNJ`, `MIT-open-group`, `X11`

- [V] `libxtst` `1.2.6-1`
  SPDX (pacman): `MIT-open-group`, `HPND-sell-variant`, `X11`, `HPND-doc`,
  `HPND-doc-sell`

- [V] `libxv` `1.0.13-1`
  SPDX (pacman): `SMLNJ`, `HPND-sell-variant`

- [V] `libxxf86vm` `1.1.7-1`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `libzip` `1.11.4-1`
  SPDX (pacman): `BSD`

- [V] `limine` `12.9.4-1`
  SPDX (pacman): `BSD-2-Clause`

- [V] `limine-mkinitcpio-hook` `1.40.0-2`
  SPDX (pacman): `GPL3`

- [V] `limine-snapper-sync` `1.32.1-2`
  SPDX (pacman): `GPL3`

- [V] `linux-api-headers` `7.3-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `llvm-libs` `23.1.3-4`
  SPDX (pacman): `Apache-2.0 WITH LLVM-exception`

- [V] `lm_sensors` `1:3.6.2-1`
  SPDX (pacman): `GPL-2.0-only OR LGPL-2.1-only`

- [V] `lmdb` `0.9.35-1`
  SPDX (pacman): `custom:OpenLDAP`

- [V] `lua` `5.5.1-1`
  SPDX (pacman): `MIT`

- [V] `lua54` `5.4.9-1`
  SPDX (pacman): `MIT`

- [V] `lz4` `1:1.10.0-2`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `lzo` `2.10-5`
  SPDX (pacman): `GPL`

- [V] `mbedtls3` `3.6.7-1`
  SPDX (pacman): `Apache-2.0`

- [V] `md4c` `0.6.0-2`
  SPDX (pacman): `MIT`

- [V] `mesa` `1:26.2.5-1`
  SPDX (pacman): `MIT AND BSD-3-Clause AND SGI-B-2.0`

- [V] `mkinitcpio` `42.2-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `mkinitcpio-busybox` `1.36.1-1`
  SPDX (pacman): `GPL`

- [V] `mpdecimal` `4.0.1-3`
  SPDX (pacman): `BSD-2-Clause`

- [V] `mpfr` `4.2.2-1`
  SPDX (pacman): `GPL-3.0-or-later`, `LGPL-3.0-or-later`

- [V] `mtdev` `1.1.7-1`
  SPDX (pacman): `MIT`

- [V] `muparser` `2.3.5-2`
  SPDX (pacman): `BSD-2-Clause`

- [V] `ncurses` `6.6-2`
  SPDX (pacman): `MIT-open-group`

- [V] `nettle` `4.0-1`
  SPDX (pacman): `LGPL-3.0-or-later OR GPL-2.0-or-later`

- [V] `noto-fonts` `1:2026.10.01-1`
  SPDX (pacman): `OFL-1.1-no-RFN`

- [V] `npth` `1.8-1`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `numactl` `2.0.19-1`
  SPDX (pacman): `GPL-2.0-only`, `LGPL-2.1-only`

- [V] `omarchy-keyring` `20251027-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `omarchy-settings` `4.5.0-3`
  SPDX (pacman): `MIT`

- [V] `omarchy-speedtest` `0.2.1-1`
  SPDX (pacman): `MIT`

- [V] `omarchy-themes-intros` `2026.10.14-1`
  SPDX (pacman): `MIT`

- [V] `oniguruma` `6.9.10-3`
  SPDX (pacman): `BSD-2-Clause`

- [V] `openssh` `10.6p1-2`
  SPDX (pacman): `0BSD`, `BSD-2-Clause`, `BSD-3-Clause`, `ISC`,
  `LicenseRef-Public-Domain`, `MIT`

- [V] `openssl` `3.6.5-1`
  SPDX (pacman): `Apache-2.0`

- [V] `orc` `0.4.44-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `p11-kit` `0.26.5-1`
  SPDX (pacman): `BSD-3-Clause`

- [V] `pacman` `7.1.0.r9.g54d9411-3`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `pacman-contrib` `1.13.1-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `pacman-mirrorlist` `20260610-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `pam` `1.7.3-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `pambase` `20260616-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `pango` `1:1.58.2-1`
  SPDX (pacman): `LGPL-2.0-or-later`

- [V] `pcre2` `10.49-1`
  SPDX (pacman): `BSD-2-Clause`, `BSD-3-Clause WITH PCRE2-exception`

- [V] `perl` `5.44.0-1`
  SPDX (pacman): `Artistic-1.0-Perl`, `GPL-1.0-or-later`

- [V] `perl-error` `0.17030-3`
  SPDX (pacman): `PerlArtistic`, `GPL`

- [V] `perl-mailtools` `2.22-3`
  SPDX (pacman): `PerlArtistic`, `GPL`

- [V] `perl-timedate` `2.35-1`
  SPDX (pacman): `PerlArtistic`

- [V] `pinentry` `1.3.3-1`
  SPDX (pacman): `GPL`

- [V] `pipewire` `1:1.6.9-1`
  SPDX (pacman): `MIT`, `LGPL-2.1-or-later`

- [V] `pixman` `0.46.4-1`
  SPDX (pacman): `MIT`

- [V] `plymouth` `26.134.222-3`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `popt` `1.19-2`
  SPDX (pacman): `custom`

- [V] `pugixml` `1.16-1`
  SPDX (pacman): `MIT`

- [V] `python-dbus` `1.5.0-1`
  SPDX (pacman): `MIT`

- [V] `python-pyxdg` `0.28-8`
  SPDX (pacman): `LGPL-2.0-only`

- [V] `qt6-declarative` `6.12.0-2`
  SPDX (pacman): `GPL-3.0-only`, `LGPL-3.0-only`, `LicenseRef-Qt-Commercial`,
  `Qt-GPL-exception-1.0`

- [V] `qt6-svg` `6.12.0-1`
  SPDX (pacman): `GPL-3.0-only`, `LGPL-3.0-only`, `LicenseRef-Qt-Commercial`,
  `Qt-GPL-exception-1.0`

- [V] `qt6-translations` `6.12.0-1`
  SPDX (pacman): `GPL-3.0-only`, `LGPL-3.0-only`, `LicenseRef-Qt-Commercial`,
  `Qt-GPL-exception-1.0`

- [V] `qt6-wayland` `6.12.0-1`
  SPDX (pacman): `GPL-3.0-only`, `LGPL-3.0-only`, `LicenseRef-Qt-Commercial`,
  `Qt-GPL-exception-1.0`

- [V] `re2` `2:2025.11.05-6`
  SPDX (pacman): `BSD-3-Clause`

- [V] `readline` `8.3.6-1`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `sdbus-cpp` `2.3.1-1`
  SPDX (pacman): `LGPL-2.1-only`, `LicenseRef-sdbus-c++-LGPL-Exception-1.0`

- [V] `sddm` `0.21.0-7`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `seatd` `0.9.3-1`
  SPDX (pacman): `MIT`

- [V] `sed` `4.10-2`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `shadow` `4.20.0.arch1-1`
  SPDX (pacman): `0BSD`, `BSD-3-Clause`

- [V] `shared-mime-info` `2.5.1-2`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `snapper` `0.13.2-1`
  SPDX (pacman): `GPL-2.0-only`

- [V] `spirv-tools` `1:1.4.363.0-1`
  SPDX (pacman): `Apache-2.0`

- [V] `sqlite` `3.54.0-1`
  SPDX (pacman): `LicenseRef-Sqlite`

- [V] `sudo` `1.9.17.p2-6`
  SPDX (pacman): `custom`

- [V] `tar` `1.35-5`
  SPDX (pacman): `GPL-3.0-or-later`

- [V] `tinysparql` `3.12.0-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `tomlplusplus` `3.4.0-2`
  SPDX (pacman): `MIT`

- [V] `tpm2-tss` `4.2.0-2`
  SPDX (pacman): `BSD-2-Clause`

- [V] `tslib` `1.24-1`
  SPDX (pacman): `LGPL-2.1-only`

- [V] `ttf-jetbrains-mono-nerd-basic` `3.5.1-2`
  SPDX (pacman): `OFL-1.1-no-RFN`

- [V] `ttf-liberation` `2.1.5-2`
  SPDX (pacman): `custom:OFL`

- [V] `tzdata` `2026e-1`
  SPDX (pacman): `LicenseRef-tz`

- [V] `upower` `1.91.5-1`
  SPDX (pacman): `GPL-2.0-or-later`

- [V] `util-linux` `2.42.4-1`
  SPDX (pacman): `BSD-2-Clause`, `BSD-3-Clause`, `BSD-4-Clause-UC`,
  `GPL-2.0-only`, `GPL-2.0-or-later`, `GPL-3.0-or-later`, `ISC`,
  `LGPL-2.1-or-later`, `LicenseRef-PublicDomain`

- [V] `util-linux-libs` `2.42.4-1`
  SPDX (pacman): `BSD-2-Clause`, `BSD-3-Clause`, `BSD-4-Clause-UC`,
  `GPL-2.0-only`, `GPL-2.0-or-later`, `GPL-3.0-or-later`, `ISC`,
  `LGPL-2.1-or-later`, `LicenseRef-PublicDomain`

- [V] `uwsm` `0.27.1-1`
  SPDX (pacman): `MIT`

- [V] `wayland` `1.26.0-1`
  SPDX (pacman): `MIT`

- [V] `wayland-protocols` `1.49-1`
  SPDX (pacman): `MIT`

- [V] `wireplumber` `0.5.18-1`
  SPDX (pacman): `MIT`

- [V] `xcb-proto` `1.17.0-4`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `xcb-util` `0.4.1-2`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `xcb-util-cursor` `0.1.6-1`
  SPDX (pacman): `MIT`

- [V] `xcb-util-errors` `1.0.1-2`
  SPDX (pacman): `MIT`

- [V] `xcb-util-image` `0.4.1-3`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `xcb-util-keysyms` `0.4.1-5`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `xcb-util-renderutil` `0.3.10-2`
  SPDX (pacman): `X11-distribute-modifications-variant`, `HPND-sell-variant`

- [V] `xcb-util-wm` `0.4.2-2`
  SPDX (pacman): `X11-distribute-modifications-variant`

- [V] `xdg-desktop-portal` `1.22.1-2`
  SPDX (pacman): `LGPL-2.1-or-later`

- [V] `xdg-desktop-portal-hyprland` `1.4.1-2`
  SPDX (pacman): `MIT`

- [V] `xdg-utils` `1.2.1-2`
  SPDX (pacman): `MIT`

- [V] `xf86-input-libinput` `1.5.0-1`
  SPDX (pacman): `MIT`

- [V] `xkeyboard-config` `2.48-1`
  SPDX (pacman): `LicenseRef-xkeyboard-config`

- [V] `xorg-fonts-encodings` `1.1.0-2`
  SPDX (pacman): `LicenseRef-xorg-fonts-encodings`

- [V] `xorg-server` `21.1.25-2`
  SPDX (pacman): `LicenseRef-Adobe-Display-PostScript`, `BSD-3-Clause`,
  `LicenseRef-DEC-3-Clause`, `HPND`,
  `LicenseRef-HPND-sell-MIT-disclaimer-xserver`, `HPND-sell-variant`, `ICU`,
  `ISC`, `MIT`, `MIT-open-group`, `NTP`, `SGI-B-2.0`, `SMLNJ`, `X11`,
  `X11-distribute-modifications-variant`

- [V] `xorg-server-common` `21.1.25-2`
  SPDX (pacman): `LicenseRef-Adobe-Display-PostScript`, `BSD-3-Clause`,
  `LicenseRef-DEC-3-Clause`, `HPND`,
  `LicenseRef-HPND-sell-MIT-disclaimer-xserver`, `HPND-sell-variant`, `ICU`,
  `ISC`, `MIT`, `MIT-open-group`, `NTP`, `SGI-B-2.0`, `SMLNJ`, `X11`,
  `X11-distribute-modifications-variant`

- [V] `xorg-setxkbmap` `1.3.5-1`
  SPDX (pacman): `HPND`

- [V] `xorg-xauth` `1.1.5-1`
  SPDX (pacman): `MIT-open-group`

- [V] `xorg-xkbcomp` `1.5.0-1`
  SPDX (pacman): `LicenseRef-xkbcomp`

- [V] `xorg-xprop` `1.2.8-1`
  SPDX (pacman): `MIT-open-group`

- [V] `xorg-xwayland` `24.1.14-1`
  SPDX (pacman): `LicenseRef-Adobe-Display-PostScript`, `BSD-3-Clause`,
  `LicenseRef-DEC-3-Clause`, `HPND`,
  `LicenseRef-HPND-sell-MIT-disclaimer-xserver`, `HPND-sell-variant`, `ICU`,
  `ISC`, `MIT`, `MIT-open-group`, `NTP`, `SGI-B-2.0`, `SMLNJ`, `X11`,
  `X11-distribute-modifications-variant`

- [V] `xorgproto` `2026.1-1`
  SPDX (pacman): `BSD-2-Clause`, `HPND`, `HPND-sell-variant`, `ICU`, `MIT`,
  `MIT-open-group`, `SGI-B-2.0`, `SMLNJ`, `X11`,
  `X11-distribute-modifications-variant`

- [V] `xz` `5.8.4-1`
  SPDX (pacman): `GPL-2.0-or-later AND 0BSD AND LicenseRef-Public-Domain AND
  LGPL-2.1-or-later`

- [V] `zlib` `1:1.3.2-4`
  SPDX (pacman): `Zlib`

- [V] `zlib-ng` `2.3.3-1`
  SPDX (pacman): `Zlib`

- [V] `zstd` `1.5.7-3`
  SPDX (pacman): `BSD-3-Clause`, `GPL-2.0-only`

## Not included in the dependency closure

- [NV] `coolercontrol`: this AUR package is not installed,
  `pacman -Qi coolercontrol` found no local package, and
  `/usr/share/licenses/coolercontrol/` is absent. No license is
  asserted here.
