// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "adapter.hpp"
#include "hotplug.hpp"
#include <QObject>
#include <QThread>
#include <functional>

class OpenRgbWorker;
class OpenRgbAdapter final : public QObject, public LightingAdapter {
public:
    using Callback = std::function<void(const Protocol::Reply &)>;
    OpenRgbAdapter(std::function<void()> changed, const QString &sysRoot,
                   const QString &rules);
    ~OpenRgbAdapter() override;
    QJsonObject engine() const override;
    QJsonArray devices() const override;
    Protocol::Reply lighting(const QString &device) const override;
    Protocol::Reply updateLighting(const QJsonObject &params) override;
    Protocol::Reply saveLighting(const QString &device) override;
    Protocol::Reply setLighting(const QString &, const QString &, int) override;
    void perform(const QString &operation, const QJsonObject &params, Callback ready);
    void refresh();
    void hotplug(const QVector<HotplugEvent> &events, bool discover);
    void wake();
    void setSubscribed(bool value);
    bool running() const;
    static bool decodeController(const QByteArray &, unsigned, QJsonObject &, QJsonObject &);

private:
    QThread thread;
    OpenRgbWorker *worker;
    QJsonObject cachedEngine;
    QJsonArray cachedDevices;
    bool active = false;
};
