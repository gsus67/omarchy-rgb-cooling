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
        mode.value = reader.u32();
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
        || mode.colorMode > 3) {
        return false;
    }
    for (unsigned i = 0; i < count; ++i) {
        mode.colors.append(reader.u32());
    }
    return reader.valid();
}

QByteArray SdkMode::encode(unsigned version) const
{
    QByteArray result = sdkText(name);
    if (version < 6) {
        result += sdkWord(value);
    }
    result += sdkWord(flags) + sdkWord(speedMin) + sdkWord(speedMax);
    if (version >= 3) {
        result += sdkWord(brightnessMin) + sdkWord(brightnessMax);
    }
    result += sdkWord(colorsMin) + sdkWord(colorsMax) + sdkWord(speed);
    if (version >= 3) {
        result += sdkWord(brightness);
    }
    result += sdkWord(direction) + sdkWord(colorMode);
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
    const bool uniform = !values.isEmpty() && std::all_of(values.begin(), values.end(),
        [&](auto value) { return value == values.first(); });
    if (mode.singleColor() && mode.colorMode != 3 && !uniform) {
        return {};
    }
    const auto first = uniform ? values.first() : 0U;
    const auto color = QString("#%1%2%3").arg(first & 255, 2, 16, QChar('0'))
        .arg((first >> 8) & 255, 2, 16, QChar('0')).arg((first >> 16) & 255, 2, 16, QChar('0'));
    const bool native = mode.flags & 16U;
    return {{"device", device.value("id")}, {"mode", mode.name}, {"color", color},
            {"brightness", native
                ? modePercent(mode.brightness, mode.brightnessMin, mode.brightnessMax) : 100},
            {"brightness_emulated", !native},
            {"speed", (mode.flags & 1U)
                ? QJsonValue(modePercent(mode.speed, mode.speedMin, mode.speedMax))
                : QJsonValue(QJsonValue::Null)},
            {"random", mode.colorMode == 3}, {"saved", true}};
}

quint32 modeRange(int percent, quint32 minimum, quint32 maximum)
{
    return (quint64(minimum) * (100 - percent) + quint64(maximum) * percent + 50) / 100;
}

int modePercent(quint32 value, quint32 minimum, quint32 maximum)
{
    if (minimum == maximum) {
        return 100;
    }
    value = std::clamp(value, std::min(minimum, maximum), std::max(minimum, maximum));
    const quint64 distance = qAbs(qint64(value) - minimum);
    const quint64 range = qAbs(qint64(maximum) - minimum);
    return (distance * 100 + range / 2) / range;
}

QJsonObject SdkMode::description() const
{
    return {{"name", name}, {"speed", bool(flags & 1U)}, {"brightness", bool(flags & 16U)},
            {"color", singleColor() ? "single" : "none"}, {"random", bool(flags & 128U)},
            {"savable", savable()}};
}
