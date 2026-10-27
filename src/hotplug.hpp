// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QObject>
#include <QString>
#include <QVector>
#include <QSocketNotifier>
#include <functional>
#include <memory>

struct udev;
struct udev_monitor;

struct HotplugEvent {
    QString action, node, identity, path;
};

class Hotplug final : public QObject {
public:
    explicit Hotplug(std::function<void(QVector<HotplugEvent>)> reconcile);
    ~Hotplug() override;
    bool active() const;

private:
    udev *context = nullptr;
    udev_monitor *monitor = nullptr;
    std::unique_ptr<QSocketNotifier> notifier;
    void drain(const std::function<void(QVector<HotplugEvent>)> &reconcile);
};
