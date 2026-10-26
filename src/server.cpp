// SPDX-License-Identifier: GPL-3.0-or-later
#include "server.hpp"
#include "openrgb.hpp"
#include <QCoreApplication>
#include <QJsonArray>
#include <QPointer>
#include <algorithm>
#include <limits>
#include <utility>
#include <sys/socket.h>
#include <unistd.h>

Server::Server(bool demo, const QString &hwmonRoot) : demo(demo), sensorSource(hwmonRoot)
{
    clock.start();
    socket.accepted = [this](qintptr descriptor) { accept(descriptor); };
    idleExit.setSingleShot(true);
    idleExit.setInterval(Protocol::ExitMilliseconds);
    idleExit.setTimerType(Qt::PreciseTimer);
    connect(&idleExit, &QTimer::timeout, qApp, &QCoreApplication::quit);
    idleExit.start();
    events.setSingleShot(true);
    events.setTimerType(Qt::PreciseTimer);
    connect(&events, &QTimer::timeout, this, [this] { tick(); });
}

void Server::initializeAdapters()
{
    // No engine connection is attempted until the local endpoint has been validated.
    if (demo) {
        adapter = std::make_unique<DemoAdapter>();
    } else {
        adapter = std::make_unique<OpenRgbAdapter>([this] { devicesChanged(); });
        hotplug = std::make_unique<Hotplug>([this] {
            sensorSource.invalidate();
            static_cast<OpenRgbAdapter *>(adapter.get())->refresh();
        });
    }
}

Server::~Server()
{
    // Connections are QObject children, but callbacks must stop before members disappear.
    for (auto *connection : clients) {
        connection->closed = {};
        connection->requestReceived = {};
        delete connection;
    }
    clients.clear();
}

bool Server::listen(const QString &path, QString &error)
{
    if (!socket.listen(path, error)) {
        return false;
    }
    initializeAdapters();
    return true;
}

bool Server::adopt(qintptr descriptor, QString &error)
{
    if (!socket.adopt(descriptor, error)) {
        return false;
    }
    initializeAdapters();
    return true;
}

bool Server::peerAllowed(qintptr descriptor, uid_t owner)
{
    struct ucred credentials {};
    socklen_t length = sizeof(credentials);
    return ::getsockopt(static_cast<int>(descriptor), SOL_SOCKET, SO_PEERCRED,
                        &credentials, &length) == 0
        && length == sizeof(credentials) && credentials.uid == owner;
}

void Server::accept(qintptr descriptor)
{
    // Check native credentials before giving the fd to Qt, which could buffer bytes.
    if (!peerAllowed(descriptor, ::getuid()) || clients.size() >= Protocol::MaxConnections) {
        ::close(static_cast<int>(descriptor));
        return;
    }
    auto *connection = new Connection(descriptor, this);
    clients.insert(connection);
    idleExit.stop();
    connection->requestReceived = [this](auto *peer, const auto &request) {
        dispatch(peer, request);
    };
    connection->closed = [this](auto *peer) {
        clients.remove(peer);
        subscriptionsChanged();
        if (clients.isEmpty()) {
            idleExit.start();
        }
    };
    connection->start();
}

void Server::readSensors(SensorSource::Callback ready)
{
    if (demo) {
        ready(static_cast<DemoAdapter *>(adapter.get())->sensors());
    } else {
        sensorSource.request(sampleInterval, std::move(ready));
    }
}

