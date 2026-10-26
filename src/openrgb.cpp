// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb.hpp"
#include "sdk_reader.hpp"
#include <QHostAddress>
#include <QtEndian>
#include <algorithm>
#include <utility>

namespace {
constexpr quint32 MaxPacket = 1024 * 1024;
constexpr quint32 MaxControllers = 128;

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
    lastScan.start();
    input.clear();
    pendingInventory.clear();
    pendingColors.clear();
    phase = Phase::Connecting;
    timeout.start();
    socket.connectToHost(QHostAddress::LocalHost, 6742);
}

void OpenRgbAdapter::fail(const QString &newState, const QString &message)
{
    if (phase == Phase::Disconnected) {
        return;
    }
    phase = Phase::Disconnected;
    timeout.stop();
    socket.abort();
    input.clear();
    pendingInventory.clear();
    pendingColors.clear();
    inventory.clear();
    colors.clear();
    state = newState;
    reason = message;
    changed();
    settleRequests();
}

void OpenRgbAdapter::refresh()
{
    // Hotplug joins any scan already in progress; it never schedules a later retry.
    connectServer();
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
    if (phase == Phase::Disconnected) {
        return;
    }
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
        if (phase == Phase::Disconnected) {
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
        // Indices changed mid-scan. Leave failure cached until the next explicit scan.
        fail("unreachable", "OpenRGB device list changed during scan");
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
    phase = Phase::Disconnected;
    timeout.stop();
    socket.abort();
    input.clear();
    pendingInventory.clear();
    pendingColors.clear();
    state = inventory.isEmpty() ? "ready" : "blocked";
    reason = inventory.isEmpty() ? "OpenRGB scan completed; no devices" : WriteGate;
    changed();
    settleRequests();
}

void OpenRgbAdapter::request(std::function<void()> ready)
{
    if (phase == Phase::Disconnected && lastScan.isValid()) {
        ready();
        return;
    }
    pending.push_back(std::move(ready));
    connectServer();
}

bool OpenRgbAdapter::rescan(std::function<void()> ready)
{
    // Concurrent callers share the running scan, including its eventual failure.
    if (phase == Phase::Disconnected && lastScan.isValid() && lastScan.elapsed() < 2000) {
        return false;
    }
    pending.push_back(std::move(ready));
    connectServer();
    return true;
}

void OpenRgbAdapter::settleRequests()
{
    auto callbacks = std::exchange(pending, {});
    for (const auto &callback : callbacks) {
        callback();
    }
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
