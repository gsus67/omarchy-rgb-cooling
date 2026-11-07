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
    for (auto *timer : {&recoveryDebounce, &recoveryDeadline, &writeFailure}) {
        timer->setParent(this);
        timer->setSingleShot(true);
        timer->setTimerType(Qt::PreciseTimer);
    }
    recoveryDebounce.setInterval(1000);
    recoveryDeadline.setInterval(15000);
    writeFailure.setInterval(1000);
    connect(&recoveryDebounce, &QTimer::timeout, this, [this] {
        recoveryDue = true;
        recover();
    });
    connect(&recoveryDeadline, &QTimer::timeout, this, [this] {
        recoveryDebounce.stop();
        suspendOperation();
        fail("Device reconnection did not complete within 15 s", false);
    });
    connect(&writeFailure, &QTimer::timeout, this, [this] {
        if (!recovering) {
            fail(pendingFailure, false);
        }
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
    unit.settled = [this] {
        if (recovering) {
            recover();
        } else {
            next();
        }
    };
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
    if (recovering && op == "devices") {
        QJsonArray devices;
        for (const auto &device : inventory) {
            devices.append(device);
        }
        ready({{{"devices", devices}}, {}, {}});
        return;
    }
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
void OpenRgbWorker::hotplug(const QVector<HotplugEvent> &events, bool discover)
{
    const auto current = UsbDevices::scan(root, rules);
    QSet<QString> affected;
    if (unit.owned() || unit.transitioning()) {
        for (auto it = launchedNodes.begin(); it != launchedNodes.end(); ++it) {
            const auto &identity = it.value();
            if (!current.enabled.contains(identity) || identity.startsWith("usb:0416:5302:")) {
                continue;
            }
            if (current.nodes.value(it.key()) != identity) {
                affected.insert(identity);
            }
            for (const auto &event : events) {
                if (event.action != "remove" && event.action != "add") {
                    continue;
                }
                // Removed sysfs attributes may already be gone. Match their last
                // validated node or USB parent path as well as a resolved ID.
                const bool knownPath = !event.path.isEmpty()
                    && usb.locations.value(identity).contains(event.path);
                if (event.identity == identity || event.node == it.key() || knownPath) {
                    affected.insert(identity);
                }
            }
        }
    }
    usb = current;
    if (!affected.isEmpty()) {
        reconnecting.unite(affected);
        if (!recovering) {
            recovering = true;
            recoveryRestarted = false;
            recoveryDirty = false;
            recoveryDeadline.start();
            unit.activity();
        }
        // Events after StartUnit may invalidate that new sandbox too. Keep
        // them pending until another quiet interval, including during startup.
        recoveryDirty = recoveryRestarted;
        recoveryDue = false;
        recoveryDebounce.start();
        gates();
        state = "blocked";
        reason = "Device reconnected; restarting OpenRGB";
        notify();
    } else if (!recovering && discover) {
        refresh();
    }
}

void OpenRgbWorker::completeAppliedWrite()
{
    if (reading.isEmpty()) {
        return;
    }
    const auto identity = controllers.value(reading).device.value("usb").toString();
    if (writtenMode >= 0) {
        auto payload = sdkWord(writtenMode) + writtenDescriptor.encode(version);
        payload.prepend(sdkWord(payload.size() + 4));
        appliedModes[identity] = payload;
        auto &controller = controllers[reading];
        controller.active = writtenMode;
        controller.modes[writtenMode] = writtenDescriptor;
        if (writtenDescriptor.colorMode == 1 && !writtenColor.isEmpty()) {
            const auto rgb = writtenColor.mid(1).toUInt(nullptr, 16);
            const auto packed = ((rgb >> 16) & 255) | (rgb & 0xff00) | ((rgb & 255) << 16);
            controller.colors.fill(packed);
        }
    }
    if (saving) {
        unsaved.remove(identity);
        updateSaved();
    }
}

void OpenRgbWorker::suspendOperation()
{
    writeFailure.stop();
    if (!reading.isEmpty() && !requests.isEmpty() && (writtenMode >= 0 || saving)) {
        auto &request = requests.head();
        if (version >= 6 && !awaitingWriteAck && !writeAckFailed) {
            // An ACK confirms the write even if re-enumeration loses REQ_DATA.
            completeAppliedWrite();
            request.applied = lighting(reading).result;
        } else if (writeAckFailed || request.retries >= 1) {
            finish(Protocol::Reply::failure("unavailable",
                "OpenRGB write was not acknowledged after reconnection"));
        } else {
            ++request.retries;
        }
    }
    reading.clear();
    writing = false;
    writtenMode = -1;
    saving = false;
}

void OpenRgbWorker::recover()
{
    if (!recovering || !recoveryDue || (recoveryRestarted && !recoveryDirty)
        || unit.transitioning()) {
        return;
    }
    for (const auto &identity : reconnecting) {
        if (usb.locations.value(identity).isEmpty()) {
            return; // Only a later udev event can resume recovery; never poll USB.
        }
    }
    recoveryRestarted = true;
    recoveryDirty = false;
    suspendOperation();
    scan();
}

void OpenRgbWorker::next()
{
    if (recovering || writeFailure.isActive()) {
        return;
    }
    if (scanning || requests.isEmpty() || phase == Phase::Read || unit.transitioning()) {
        return;
    }
    auto &request = requests.head();
    const auto &op = request.operation;
    if (!request.applied.isEmpty()) {
        finish({request.applied, {}, {}});
        return;
    }
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
    const auto generation = ++scanGeneration;
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
    writeAckFailed = false;
    writtenColor.clear();
    writtenMode = -1;
    saving = false;
    usb = UsbDevices::scan(root, rules);
    if (controllers.isEmpty()) {
        gates();
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
    auto activate = [this, allowed, nodes, generation](bool stopped) {
        if (generation != scanGeneration) {
            return;
        }
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
        if (starting) {
            launchedDevices = allowed;
            launchedNodes = nodes;
        }
        unit.start([this, allowed, nodes, starting, generation](bool success) {
            if (generation != scanGeneration) {
                return;
            }
            if (!success) {
                fail("Unable to start the plugin's OpenRGB unit through the session bus");
            } else {
                launchedDevices = allowed;
                launchedNodes = nodes;
                if (recovering && !recoveryRestarted) {
                    scanning = false;
                    recover();
                    return;
                }
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
    if (unit.owned()
        && (recoveryRestarted || allowed != launchedDevices || nodes != launchedNodes)) {
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
void OpenRgbWorker::fail(const QString &message, bool allowGrace)
{
    if (allowGrace && !reading.isEmpty() && (writtenMode >= 0 || saving)
        && !recovering) {
        // A transport failure can precede processed udev delivery. Give that
        // event one debounce interval to claim the interrupted write.
        pendingFailure = message;
        if (!writeFailure.isActive()) {
            writeFailure.start();
        }
        phase = Phase::Disconnected;
        timeout.stop();
        socket.abort();
        return;
    }
    if (allowGrace && recovering && (!recoveryRestarted || recoveryDirty)) {
        phase = Phase::Disconnected;
        timeout.stop();
        socket.abort();
        return;
    }
    ++scanGeneration;
    const bool recoveryFailed = recovering;
    recovering = false;
    recoveryRestarted = false;
    recoveryDirty = false;
    reconnecting.clear();
    recoveryDebounce.stop();
    recoveryDeadline.stop();
    writeFailure.stop();
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
        if (device.value("writable").toBool()
            || device.value("blocked_reason").toString()
                == "Device reconnected; restarting OpenRGB") {
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
    } else if (!recoveryFailed) {
        next();
    }
    if (recoveryFailed) {
        while (!requests.isEmpty()) {
            const auto applied = requests.head().applied;
            finish(applied.isEmpty() ? Protocol::Reply::failure("unavailable", message)
                                     : Protocol::Reply{applied, {}, {}});
        }
    }
}
void OpenRgbWorker::publish()
{
    timeout.stop();
    controllers = std::move(pendingControllers);
    pendingControllers.clear();
    scanning = false;
    phase = Phase::Idle;
    if (recovering && recoveryRestarted && !recoveryDirty) {
        recovering = false;
        recoveryRestarted = false;
        recoveryDeadline.stop();
        reconnecting.clear();
    }
    gates();
    state = recovering ? "blocked" : "ready";
    reason = recovering ? "Device reconnected; restarting OpenRGB" : QString();
    notify();
    if (recovering) {
        recover();
    } else {
        next();
    }
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
