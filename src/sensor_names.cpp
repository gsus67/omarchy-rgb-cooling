// SPDX-License-Identifier: GPL-3.0-or-later
#include "sensor_names.hpp"
#include <QRegularExpression>

namespace {
bool startsWithAny(const QString &value, const QStringList &prefixes)
{
    for (const auto &prefix : prefixes) {
        if (value.startsWith(prefix)) {
            return true;
        }
    }
    return false;
}

bool motherboard(const QString &name)
{
    return name == "nct6683" || name == "nct6687" || name == "nct6775"
        || name == "nct6779" || name == "it87" || name.startsWith("it8");
}

// The hwmon driver identifies the sensor's own CPU; /proc/cpuinfo is only a
// fallback for drivers that do not imply a vendor.
QString cpuName(const QString &driver, const QString &vendor)
{
    if (driver == "coretemp") {
        return "Intel CPU";
    }
    if (driver == "k10temp" || driver == "zenpower") {
        return "AMD CPU";
    }
    if (vendor == "GenuineIntel") {
        return "Intel CPU";
    }
    if (vendor == "AuthenticAMD") {
        return "AMD CPU";
    }
    return "CPU";
}
}

QString SensorNames::device(const QString &hwmonName, const QString &parentPath,
                            const QString &driver, const QString &cpuVendor, int nvmeNumber)
{
    const QString hwmon = hwmonName.toLower();
    const QString module = driver.isEmpty() ? hwmon : driver.toLower();
    if (motherboard(hwmon) || motherboard(module)) {
        return "Motherboard";
    }
    if (hwmon == "coretemp" || hwmon == "k10temp" || hwmon == "zenpower"
        || hwmon.startsWith("cpu")) {
        return cpuName(hwmon, cpuVendor);
    }
    if (module == "amdgpu" || hwmon == "amdgpu") {
        return "AMD GPU";
    }
    if (module == "nouveau" || hwmon == "nouveau") {
        return "NVIDIA GPU";
    }
    if (module == "nvidia" || hwmon == "nvidia") {
        return "NVIDIA GPU";
    }
    if (module == "i915" || module == "xe" || hwmon == "i915" || hwmon == "xe") {
        return "Intel GPU";
    }
    if (hwmon.startsWith("nvme") || module == "nvme") {
        return nvmeNumber > 0 ? QString("NVMe %1").arg(nvmeNumber) : "NVMe";
    }
    if (hwmon == "spd5118" || hwmon == "jc42" || hwmon == "ee1004") {
        return "RAM";
    }
    if (hwmon.startsWith("iwlwifi") || module.startsWith("iwlwifi")) {
        return "Wi-Fi";
    }
    if (startsWithAny(module, {"r8169", "igc", "e1000e", "e1000", "atlantic", "alx",
                               "igb", "ixgbe", "r8152", "tg3", "bnx2"})
        || parentPath.contains("/net/")) {
        return "Ethernet";
    }
    if (hwmon == "acpitz") {
        return "ACPI";
    }
    return hwmonName;
}

QString SensorNames::label(const QString &hwmonName, const QString &channel,
                           const QString &customLabel)
{
    if (motherboard(hwmonName.toLower()) && channel.startsWith("fan")) {
        return "Fan " + channel.mid(3);
    }
    if (!customLabel.isEmpty()) {
        return customLabel;
    }
    static const QRegularExpression channelNumber("[0-9]+$");
    const QString number = channelNumber.match(channel).captured();
    const QString kind = channel.startsWith("fan") ? "Fan" : "Temperature";
    Q_UNUSED(hwmonName);
    return number.isEmpty() || number == "1" ? kind : kind + " " + number;
}
