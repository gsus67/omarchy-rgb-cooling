// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb.hpp"
#include "sdk_reader.hpp"
#include <QCryptographicHash>
#include <QJsonDocument>
#include <QRegularExpression>

namespace {
constexpr quint32 MaxPacket = 1024 * 1024;
} // namespace

const QString OpenRgbAdapter::WriteGate = QStringLiteral(
    "Hardware writes are blocked: persistent identity, single ownership, "
    "engine Trofeo exclusions and exact device/mode support are not verified");
const QString OpenRgbAdapter::TrofeoGate = QStringLiteral(
    "0416:5302 is reserved exclusively for omarchy-trcc");

bool OpenRgbAdapter::decodeController(const QByteArray &payload, unsigned version,
                                     QJsonObject &device, QJsonObject &lighting)
{
    device = {};
    lighting = {};
    if (version > 1 || payload.size() > MaxPacket) {
        return false;
    }
    SdkReader reader(payload);
    if (reader.u32() != payload.size()) {
        return false;
    }
    reader.u32(); // Device type is presentation metadata, never a write gate.
    const QString name = reader.string();
    const QString vendor = version >= 1 ? reader.string() : QString();
    const QString description = reader.string();
    reader.string(); // Firmware version may change without changing physical identity.
    const QString serial = reader.string();
    const QString location = reader.string();
    const auto modes = reader.u16();
    const auto activeMode = reader.u32();
    if (modes > 256 || (modes > 0 && activeMode >= modes)) {
        return false;
    }
    for (unsigned index = 0; index < modes; ++index) {
        reader.string();
        // v0/v1: value, flags, speed/color limits, speed, direction and color mode.
        reader.skip(9 * 4);
        const auto count = reader.u16();
        if (count > 4096 || !reader.skip(qsizetype(count) * 4)) {
            return false;
        }
    }
    const auto zones = reader.u16();
    if (zones > 256) {
        return false;
    }
    for (unsigned index = 0; index < zones; ++index) {
        reader.string();
        reader.u32(); // Zone type.
        reader.u32(); // Minimum LEDs.
        reader.u32(); // Maximum LEDs.
        const auto count = reader.u32();
        const auto matrixBytes = reader.u16();
        if (count > 4096) {
            return false;
        }
        if (matrixBytes != 0) {
            const auto height = reader.u32();
            const auto width = reader.u32();
            const quint64 cells = quint64(height) * width;
            if (cells > 4096 || matrixBytes != 8 + cells * 4
                || !reader.skip(qsizetype(cells) * 4)) {
                return false;
            }
        }
    }
    const auto leds = reader.u16();
    if (leds > 4096) {
        return false;
    }
    for (unsigned index = 0; index < leds; ++index) {
        reader.string();
        reader.u32();
    }
    const auto colorCount = reader.u16();
    if (colorCount > 4096 || colorCount != leds) {
        return false;
    }
    quint32 firstColor = 0;
    bool uniform = true;
    for (unsigned index = 0; index < colorCount; ++index) {
        const auto color = reader.u32();
        if (index == 0) {
            firstColor = color;
        } else if (color != firstColor) {
            uniform = false;
        }
    }
    if (!reader.done()) {
        return false;
    }
    const QJsonArray identityFields{name, vendor, description, serial, location};
    const QByteArray identityBytes = QJsonDocument(identityFields).toJson(QJsonDocument::Compact);
    const QString identityText = QString::fromUtf8(identityBytes);
    const auto identity = QCryptographicHash::hash(identityBytes,
                                                  QCryptographicHash::Sha256).toHex();
    const QString id = "openrgb:" + QString::fromLatin1(identity);
    static const QRegularExpression trofeo(
        "0416.{0,32}5302", QRegularExpression::CaseInsensitiveOption);
    const bool excluded = trofeo.match(identityText).hasMatch()
        || identityText.contains("trofeo", Qt::CaseInsensitive)
        || identityText.contains("usbdisplay", Qt::CaseInsensitive);
    QJsonArray capabilities;
    if (!excluded && colorCount > 0 && uniform) {
        capabilities.append("lighting.read");
        const auto red = firstColor & 255;
        const auto green = (firstColor >> 8) & 255;
        const auto blue = (firstColor >> 16) & 255;
        const QString color = QString("#%1%2%3")
            .arg(red, 2, 16, QChar('0')).arg(green, 2, 16, QChar('0'))
            .arg(blue, 2, 16, QChar('0'));
        lighting = {{"device", id}, {"color", color}, {"brightness", 100},
                    {"brightness_emulated", false}};
    }
    device = {{"id", id}, {"name", name}, {"vendor", vendor}, {"engine", "openrgb"},
              {"support", "recognized"}, {"writable", false},
              {"blocked_reason", excluded ? TrofeoGate : WriteGate},
              {"excluded", excluded}, {"capabilities", capabilities}};
    return true;
}
