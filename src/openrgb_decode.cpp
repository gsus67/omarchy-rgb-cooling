// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb.hpp"
#include "sdk_mode.hpp"
#include <QCryptographicHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>

namespace {
bool matrix(SdkReader &reader)
{
    const auto bytes = reader.u16();
    if (!bytes) {
        return reader.valid();
    }
    const quint64 height = reader.u32();
    const quint64 width = reader.u32();
    return height * width <= 4096 && bytes == 8 + height * width * 4
        && reader.skip(height * width * 4);
}

bool zone(SdkReader &reader, unsigned version)
{
    reader.string();
    reader.u32();
    reader.u32();
    reader.u32();
    if (reader.u32() > 4096 || !matrix(reader)) {
        return false;
    }
    const auto segments = version >= 4 ? reader.u16() : 0;
    if (segments > 4096) {
        return false;
    }
    for (int i = 0; i < segments; ++i) {
        reader.string();
        reader.skip(12);
        if (version >= 6) {
            if (!matrix(reader)) {
                return false;
            }
            reader.u32();
        }
    }
    if (version >= 5) {
        reader.u32();
    }
    if (version >= 6) {
        const auto active = reader.u32();
        const auto count = reader.u16();
        if (count > 256 || (count && active >= count)) {
            return false;
        }
        for (int i = 0; i < count; ++i) {
            SdkMode mode;
            if (!SdkMode::decode(reader, version, mode)) {
                return false;
            }
        }
        reader.string();
    }
    return reader.valid();
}
}

bool SdkController::decode(const QByteArray &payload, unsigned version, SdkController &out)
{
    out = {};
    out.version = version;
    if (version > 6 || payload.size() > 1024 * 1024) {
        return false;
    }
    SdkReader reader(payload);
    if (reader.u32() != payload.size()) {
        return false;
    }
    reader.u32();
    const auto name = reader.string();
    const auto vendor = version >= 1 ? reader.string() : QString();
    const auto description = reader.string();
    reader.string();
    const auto serial = reader.string();
    out.location = reader.string();
    const auto modes = reader.u16();
    out.active = reader.u32();
    if (modes > 256 || (modes && out.active >= modes)) {
        return false;
    }
    for (int i = 0; i < modes; ++i) {
        SdkMode mode;
        if (!SdkMode::decode(reader, version, mode)) {
            return false;
        }
        out.modes.append(mode);
    }
    const auto zones = reader.u16();
    if (zones > 256) {
        return false;
    }
    for (int i = 0; i < zones; ++i) {
        if (!zone(reader, version)) {
            return false;
        }
    }
    const auto leds = reader.u16();
    if (leds > 4096) {
        return false;
    }
    for (int i = 0; i < leds; ++i) {
        reader.string();
        if (version < 6) {
            reader.u32();
        }
    }
    const auto colors = reader.u16();
    if (colors != leds) {
        return false;
    }
    for (int i = 0; i < colors; ++i) {
        out.colors.append(reader.u32());
    }
    if (version >= 5) {
        const auto names = reader.u16();
        if (names > leds) {
            return false;
        }
        for (int i = 0; i < names; ++i) {
            reader.string();
        }
        reader.u32();
    }
    if (version >= 6) {
        reader.string();
        reader.string(true);
    }
    if (!reader.done()) {
        return false;
    }
    const auto identity = QJsonDocument(QJsonArray{name, vendor, description, serial, out.location})
        .toJson(QJsonDocument::Compact);
    const QString text = QString::fromUtf8(identity);
    const QRegularExpression trofeo("0416.{0,32}5302", QRegularExpression::CaseInsensitiveOption);
    const bool excluded = trofeo.match(text).hasMatch()
        || text.contains("trofeo", Qt::CaseInsensitive)
        || text.contains("usbdisplay", Qt::CaseInsensitive);
    const QString id = "openrgb:" + QCryptographicHash::hash(identity,
        QCryptographicHash::Sha256).toHex();
    QJsonArray descriptions;
    for (const auto &mode : out.modes) {
        if (mode.name != "Direct") {
            descriptions.append(mode.description());
        }
    }
    out.device = {{"id", id}, {"name", name}, {"vendor", vendor}, {"engine", "openrgb"},
        {"support", "recognized"}, {"modes", descriptions},
        {"usb", ""}, {"enabled", false}, {"writable", false},
        {"excluded", excluded}, {"blocked_reason", excluded
            ? "0416:5302 is reserved exclusively for omarchy-trcc" : "USB identity is unknown"},
        {"capabilities", excluded || out.lighting().isEmpty()
            ? QJsonArray{} : QJsonArray{"lighting.read"}}};
    return true;
}

bool SdkController::decodeUpdate(const QByteArray &payload, unsigned version, SdkController &out)
{
    if (payload.size() < 8 || payload.size() > 1024 * 1024) {
        return false;
    }
    SdkReader reader(payload);
    if (reader.u32() != quint32(payload.size())) {
        return false;
    }
    // OpenRGB release_1.1: this uint32 is update_reason (UPDATEMODE = 1),
    // emitted by RGBController::UpdateMode(), not a nested descriptor size.
    // NetworkServer::SendRequest_RGBController_SignalUpdate writes size, reason,
    // then GetDeviceDescriptionData; NetworkClient::ProcessRequest_RGBController_SignalUpdate
    // consumes both words before SetDeviceDescription. Ignore the reason here.
    // https://github.com/CalcProgrammer1/OpenRGB/blob/release_1.1/NetworkServer.cpp
    // https://github.com/CalcProgrammer1/OpenRGB/blob/release_1.1/NetworkClient.cpp
    // https://github.com/CalcProgrammer1/OpenRGB/blob/release_1.1/RGBController/RGBController.cpp
    reader.u32();
    // Rebuild the REQ_DATA envelope using only the checked, actual buffer size.
    return decode(sdkWord(payload.size() - 4) + payload.mid(8), version, out);
}

bool OpenRgbAdapter::decodeController(const QByteArray &payload, unsigned version,
                                     QJsonObject &device, QJsonObject &lighting)
{
    SdkController controller;
    if (!SdkController::decode(payload, version, controller)) {
        return false;
    }
    device = controller.device;
    lighting = controller.lighting();
    return true;
}
