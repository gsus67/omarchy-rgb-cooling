// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "hwmon.hpp"
#include <QElapsedTimer>
#include <QObject>
#include <QThread>
#include <functional>
#include <vector>

// All filesystem access stays on a worker; simultaneous requests share one sample.
class SensorSource final : public QObject {
public:
    explicit SensorSource(const QString &root);
    ~SensorSource() override;
    using Callback = std::function<void(const QJsonObject &)>;
    void request(int intervalMilliseconds, Callback ready);
    void invalidate();

private:
    QThread thread;
    QObject *worker;
    Hwmon hwmon;
    QElapsedTimer age;
    QJsonObject cached;
    bool sampling = false;
    quint64 generation = 0;
    std::vector<Callback> pending;
};
