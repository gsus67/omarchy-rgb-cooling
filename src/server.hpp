// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "adapter.hpp"
#include "connection.hpp"
#include "demo.hpp"
#include "hotplug.hpp"
#include "listener.hpp"
#include "power_profiles.hpp"
#include "sensor_source.hpp"
#include <QElapsedTimer>
#include <QSet>
#include <QTimer>
#include <functional>
#include <memory>
#include <sys/types.h>

class Server final : public QObject {
public:
    Server(bool demo, const QString &hwmonRoot, const QString &dataDirectory,
           const QString &dmiRoot);
    ~Server() override;
    bool listen(const QString &path, QString &error);
    bool adopt(qintptr descriptor, QString &error);
    static bool peerAllowed(qintptr descriptor, uid_t owner);

private:
    Listener socket;
    bool demo;
    SensorSource sensorSource;
    PowerProfiles powerProfiles;
    std::unique_ptr<LightingAdapter> adapter;
    std::unique_ptr<Hotplug> hotplug;
    QSet<Connection *> clients;
    QElapsedTimer clock;
    QElapsedTimer demoScan;
    bool deviceSubscriber = false;
    QTimer events;
    QTimer idleExit;
    int sampleInterval = 2000;
    void initializeAdapters();
    void accept(qintptr descriptor);
    void dispatch(Connection *connection, const Protocol::Request &request);
    void dispatchLighting(Connection *connection, const Protocol::Request &request);
    void subscriptionsChanged();
    void tick();
    void devicesChanged();
    void profileChanged(const QJsonObject &data);
    void scheduleEvents();
    void readSensors(SensorSource::Callback ready);
};
