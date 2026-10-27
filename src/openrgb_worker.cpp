// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb_worker.hpp"
#include <QHostAddress>
#include <QRegularExpression>
#include <QtEndian>

OpenRgbWorker::OpenRgbWorker(const QString &root, const QString &rules)
    : root(root), rules(rules), unit(this)
{
    // QObject members must be children so all sockets, D-Bus and timers follow the worker.
    socket.setParent(this);
    timeout.setParent(this);
    startupRetry.setParent(this);
    startupDeadline.setParent(this);
    for (auto *timer : {&startupRetry, &startupDeadline}) {
        timer->setTimerType(Qt::PreciseTimer);
    }
    startupDeadline.setSingleShot(true);
    startupRetry.setInterval(250);
    startupDeadline.setInterval(10000);
    connect(&startupRetry, &QTimer::timeout, this, [this] { connectServer(); });
    connect(&startupDeadline, &QTimer::timeout, this, [this] {
        fail("OpenRGB SDK server did not become reachable within 10 s after StartUnit");
    });
    socket.setReadBufferSize(1024 * 1024 + 16);
    timeout.setSingleShot(true);
    timeout.setInterval(2000);
    timeout.setTimerType(Qt::PreciseTimer);
    connect(&timeout, &QTimer::timeout, this, [this] {
        connectionFailed("OpenRGB SDK response timed out");
    });
    connect(&socket, &QTcpSocket::connected, this, [this] {
        if (startup.isValid() && startup.elapsed() >= 10000) {
            fail("OpenRGB SDK server did not become reachable within 10 s after StartUnit");
            return;
        }
        endStartup();
        phase = Phase::Version;
        send(0, 40, sdkWord(6));
    });
    connect(&socket, &QTcpSocket::readyRead, this, [this] { receive(); });
    connect(&socket, &QTcpSocket::errorOccurred, this, [this](auto) {
        connectionFailed("OpenRGB SDK transport failed");
    });
    connect(&socket, &QTcpSocket::disconnected, this, [this] {
        if (phase != Phase::Disconnected) {
            fail("OpenRGB SDK server disconnected");
        }
    });
    unit.settled = [this] { next(); };
    unit.stopped = [this] {
        if (scanning || !reading.isEmpty()) {
            fail("OpenRGB unit stopped before the SDK operation completed");
            return;
        }
        endStartup();
        timeout.stop();
        idleStopped = true;
        phase = Phase::Disconnected;
        socket.abort();
        gates();
        state = "absent";
        reason = "OpenRGB unit stopped; lighting operations or a scan can start it again";
        notify();
        next();
    };
}

