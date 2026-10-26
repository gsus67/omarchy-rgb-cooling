// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "adapter.hpp"
#include "connection.hpp"
#include "demo.hpp"
#include "hotplug.hpp"
#include "hwmon.hpp"
#include <QElapsedTimer>
#include <QLocalServer>
#include <QSet>
#include <QTimer>
#include <functional>
#include <memory>
#include <sys/types.h>

class PeerServer final : public QLocalServer {
public:
    std::function<void(qintptr)> accepted;

protected:
    void incomingConnection(quintptr descriptor) override;
};

class Server final : public QObject {
public:
    Server(bool demo, const QString &hwmonRoot);
    ~Server() override;
    bool listen(const QString &path, QString &error);
    bool adopt(qintptr descriptor, QString &error);
    static bool peerAllowed(qintptr descriptor, uid_t owner);

private:
    PeerServer socket;
    bool demo;
    Hwmon hwmon;
    std::unique_ptr<LightingAdapter> adapter;
    std::unique_ptr<Hotplug> hotplug;
    QSet<Connection *> clients;
    QElapsedTimer clock;
    QTimer events;
    QTimer idleExit;
    qint64 nextSample = 0;
    int sampleInterval = 2000;
    void initializeAdapters();
    void accept(qintptr descriptor);
    void dispatch(Connection *connection, const Protocol::Request &request);
    void subscriptionsChanged();
    void tick();
    void devicesChanged();
    QJsonObject sensors() const;
};
