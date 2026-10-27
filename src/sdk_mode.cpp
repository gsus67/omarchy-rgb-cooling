// SPDX-License-Identifier: GPL-3.0-or-later
#include "sdk_mode.hpp"
#include <QtEndian>
#include <algorithm>

QByteArray sdkWord(quint32 value)
{
    QByteArray bytes(4, '\0');
    qToLittleEndian(value, bytes.data());
    return bytes;
}

QByteArray sdkHalf(quint16 value)
{
    QByteArray bytes(2, '\0');
    qToLittleEndian(value, bytes.data());
    return bytes;
}

QByteArray sdkText(const QString &value)
{
    const auto bytes = value.toUtf8() + '\0';
    return sdkHalf(bytes.size()) + bytes;
}

bool SdkMode::decode(SdkReader &reader, unsigned version, SdkMode &mode)
{
    mode.name = reader.string();
    if (version < 6) {
        reader.u32();
    }
    mode.flags = reader.u32();
    mode.speedMin = reader.u32();
    mode.speedMax = reader.u32();
    if (version >= 3) {
        mode.brightnessMin = reader.u32();
        mode.brightnessMax = reader.u32();
    }
    mode.colorsMin = reader.u32();
    mode.colorsMax = reader.u32();
    mode.speed = reader.u32();
    if (version >= 3) {
        mode.brightness = reader.u32();
    }
    mode.direction = reader.u32();
    mode.colorMode = reader.u32();
    const auto count = reader.u16();
    if (count > 4096 || mode.colorsMin > mode.colorsMax || mode.colorsMax > 4096
        || mode.speedMin > mode.speedMax || mode.brightnessMin > mode.brightnessMax
        || mode.colorMode > 3) {
        return false;
    }
    for (unsigned i = 0; i < count; ++i) {
        mode.colors.append(reader.u32());
    }
    return reader.valid();
}

QByteArray SdkMode::encode() const
{
    QByteArray result = sdkText(name);
    for (auto field : {flags, speedMin, speedMax, brightnessMin, brightnessMax,
                       colorsMin, colorsMax, speed, brightness, direction, colorMode}) {
        result += sdkWord(field);
    }
    result += sdkHalf(colors.size());
    for (auto color : colors) {
        result += sdkWord(color);
    }
    return result;
}

int SdkController::staticMode() const
{
    for (qsizetype i = 0; i < modes.size(); ++i) {
        const auto &mode = modes[i];
        if (mode.name == "Static" && (mode.flags & (32U | 64U))
            && ((mode.flags & 32U) ? !colors.isEmpty()
                : mode.colorsMax >= std::max(1U, mode.colorsMin))) {
            return i;
        }
    }
    return -1;
}

QJsonObject SdkController::lighting() const
{
    if (device.value("excluded").toBool() || active >= unsigned(modes.size())) {
        return {};
    }
    const auto &mode = modes[active];
    const auto &values = mode.colorMode == 2 ? mode.colors : colors;
    if (values.isEmpty() || !std::all_of(values.begin(), values.end(),
                                       [&](auto value) { return value == values.first(); })) {
        return {};
    }
    const auto first = values.first();
    const auto color = QString("#%1%2%3").arg(first & 255, 2, 16, QChar('0'))
        .arg((first >> 8) & 255, 2, 16, QChar('0')).arg((first >> 16) & 255, 2, 16, QChar('0'));
    int brightness = 100;
    const bool native = (mode.flags & 16U) && mode.brightnessMax > mode.brightnessMin;
    if (native) {
        const auto value = std::clamp(mode.brightness, mode.brightnessMin, mode.brightnessMax);
        brightness = int((quint64(value - mode.brightnessMin) * 100
                          + (mode.brightnessMax - mode.brightnessMin) / 2)
                         / (mode.brightnessMax - mode.brightnessMin));
    }
    return {{"device", device.value("id")}, {"color", color}, {"brightness", brightness},
            {"brightness_emulated", !native}};
}
