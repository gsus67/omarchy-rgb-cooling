// SPDX-License-Identifier: GPL-3.0-or-later
#include "server.hpp"
#include "openrgb.hpp"
#include <QCoreApplication>
#include <QFile>
#include <QJsonArray>
#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

void PeerServer::incomingConnection(quintptr descriptor)
{
    if (accepted) {
        accepted(descriptor);
    } else {
        ::close(static_cast<int>(descriptor));
    }
}

Server::Server(bool demo, const QString &hwmonRoot) : demo(demo), hwmon(hwmonRoot)
{
    clock.start();
    socket.accepted = [this](qintptr descriptor) { accept(descriptor); };
    socket.setMaxPendingConnections(Protocol::MaxConnections);
    idleExit.setSingleShot(true);
    idleExit.setInterval(Protocol::ExitMilliseconds);
    idleExit.setTimerType(Qt::PreciseTimer);
    connect(&idleExit, &QTimer::timeout, qApp, &QCoreApplication::quit);
    idleExit.start();
    events.setInterval(50);
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
            if (events.isActive()) {
                nextSample = 0;
            }
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
    const auto encoded = QFile::encodeName(path);
    struct stat metadata {};
    if (::lstat(encoded.constData(), &metadata) == 0) {
        error = S_ISSOCK(metadata.st_mode) ? "Socket path already exists"
                                         : "Refusing to replace a non-socket file";
        return false;
    }
    if (errno != ENOENT) {
        error = QString::fromLocal8Bit(std::strerror(errno));
        return false;
    }
    // umask is set to 0077 in main before Qt creates any socket.
    socket.setSocketOptions(QLocalServer::UserAccessOption);
    if (!socket.listen(path)) {
        error = socket.errorString();
        return false;
    }
    if (::chmod(encoded.constData(), 0600) != 0) {
        error = "Could not restrict socket permissions";
        socket.close();
        return false;
    }
    initializeAdapters();
    return true;
}

bool Server::adopt(qintptr descriptor, QString &error)
{
    const int fd = static_cast<int>(descriptor);
    int type = 0;
    int accepting = 0;
    socklen_t length = sizeof(type);
    sockaddr_un address {};
    socklen_t addressLength = sizeof(address);
    if (::getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &length) != 0 || type != SOCK_STREAM
        || ::getsockopt(fd, SOL_SOCKET, SO_ACCEPTCONN, &accepting, &length) != 0 || !accepting
        || ::getsockname(fd, reinterpret_cast<sockaddr *>(&address), &addressLength) != 0
        || address.sun_family != AF_UNIX) {
        error = "Activation descriptor must be a listening Unix stream socket";
        return false;
    }
    const int flags = ::fcntl(fd, F_GETFD);
    if (flags < 0 || ::fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0
        || !socket.listen(descriptor)) {
        error = "Could not adopt activation socket";
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

QJsonObject Server::sensors() const
{
    return demo ? static_cast<DemoAdapter *>(adapter.get())->sensors()
                : hwmon.snapshot(sampleInterval);
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
        // With no sensor subscription this returns the cache, never a hidden polling read.
        reply.result = sensors();
    } else if (op == "devices") {
        reply.result = {{"devices", adapter->devices()}};
    } else if (op == "subscribe") {
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
        connection->topics.clear();
        connection->subscriptionChanged();
        subscriptionsChanged();
    } else if (op == "lighting.get") {
        reply = adapter->lighting(params.value("device").toString());
    } else if (op == "lighting.set") {
        if (!connection->allowLightingWrite()) {
            reply = Protocol::Reply::failure(
                "rate_limited", "At most 10 lighting.set requests per second");
        } else {
            reply = adapter->setLighting(params.value("device").toString(),
                                         params.value("color").toString(),
                                         params.value("brightness").toInt());
        }
    } else {
        reply = Protocol::Reply::failure("unknown_op", "Operation is not supported by API v1");
    }
    connection->send(Protocol::response(request.id, reply));
}

void Server::subscriptionsChanged()
{
    bool subscribed = false;
    int minimumInterval = 10000;
    bool sensorSubscriber = false;
    for (const auto *connection : clients) {
        subscribed = subscribed || !connection->topics.isEmpty();
        if (connection->topics.contains("sensors")) {
            minimumInterval = std::min(minimumInterval, connection->intervalMilliseconds);
            sensorSubscriber = true;
        }
    }
    if (sensorSubscriber) {
        sampleInterval = minimumInterval;
        nextSample = 0;
    }
    if (subscribed) {
        events.start();
    } else {
        events.stop();
    }
}

void Server::tick()
{
    bool sensorSubscriber = false;
    for (const auto *connection : clients) {
        sensorSubscriber = sensorSubscriber || connection->topics.contains("sensors");
    }
    const qint64 now = clock.elapsed();
    if (!demo && sensorSubscriber && now >= nextSample) {
        hwmon.sample(sampleInterval);
        nextSample = now + sampleInterval;
    }
    // Copy the set: sending to a stalled peer may synchronously disconnect it.
    const auto peers = clients;
    for (auto *connection : peers) {
        if (!clients.contains(connection) || connection->nextEvent > now) {
            continue;
        }
        connection->nextEvent = now + connection->intervalMilliseconds;
        if (connection->topics.contains("sensors")) {
            connection->send(Protocol::event("sensors", sensors()));
        }
        if (connection->topics.contains("devices")) {
            connection->send(Protocol::event("devices", {{"devices", adapter->devices()}}));
        }
    }
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
