// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb_unit.hpp"
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusObjectPath>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QMap>
#include <optional>
#include <utility>

namespace {
const QString service = "org.freedesktop.systemd1";
const QString path = "/org/freedesktop/systemd1";
const QString manager = "org.freedesktop.systemd1.Manager";
const QString unit = "omarchy-rgb-cooling-openrgb.service";
const QString unitPath = path + "/unit/omarchy_2drgb_2dcooling_2dopenrgb_2eservice";
}

class OpenRgbUnitWorker final : public QObject {
    Q_OBJECT
public:
    OpenRgbUnit *owner;
    std::optional<QDBusConnection> bus;
    QTimer idle;
    bool active = false, subscribed = false, registered = false, starting = false;
    QString job;
    QMap<QString, QString> completed;
    std::function<void(bool)> pending;

    explicit OpenRgbUnitWorker(OpenRgbUnit *owner) : QObject(owner), owner(owner)
    {
        idle.setParent(this);
        idle.setSingleShot(true);
        idle.setInterval(120000);
        idle.setTimerType(Qt::PreciseTimer);
        connect(&idle, &QTimer::timeout, this, [this] {
            if (active && !subscribed && !pending) {
                stop([this](bool success) {
                    if (success && this->owner->stopped) {
                        this->owner->stopped();
                    }
                });
            }
        });
    }

    QDBusMessage call(const QString &method)
    {
        auto message = QDBusMessage::createMethodCall(service, path, manager, method);
        message.setAutoStartService(false);
        return message;
    }

    void finish(bool success)
    {
        if (success) {
            active = starting;
        }
        job.clear();
        completed.clear();
        if (success && active && !subscribed) {
            idle.start();
        }
        auto callback = std::exchange(pending, {});
        if (callback) {
            callback(success);
        }
        if (owner->settled) {
            owner->settled();
        }
    }

    void start(std::function<void(bool)> ready)
    {
        if (active) {
            ready(true);
            return;
        }
        if (pending) {
            ready(false);
            return;
        }
        pending = std::move(ready);
        starting = true;
        if (!bus) {
            // A stalled bus handshake stays on the RGB worker, outside the API event loop.
            bus.emplace(QDBusConnection::connectToBus(QDBusConnection::SessionBus, "rgbcd-unit"));
            bus->connect(service, path, manager, "JobRemoved", this,
                         SLOT(jobRemoved(uint,QDBusObjectPath,QString,QString)));
            bus->connect(service, unitPath, "org.freedesktop.DBus.Properties",
                         "PropertiesChanged", this,
                         SLOT(propertiesChanged(QString,QVariantMap,QStringList)));
        }
        if (!bus->isConnected()) {
            finish(false);
            return;
        }
        if (registered) {
            sendJob("StartUnit");
            return;
        }
        auto *watcher = new QDBusPendingCallWatcher(bus->asyncCall(call("Subscribe"), 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher] {
            const QDBusPendingReply<> reply = *watcher;
            watcher->deleteLater();
            if (reply.isError()) {
                finish(false);
                return;
            }
            registered = true;
            sendJob("StartUnit");
        });
    }

    void stop(std::function<void(bool)> ready)
    {
        if (!active) {
            ready(true);
            return;
        }
        if (pending) {
            ready(false);
            return;
        }
        idle.stop();
        pending = std::move(ready);
        starting = false;
        sendJob("StopUnit");
    }

    void sendJob(const QString &method)
    {
        auto message = call(method);
        message << unit << QString("replace");
        auto *watcher = new QDBusPendingCallWatcher(bus->asyncCall(message, 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher] {
            const QDBusPendingReply<QDBusObjectPath> reply = *watcher;
            watcher->deleteLater();
            if (reply.isError()) {
                finish(false);
                return;
            }
            job = reply.value().path();
            if (completed.contains(job)) {
                finish(completed.value(job) == "done");
            } else {
                // An absolute job deadline, no polling or reconnect/retry.
                QTimer::singleShot(10000, this, [this, expected = job] {
                    if (pending && job == expected) {
                        finish(false);
                    }
                });
            }
        });
    }

private slots:
    void jobRemoved(uint, const QDBusObjectPath &removed, const QString &name,
                    const QString &result)
    {
        if (!pending || name != unit) {
            return;
        }
        if (removed.path() == job) {
            finish(result == "done");
        } else if (completed.size() < 64) {
            completed.insert(removed.path(), result);
        }
    }
    void propertiesChanged(const QString &interface, const QVariantMap &values,
                           const QStringList &invalidated)
    {
        if (interface != "org.freedesktop.systemd1.Unit" || pending || !active) {
            return;
        }
        const auto state = values.value("ActiveState").toString();
        if ((!state.isEmpty() && state != "active" && state != "activating")
            || invalidated.contains("ActiveState")) {
            active = false;
            idle.stop();
            if (owner->stopped) {
                owner->stopped();
            }
        }
    }
};

OpenRgbUnit::OpenRgbUnit(QObject *parent) : QObject(parent), worker(new OpenRgbUnitWorker(this)) {}
OpenRgbUnit::~OpenRgbUnit()
{
    worker.reset();
    QDBusConnection::disconnectFromBus("rgbcd-unit");
}
void OpenRgbUnit::start(std::function<void(bool)> ready) { worker->start(std::move(ready)); }
void OpenRgbUnit::stop(std::function<void(bool)> ready) { worker->stop(std::move(ready)); }
bool OpenRgbUnit::owned() const { return worker->active; }
bool OpenRgbUnit::transitioning() const { return bool(worker->pending); }
void OpenRgbUnit::activity()
{
    if (worker->active && !worker->subscribed) {
        worker->idle.start();
    }
}
void OpenRgbUnit::setSubscribed(bool value)
{
    if (worker->subscribed == value) {
        return;
    }
    worker->subscribed = value;
    if (value) {
        worker->idle.stop();
    } else {
        activity();
    }
}
#include "openrgb_unit.moc"
