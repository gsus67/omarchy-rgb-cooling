// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb.hpp"
#include "sdk_reader.hpp"
#include <QCryptographicHash>
#include <QHostAddress>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QtEndian>
#include <algorithm>
#include <utility>

namespace {
constexpr quint32 MaxPacket = 1024 * 1024;
constexpr quint32 MaxControllers = 128;
const QString WriteGate = QStringLiteral(
    "Hardware writes are blocked: persistent identity, single ownership, "
    "engine Trofeo exclusions and exact device/mode support are not verified");
const QString TrofeoGate = QStringLiteral("0416:5302 is reserved exclusively for omarchy-trcc");
}

OpenRgbAdapter::OpenRgbAdapter(std::function<void()> changed) : changed(std::move(changed))
{
    // [V] Layout/IDs checked against upstream NetworkProtocol.h and RGBController.cpp:
    // https://github.com/CalcProgrammer1/OpenRGB/blob/master/NetworkProtocol.h
    // https://github.com/CalcProgrammer1/OpenRGB/blob/master/RGBController/RGBController.cpp
    // Negotiate v1 deliberately: read-only descriptors need no newer write/mode features.
    // Server replies with its maximum; each controller request carries our selected version.
    socket.setReadBufferSize(MaxPacket + 16);
    timeout.setSingleShot(true);
    timeout.setInterval(2000);
    timeout.setTimerType(Qt::PreciseTimer);
    retry.setSingleShot(true);
    retry.setInterval(2000);
    rescan.setInterval(5000);
    connect(&socket, &QTcpSocket::connected, this, [this] {
        if (socket.peerAddress() != QHostAddress(QHostAddress::LocalHost)) {
            fail("unreachable", "OpenRGB peer is not numeric loopback");
            return;
        }
        phase = Phase::Version;
        send(0, 40, word(1));
    });
    connect(&socket, &QTcpSocket::readyRead, this, [this] { receive(); });
    connect(&socket, &QTcpSocket::errorOccurred, this, [this](auto error) {
        const bool absent = error == QAbstractSocket::ConnectionRefusedError;
        fail(absent ? "absent" : "unreachable",
             absent ? "OpenRGB SDK server is absent" : "OpenRGB SDK transport failed");
    });
    connect(&socket, &QTcpSocket::disconnected, this, [this] {
        if (phase != Phase::Disconnected) {
            fail("unreachable", "OpenRGB SDK server disconnected");
        }
    });
    connect(&timeout, &QTimer::timeout, this, [this] {
        fail("unreachable", "OpenRGB SDK response timed out");
    });
    connect(&retry, &QTimer::timeout, this, [this] { connectServer(); });
    connect(&rescan, &QTimer::timeout, this, [this] { refresh(); });
    connectServer();
}

OpenRgbAdapter::~OpenRgbAdapter()
{
    // Socket signals must not call back into partially destroyed inventory members.
    socket.disconnect(this);
    socket.abort();
}

QByteArray OpenRgbAdapter::word(quint32 value)
{
    QByteArray bytes(4, '\0');
    qToLittleEndian(value, bytes.data());
    return bytes;
}

void OpenRgbAdapter::connectServer()
{
    if (phase != Phase::Disconnected) {
        return;
    }
    input.clear();
    pendingInventory.clear();
    pendingColors.clear();
    phase = Phase::Connecting;
    timeout.start();
    socket.connectToHost(QHostAddress::LocalHost, 6742);
}

void OpenRgbAdapter::fail(const QString &newState, const QString &message)
{
    phase = Phase::Disconnected;
    timeout.stop();
    rescan.stop();
    socket.abort();
    input.clear();
    pendingInventory.clear();
    pendingColors.clear();
    inventory.clear();
    colors.clear();
    state = newState;
    reason = message;
    retry.start();
    changed();
}

void OpenRgbAdapter::refresh()
{
    if (phase != Phase::Ready) {
        return;
    }
    // Protocol v1 indices can be reassigned after hotplug. Rebuild the entire map.
    phase = Phase::Count;
    pendingInventory.clear();
    pendingColors.clear();
    send(0, 0);
}

void OpenRgbAdapter::send(quint32 device, quint32 command, const QByteArray &payload)
{
    const QByteArray header = QByteArray("ORGB", 4) + word(device) + word(command)
        + word(static_cast<quint32>(payload.size()));
    if (socket.write(header + payload) < 0) {
        fail("unreachable", "OpenRGB SDK request failed");
        return;
    }
    // An absolute per-request deadline: a trickle of bytes cannot extend it.
    timeout.start();
}