OpenRgbWorker::~OpenRgbWorker()
{
    socket.disconnect(this);
    socket.abort();
}
void OpenRgbWorker::subscribed(bool value) { unit.setSubscribed(value); }
void OpenRgbWorker::perform(const QString &op, const QJsonObject &params, Callback ready)
{
    requests.enqueue({op, params, std::move(ready), scanning});
    if (requests.size() == 1) {
        next();
    }
}
void OpenRgbWorker::refresh()
{
    if (!scanning) {
        perform("devices.hotplug", {}, [](const auto &) {});
    }
}
void OpenRgbWorker::next()
{
    if (scanning || requests.isEmpty() || phase == Phase::Read || unit.transitioning()) {
        return;
    }
    auto &request = requests.head();
    const auto &op = request.operation;
    if ((op == "devices.rescan" || op == "devices.hotplug") && !request.join) {
        if (op == "devices.rescan" && lastScan.isValid() && lastScan.elapsed() < 2000) {
            finish(Protocol::Reply::failure("rate_limited", "Scans must be at least 2 s apart"));
            return;
        }
        request.join = true;
        scan();
        return;
    }
    if (!lastScan.isValid()) {
        request.join = true;
        scan();
        return;
    }
    if (op == "devices" || op == "devices.rescan" || op == "devices.hotplug") {
        QJsonArray devices;
        for (const auto &device : inventory) {
            devices.append(device);
        }
        finish({{{"devices", devices}}, {}, {}});
        return;
    }
    if (idleStopped) {
        request.join = true;
        scan();
        return;
    }
    if (phase == Phase::Disconnected && !controllers.isEmpty() && !usb.enabled.isEmpty()) {
        // A transport failure does not erase physical identity. Reconnect before
        // checking the cached write gate, then use the newly validated descriptor.
        if (request.join) {
            finish(Protocol::Reply::failure("unavailable", reason));
        } else {
            request.join = true;
            scan();
        }
        return;
    }
    unit.activity();
    const auto id = request.params.value("device").toString();
    const auto gate = lighting(id);
    if (op == "lighting.set" || op == "lighting.save") {
        if (!inventory.contains(id) || !inventory[id].value("writable").toBool()) {
            finish(Protocol::Reply::failure(inventory.contains(id) ? "blocked" : "unavailable",
                inventory.contains(id) ? inventory[id].value("blocked_reason").toString()
                                       : "Device is not available"));
            return;
        }
    } else if (!gate.ok()) {
        finish(gate);
        return;
    }
    if (phase == Phase::Disconnected && usb.enabled.size() > 0) {
        // An idle stop is not a failed scan. A new lighting operation needs the unit again.
        scan();
        return;
    }
    if (phase != Phase::Idle || !controllers.contains(id)) {
        finish(gate);
        return;
    }
    reading = id;
    writing = op == "lighting.set" || op == "lighting.save";
    phase = Phase::Read;
    // Re-read current mode/colour and re-check gates immediately before a write.
    send(controllers[id].index, 1, version >= 6 ? QByteArray() : sdkWord(version));
}
void OpenRgbWorker::scan()
{
    scanning = true;
    idleStopped = false;
    lastScan.start();
    endStartup();
    phase = Phase::Disconnected;
    socket.abort();
    input.clear();
    pendingControllers.clear();
    controllerIds.clear();
    acknowledgements.clear();
    awaitingWriteAck = false;
    writtenColor.clear();
    writtenMode = -1;
    saving = false;
    usb = UsbDevices::scan(root, rules);
    if (controllers.isEmpty()) {
        inventory = usb.candidates;
    }
    updateSaved();
    QSet<QString> allowed;
    for (const auto &device : usb.candidates) {
        if (device.value("enabled").toBool()) {
            allowed.insert(device.value("usb").toString());
        }
    }
    QMap<QString, QString> nodes;
    for (auto it = usb.nodes.begin(); it != usb.nodes.end(); ++it) {
        if (usb.enabled.contains(it.value()) && !it.value().startsWith("usb:0416:5302:")
            && usb.locations.value(it.value()).size() == 1) {
            nodes.insert(it.key(), it.value());
        }
    }
    auto activate = [this, allowed, nodes](bool stopped) {
        if (!stopped) {
            fail("Unable to stop OpenRGB after the enabled USB device list changed");
            return;
        }
        if (allowed.isEmpty()) {
            controllers.clear();
            inventory = usb.candidates;
            state = "absent";
            reason = usb.valid ? "No enabled USB HID candidates"
                               : "Invalid devices.json; writes disabled";
            scanning = false;
            notify();
            next();
            return;
        }
        phase = Phase::Starting;
        const bool starting = !unit.owned();
        unit.start([this, allowed, nodes, starting](bool success) {
            if (!success) {
                fail("Unable to start the plugin's OpenRGB unit through the session bus");
            } else {
                launchedDevices = allowed;
                launchedNodes = nodes;
                if (starting) {
                    // Only a new StartUnit gets a bounded connection grace period.
                    startup.start();
                    startupDeadline.start();
                    startupRetry.start();
                }
                connectServer();
            }
        });
    };
    if (unit.owned() && (allowed != launchedDevices || nodes != launchedNodes)) {
        unit.stop(std::move(activate));
    } else {
        activate(true);
    }
}
void OpenRgbWorker::connectServer()
{
    if (startup.isValid() && startup.elapsed() >= 10000) {
        fail("OpenRGB SDK server did not become reachable within 10 s after StartUnit");
        return;
    }
    phase = Phase::Disconnected;
    socket.abort();
    version = 6;
    phase = Phase::Connecting;
    timeout.start();
    socket.connectToHost(QHostAddress::LocalHost, 6742);
}
void OpenRgbWorker::connectionFailed(const QString &message)
{
    if (phase == Phase::Connecting && startup.isValid()) {
        // Keep the scan and its joined requests pending while the unit detects hardware.
        phase = Phase::Starting;
        timeout.stop();
        socket.abort();
    } else {
        fail(message);
    }
}
void OpenRgbWorker::endStartup()
{
    startup.invalidate();
    startupRetry.stop();
    startupDeadline.stop();
}
void OpenRgbWorker::send(quint32 device, quint32 command, const QByteArray &payload)
{
    if (version >= 6) {
        const auto key = (quint64(device) << 32) | command;
        ++acknowledgements[key];
    }
    if (socket.write(QByteArray("ORGB", 4) + sdkWord(device) + sdkWord(command)
                     + sdkWord(payload.size()) + payload) < 0) {
        fail("OpenRGB SDK request failed");
        return;
    }
    timeout.start();
}
void OpenRgbWorker::receive()
{
    constexpr qsizetype maximum = 1024 * 1024;
    const auto room = maximum + 16 - input.size();
    if (room <= 0) {
        fail("OpenRGB receive buffer exceeded its limit");
        return;
    }
    input += socket.read(room);
    for (int budget = 0; budget < 256 && input.size() >= 16; ++budget) {
        if (input.first(4) != "ORGB") {
            fail("OpenRGB packet has invalid magic");
            return;
        }
        SdkReader header(input);
        header.skip(4);
        const auto device = header.u32(), command = header.u32(), size = header.u32();
        if (size > maximum) {
            fail("OpenRGB packet is too large");
            return;
        }
        if (input.size() < 16 + qsizetype(size)) {
            return;
        }
        const auto payload = input.mid(16, size);
        input.remove(0, 16 + size);
        if (!packet(device, command, payload)) {
            fail("OpenRGB packet or descriptor is invalid");
            return;
        }
        if (phase == Phase::Disconnected) {
            return;
        }
    }
    if (socket.bytesAvailable() || input.size() >= 16) {
        QTimer::singleShot(0, this, [this] { receive(); });
    }
}
void OpenRgbWorker::fail(const QString &message)
{
    endStartup();
    phase = Phase::Disconnected;
    socket.abort();
    timeout.stop();
    input.clear();
    pendingControllers.clear();
    // Keep the last complete inventory across transport failures. A controller
    // already supplied by OpenRGB must not turn back into its USB candidate.
    if (controllers.isEmpty()) {
        inventory = usb.candidates;
    }
    for (auto &device : inventory) {
        if (device.value("writable").toBool()) {
            device.insert("writable", false);
            device.insert("blocked_reason", message);
            device.insert("capabilities", QJsonArray{"lighting.read"});
        }
    }
    writtenColor.clear();
    writtenMode = -1;
    saving = false;
    state = "unreachable";
    reason = message;
    scanning = false;
    notify();
    if (!reading.isEmpty()) {
        reading.clear();
        finish(Protocol::Reply::failure("unavailable", message));
    } else {
        next();
    }
}
void OpenRgbWorker::publish()
{
    timeout.stop();
    controllers = std::move(pendingControllers);
    pendingControllers.clear();
    scanning = false;
    phase = Phase::Idle;
    gates();
    state = "ready";
    reason.clear();
    notify();
    next();
}
void OpenRgbWorker::notify()
{
    QJsonArray devices;
    for (const auto &device : inventory) {
        devices.append(device);
    }
    changed({{"id", "openrgb"}, {"state", state}, {"reason", reason}}, devices, unit.owned());
}
void OpenRgbWorker::finish(const Protocol::Reply &reply)
{
    if (requests.isEmpty()) {
        return;
    }
    const auto request = requests.dequeue();
    request.ready(reply);
    QTimer::singleShot(0, this, [this] { next(); });
}
