# Fan control research: MSI B760 GAMING PLUS WIFI (MS-7D98)

Research date: 2026-10-26. Machine facts below are local, read-only observations. No hardware probing, module loading, bus scanning, or system writes were performed.

## Evidence labels

- **[V] Verified:** directly stated in a cited primary source or observed locally.
- **[I] Inference:** conclusion from the available evidence, not a verified fact for this exact board.
- **[NV] Not verified:** evidence is missing or the claim cannot be safely established without hardware probing.

## 1. Super I/O identification

- **[V]** MSI's product specification/manual materials identify the board's Super I/O as a Nuvoton NCT6687 (some software and drivers identify the family/variant as NCT6687D or NCT6687D-R). The NCT6687D silicon is supported by the Linux `nct6683` driver; the Linux driver documentation lists MSI B550, X670-P, and X870E systems using NCT6687D firmware. [MSI B760 product specification](https://storage-asset.msi.com/specSheet/es/mb/B760%20GAMING%20PLUS%20WIFI.pdf), [Linux nct6683 documentation](https://cdn.kernel.org/doc/html/latest/hwmon/nct6683.html)
- **[V]** LibreHardwareMonitor's upstream release history describes adding support for MSI X870/Z890 boards using NCT6687D and its source lineage describes Super I/O detection. Fred78290's module README explicitly says its implementation was reverse-coded from LibreHardwareMonitor Windows code. These support the NCT6687 family identification, but are not a board-specific Linux probe. [LibreHardwareMonitor releases](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases), [Fred78290/nct6687d README](https://github.com/Fred78290/nct6687d)
- **[V]** The kernel documentation names NCT6683D/NCT6686D/NCT6687D under the single `nct6683` hwmon driver. It says non-Intel vendor boards require `force=1`; this is a vendor gate, not a way to select the chip variant. [Kernel documentation](https://cdn.kernel.org/doc/html/latest/hwmon/nct6683.html)
- **[NV]** The exact chip/firmware revision installed in this particular machine has not been read from hardware. The model's published specification is the evidence used here; no Super I/O access was attempted.

## 2. Driver options and local inspection

### In-tree `nct6683`

- **[V]** On this host `uname -r` returned `7.2.8-9-omarchy`. `modinfo nct6683` found `/lib/modules/7.2.8-9-omarchy/kernel/drivers/hwmon/nct6683.ko.zst`, marked `intree: Y`, GPL, with `force:Set to one to enable support for unknown vendors (bool)`. `lsmod` showed no loaded `nct6683` or `nct6687` module. The platform-device directory contained no names matching `nct`, `668`, `wmi`, `ec`, or `hwmon`. The observed hwmon inventory was the one stated in the request; it had no motherboard fan/PWM channels.
- **[V]** The kernel driver added NCT6687D chip support for Linux 5.11. Subsequent customer-ID whitelist additions are separate changes; for example, an additional MSI ID was added in a 2025 upstream change. Thus kernel age alone does not prove a particular MSI firmware ID is recognized. [NCT6687D support change](https://git.evolution-x.org/anierin/msm-5.15/commit/daf4fedde6177941b55ba3c3293a8585d5280b94), [MSI customer-ID change](https://git.zx2c4.com/wireguard-linux/commit/Documentation/hwmon?id=a045a189f425e073ea5d6427ee66252eb990ed92)
- **[V]** The installed module exposes `force`. For an MSI board, `force=1` is the documented path to instantiate on a non-Intel vendor. A module parameter does not guarantee that a specific firmware/revision will be supported or that channels will appear. `modinfo -p nct6683` locally confirmed only that parameter; no module was loaded.
- **[V]** The in-tree driver reports up to 16 fan tachometers and 8 PWM-capable channels in its generic description. However, its documented fan-control support for MSI NCT6687D-R is currently not present in the published kernel documentation. A proposed upstream patch dated 2026-10-04 adds writable fan control specifically for MSI NCT6687D-R customer ID `0x20d`; it maps CPU/pump to `pwm1`/`pwm2` and system headers to `pwm11`–`pwm16`, where present. The patch defines `pwmN_enable=1` manual and `=2` BIOS automatic, with `pwmN` writable only in manual mode. **[I]** As this is only a patch submission and not established as merged/released by the evidence reviewed, do not assume kernel `7.2.8-9-omarchy` implements this MSI write support. [Kernel driver documentation](https://cdn.kernel.org/doc/html/latest/hwmon/nct6683.html), [patch submission and channel details](https://lists.openwall.net/linux-kernel/2026/10/04/632)
- **[V]** The current driver source recognizes several MSI customer IDs, including `0x20d`; driver recognition/sensor reporting is distinct from writable PWM support. **[NV]** Without probing, the B760's reported customer ID and its mapping to an exact compatible driver path cannot be checked.

### Out-of-tree `nct6687d`

- **[V]** Fred78290's `nct6687d` is a separate external kernel module for NCT6687-R. Its upstream repository provides DKMS and manual build/install instructions and reports GPL-2.0. It is reverse-engineered, not an in-tree Linux driver. [Upstream repository and README](https://github.com/Fred78290/nct6687d)
- **[V]** The project is actively used/maintained in the sense that its GitHub repository has ongoing commits/issues and downstream CoolerControl package work exists; its README and issue tracker also show compatibility reports can be board/kernel-specific. The Arch package is commonly distributed as `nct6687d-dkms-git` via AUR, not as part of the kernel. [AUR package reference in CoolerControl packaging project](https://gitlab.com/coolercontrol/nct6687d-packages), [upstream issues](https://github.com/Fred78290/nct6687d/issues)
- **[I]** DKMS adds a third-party kernel module that must be rebuilt and trusted across kernel upgrades; reverse-engineered register access carries more compatibility risk than a tested in-tree driver. It may claim legacy Super I/O resources or expose writable controls whose behavior varies by firmware. A successful build/load is not proof of safe control on this B760.
- **[NV]** No evidence reviewed establishes that the external module is safer or more compatible on this exact MS-7D98 than the installed in-tree driver. Do not install both drivers or load both for the same chip.

## 3. ACPI resource conflict

- **[V]** The local `/proc/cmdline` contains no `acpi_enforce_resources=` setting. The kernel default is `strict`, which blocks legacy driver access to I/O regions claimed by ACPI. **[I]** In the absence of an overriding setting, this machine is therefore using the default strict policy. [Kernel parameter documentation](https://docs.kernel.org/7.2/admin-guide/kernel-parameters.html)
- **[V]** The in-tree driver's Super I/O access path requests the I/O region and checks resource ownership before accessing it; when the ACPI resource policy rejects the access, initialization may fail with a resource conflict rather than safely bypassing ACPI. [Linux `nct6683.c`](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6683.c)
- **[I]** `acpi_enforce_resources=lax` or `no` relaxes protections against legacy access to ACPI-reserved resources; this is a system-wide kernel boot-policy change and is not recommended as a first step. It can permit concurrent ACPI/driver access and undefined behavior. `force=1` is not the same setting and should not be treated as an ACPI-conflict fix.
- **[NV]** The specific ACPI resource ownership/conflict state on this machine cannot be determined from the read-only facts collected; no driver was loaded and no resource claim was challenged. Do not change `acpi_enforce_resources` to make a driver load without first identifying the exact conflict and understanding the system-wide effect.

## 4. CoolerControl behavior and thermal risks

- **[V]** CoolerControl reads Linux interfaces such as `hwmon`; it does not ship motherboard drivers or talk to the Super I/O directly. It displays fans exposed by hwmon, including read-only channels. Without a matching loaded driver and hwmon nodes, it cannot control these motherboard fans. [CoolerControl hardware support](https://docs.coolercontrol.org/hardware-support.html)
- **[V]** The in-tree driver's normal NCT6687D sensor exposure should be considered monitoring-only unless the running module actually provides writable `pwmN`/`pwmN_enable` files. The proposed MSI-specific kernel patch describes manual/automatic semantics, but is not evidence that this host's driver has them.
- **[V]** With hwmon controls, manual mode (`pwmN_enable=1`) hands the duty to software; `pwmN` is generally 0–255, with low settings reducing airflow. `pwmN_enable=2` is documented as automatic mode for hardware that implements it. CoolerControl's “Unmanaged” action returns a hwmon fan to the driver's automatic/BIOS behavior where that mode exists; some drivers instead leave the last duty set. [Kernel hwmon sysfs documentation](https://github.com/torvalds/linux/blob/master/Documentation/hwmon/sysfs-interface.rst), [CoolerControl FAQ](https://docs.coolercontrol.org/reference/faq)
- **[I]** If manual control is enabled and the service, application, kernel, or driver fails before restoring automatic mode, a fan can remain at a low fixed duty. This creates overheating risk, especially for CPU/pump headers. Configure and verify a BIOS fan curve first; test with conservative high airflow, monitor temperatures, and confirm automatic mode is restored before relying on software curves. Avoid writing `pwmN_enable` or `pwmN` until the actual exposed channels and semantics are confirmed for this hardware.
- **[NV]** Whether unloading either driver restores the B760's firmware fan curve is not established. A driver unload, shutdown, or service exit is not a substitute for explicitly returning each channel to automatic mode when supported. Firmware/BIOS curves are the reliable fallback.

## 5. Recommendation and user-run steps

**Recommendation [I]:** least invasive and safest is to keep fan curves in BIOS and leave motherboard fan control there. If board fan telemetry in Linux is desired, first try the already-installed in-tree module with `force=1`, with no PWM writes and no ACPI-policy changes. Given the requested safety priority and uncertain current MSI write support, do not install `nct6687d` or use CoolerControl manual curves yet. If `nct6683` creates no device under the default ACPI policy, stop; do not switch ACPI enforcement to `lax/no` merely to force it.

Suggested steps for the user (commands below are instructions, not commands run during this research):

1. In BIOS Hardware Monitor, ensure a sensible CPU, pump, and system-fan curve is saved. Confirm fans spin and temperatures are normal before experimenting.
2. Check for an ACPI/resource error and the driver's current status without changing settings:

   ```sh
   journalctl -k -b | grep -Ei 'nct6683|acpi|resource|hwmon'
   ```

3. If the log shows no known conflict, load only the in-tree driver for a temporary, read-only detection trial:

   ```sh
   sudo modprobe nct6683 force=1
   find /sys/class/hwmon -maxdepth 2 -type f \( -name name -o -name 'fan*_input' -o -name 'pwm*' \) -print
   ```

   Read the `name` file and inspect file permissions before considering anything else. If there is no NCT668x hwmon node, or an ACPI/resource error appears, stop and unload it. Do not use `sensors-detect`, `isadump`, `i2cdetect`, or `acpi_enforce_resources=lax/no`.
4. For full reversal of this temporary trial, while the driver is loaded:

   ```sh
   sudo modprobe -r nct6683
   ```

   Verify `lsmod | grep nct6683` is empty. Since no persistent module configuration was added, reboot also clears a temporary load. BIOS curves remain the control source. If the user later elects to persist module loading, remove that specific added configuration file/line and rebuild initramfs if the distribution requires it.
5. Only if a future, verified kernel build for this exact board exposes writable MSI PWM channels should CoolerControl manual control be considered. Keep a known-good BIOS curve; begin at a conservative/high duty, verify RPM and temperature response per header, and set each channel back to automatic (`pwmN_enable=2`) before leaving or stopping control. If that automatic write fails, immediately restore the BIOS curve/reboot and do not continue software control. **[NV]** Do not assume the external DKMS module's teardown restores BIOS automatic mode; consult its current board-specific documentation before any trial.

To completely reverse a later DKMS installation (not applicable now), use the AUR helper's package removal or `dkms remove nct6687d/1 --all` as applicable, remove any added module-load/modprobe configuration, rebuild initramfs if required by the distro, and reboot. Do not leave both `nct6683` and `nct6687` active for the same chip.

## Resumen corto (español)

La documentación de MSI apunta a un Nuvoton NCT6687. El módulo `nct6683` ya existe en el kernel local 7.2.8, pero no está cargado y aún no hay hwmon de la placa; el parámetro `force=1` puede intentar habilitar detección MSI. La compatibilidad de lectura no garantiza control PWM: el soporte de escritura MSI descrito en una propuesta reciente no está confirmado en este kernel. Mantén las curvas en BIOS; si quieres probar telemetría, carga temporalmente solo `nct6683 force=1`, sin cambiar ACPI ni escribir PWM, y revierte con `modprobe -r nct6683`. Evita por ahora el módulo DKMS externo y el modo manual de CoolerControl.