void OpenRgbAdapter::receive()
{
    const qsizetype room = MaxPacket + 16 - input.size();
    if (room <= 0) {
        fail("unreachable", "OpenRGB SDK receive buffer exceeded its limit");
        return;
    }
    input.append(socket.read(room));
    for (int budget = 0; budget < 256 && input.size() >= 16; ++budget) {
        if (input.first(4) != "ORGB") {
            fail("unreachable", "OpenRGB SDK packet has invalid magic");
            return;
        }
        SdkReader header(input);
        header.skip(4);
        const auto device = header.u32();
        const auto command = header.u32();
        const auto length = header.u32();
        if (length > MaxPacket) {
            fail("unreachable", "OpenRGB SDK packet is too large");
            return;
        }
        if (input.size() < 16 + qsizetype(length)) {
            return;
        }
        const QByteArray payload = input.mid(16, length);
        input.remove(0, 16 + length);
        if (!packet(device, command, payload)) {
            fail("unreachable", "OpenRGB SDK packet or descriptor is invalid");
            return;
        }
    }
    if (socket.bytesAvailable() > 0 || input.size() >= 16) {
        QTimer::singleShot(0, this, [this] { receive(); });
    }
}

bool OpenRgbAdapter::packet(quint32 device, quint32 command, const QByteArray &payload)
{
    if (command == 100 && device == 0 && payload.isEmpty()) {
        // Drop in-flight index replies and reconnect; no stale index can survive a rescan.
        fail("unreachable", "OpenRGB device list changed; rebuilding identities");
        return true;
    }
    if (phase == Phase::Version && command == 40 && device == 0 && payload.size() == 4) {
        const auto advertised = qFromLittleEndian<quint32>(payload.constData());
        protocolVersion = std::min(advertised, 1U);
        phase = Phase::Count;
        send(0, 0);
        return true;
    }
    if (phase == Phase::Count && command == 0 && device == 0 && payload.size() == 4) {
        controllerCount = qFromLittleEndian<quint32>(payload.constData());
        if (controllerCount > MaxControllers) {
            return false;
        }
        controllerIndex = 0;
        if (controllerCount == 0) {
            publish();
        } else {
            phase = Phase::Controller;
            send(controllerIndex, 1, word(protocolVersion));
        }
        return true;
    }
    if (phase == Phase::Controller && command == 1 && device == controllerIndex) {
        QJsonObject descriptor;
        QJsonObject lighting;
        if (!decodeController(payload, protocolVersion, descriptor, lighting)) {
            return false;
        }
        const QString id = descriptor.value("id").toString();
        pendingInventory.insert(id, descriptor);
        if (!lighting.isEmpty()) {
            pendingColors.insert(id, lighting);
        }
        ++controllerIndex;
        if (controllerIndex == controllerCount) {
            publish();
        } else {
            send(controllerIndex, 1, word(protocolVersion));
        }
        return true;
    }
    return false;
}

void OpenRgbAdapter::publish()
{
    inventory = pendingInventory;
    colors = pendingColors;
    phase = Phase::Ready;
    timeout.stop();
    rescan.start();
    state = inventory.isEmpty() ? "ready" : "blocked";
    reason = inventory.isEmpty() ? "OpenRGB SDK connected; no devices" : WriteGate;
    changed();
}

QJsonObject OpenRgbAdapter::engine() const
{
    return {{"id", "openrgb"}, {"state", state}, {"reason", reason}};
}

QJsonArray OpenRgbAdapter::devices() const
{
    QJsonArray result;
    for (const auto &device : inventory) {
        result.append(device);
    }
    return result;
}

Protocol::Reply OpenRgbAdapter::lighting(const QString &device) const
{
    if (!inventory.contains(device)) {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    if (inventory.value(device).value("excluded").toBool()) {
        return Protocol::Reply::failure("blocked", TrofeoGate);
    }
    if (!colors.contains(device)) {
        return Protocol::Reply::failure("unsupported", "No uniform static lighting is available");
    }
    return {colors.value(device), {}, {}};
}

Protocol::Reply OpenRgbAdapter::setLighting(const QString &device, const QString &, int)
{
    if (!inventory.contains(device)) {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    const auto descriptor = inventory.value(device);
    return Protocol::Reply::failure("blocked", descriptor.value("blocked_reason").toString());
}

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