void Server::dispatch(Connection *connection, const Protocol::Request &request)
{
    Protocol::Reply reply;
    const auto &op = request.operation;
    const auto &params = request.params;
    if (op == "hello") {
        reply.result = {{"version", "0.1.0"}, {"api", 1}, {"demo", demo}};
    } else if (op == "status") {
        reply.result = {{"engines", QJsonArray{adapter->engine()}},
                        {"uptime_s", clock.elapsed() / 1000}};
    } else if (op == "sensors") {
        readSensors([peer = QPointer(connection), id = request.id](const auto &data) {
            if (peer) {
                peer->send(Protocol::response(id, {data, {}, {}}));
            }
        });
        return;
    } else if (op == "subscribe") {
        ++connection->subscriptionRevision;
        connection->topics.clear();
        for (const auto &topic : params.value("topics").toArray()) {
            connection->topics.insert(topic.toString());
        }
        const double interval = params.value("interval_ms").toDouble(2000);
        connection->intervalMilliseconds = static_cast<int>(std::clamp(interval, 500.0, 10000.0));
        connection->nextEvent = clock.elapsed();
        connection->subscriptionChanged();
        subscriptionsChanged();
    } else if (op == "unsubscribe") {
        ++connection->subscriptionRevision;
        connection->topics.clear();
        connection->subscriptionChanged();
        subscriptionsChanged();
    } else if (op == "devices" || op == "lighting.get" || op == "lighting.set") {
        if (op == "lighting.set" && !connection->allowLightingWrite()) {
            reply = Protocol::Reply::failure(
                "rate_limited", "At most 10 lighting.set requests per second");
        } else {
            auto ready = [this, peer = QPointer(connection), request] {
                if (!peer || !clients.contains(peer)) {
                    return;
                }
                Protocol::Reply result;
                const auto &params = request.params;
                if (request.operation == "devices") {
                    result.result = {{"devices", adapter->devices()}};
                } else if (request.operation == "lighting.get") {
                    result = adapter->lighting(params.value("device").toString());
                } else {
                    result = adapter->setLighting(params.value("device").toString(),
                        params.value("color").toString(), params.value("brightness").toInt());
                }
                peer->send(Protocol::response(request.id, result));
            };
            if (demo) {
                ready();
            } else {
                static_cast<OpenRgbAdapter *>(adapter.get())->request(std::move(ready));
            }
            return;
        }
    } else {
        reply = Protocol::Reply::failure("unknown_op", "Operation is not supported by API v1");
    }
    connection->send(Protocol::response(request.id, reply));
}

void Server::subscriptionsChanged()
{
    sampleInterval = 10000;
    bool deviceSubscriber = false;
    for (const auto *connection : clients) {
        if (connection->topics.contains("sensors")) {
            sampleInterval = std::min(sampleInterval, connection->intervalMilliseconds);
        }
        deviceSubscriber = deviceSubscriber || connection->topics.contains("devices");
    }
    if (!demo) {
        static_cast<OpenRgbAdapter *>(adapter.get())->setInterested(deviceSubscriber);
    }
    scheduleEvents();
}

void Server::scheduleEvents()
{
    events.stop();
    qint64 earliest = std::numeric_limits<qint64>::max();
    for (const auto *connection : clients) {
        if (!connection->topics.isEmpty()) {
            earliest = std::min(earliest, connection->nextEvent);
        }
    }
    if (earliest != std::numeric_limits<qint64>::max()) {
        events.start(static_cast<int>(std::max(qint64(0), earliest - clock.elapsed())));
    }
}

void Server::tick()
{
    const qint64 now = clock.elapsed();
    // Copy the set: sending to a stalled peer may synchronously disconnect it.
    const auto peers = clients;
    for (auto *connection : peers) {
        if (!clients.contains(connection) || connection->topics.isEmpty()
            || connection->nextEvent > now) {
            continue;
        }
        connection->nextEvent = now + connection->intervalMilliseconds;
        if (connection->topics.contains("sensors")) {
            const auto revision = connection->subscriptionRevision;
            readSensors([this, peer = QPointer(connection), revision](const auto &data) {
                if (peer && clients.contains(peer) && peer->topics.contains("sensors")
                    && peer->subscriptionRevision == revision) {
                    peer->send(Protocol::event("sensors", data));
                }
            });
        }
        if (clients.contains(connection) && connection->topics.contains("devices")) {
            connection->send(Protocol::event("devices", {{"devices", adapter->devices()}}));
        }
    }
    scheduleEvents();
}

void Server::devicesChanged()
{
    if (!adapter) {
        return;
    }
    const auto peers = clients;
    for (auto *connection : peers) {
        if (clients.contains(connection) && connection->topics.contains("devices")) {
            connection->send(Protocol::event("devices", {{"devices", adapter->devices()}}));
        }
    }
}
