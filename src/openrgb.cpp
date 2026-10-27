// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb_worker.hpp"
#include <QMetaObject>
#include <utility>

OpenRgbAdapter::OpenRgbAdapter(std::function<void()> changed, const QString &root,
                               const QString &rules)
    : worker(new OpenRgbWorker(root, rules))
{
    cachedEngine = {{"id", "openrgb"}, {"state", "absent"},
                    {"reason", "OpenRGB has not been requested"}};
    worker->changed = [this, changed](auto engine, auto devices, bool running) {
        QMetaObject::invokeMethod(this, [this, changed, engine, devices, running] {
            cachedEngine = engine;
            cachedDevices = devices;
            active = running;
            changed();
        }, Qt::QueuedConnection);
    };
    worker->moveToThread(&thread);
    connect(&thread, &QThread::finished, worker, &QObject::deleteLater);
    thread.start();
}

OpenRgbAdapter::~OpenRgbAdapter()
{
    thread.quit();
    thread.wait();
}
QJsonObject OpenRgbAdapter::engine() const { return cachedEngine; }
QJsonArray OpenRgbAdapter::devices() const { return cachedDevices; }
bool OpenRgbAdapter::running() const { return active; }
Protocol::Reply OpenRgbAdapter::lighting(const QString &) const
{
    return Protocol::Reply::failure("unavailable", "Use asynchronous lighting requests");
}
Protocol::Reply OpenRgbAdapter::setLighting(const QString &, const QString &, int)
{
    return Protocol::Reply::failure("unavailable", "Use asynchronous lighting requests");
}
void OpenRgbAdapter::perform(const QString &op, const QJsonObject &params, Callback ready)
{
    QMetaObject::invokeMethod(worker, [this, op, params, ready = std::move(ready)] {
        worker->perform(op, params, [this, ready](const auto &reply) {
            QMetaObject::invokeMethod(this, [ready, reply] { ready(reply); }, Qt::QueuedConnection);
        });
    }, Qt::QueuedConnection);
}
void OpenRgbAdapter::refresh()
{
    QMetaObject::invokeMethod(worker, [this] { worker->refresh(); }, Qt::QueuedConnection);
}
void OpenRgbAdapter::setSubscribed(bool value)
{
    QMetaObject::invokeMethod(worker, [this, value] { worker->subscribed(value); },
                              Qt::QueuedConnection);
}

void OpenRgbAdapter::wake()
{
    QMetaObject::invokeMethod(worker, [] {}, Qt::QueuedConnection);
}
