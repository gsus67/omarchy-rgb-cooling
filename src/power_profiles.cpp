// SPDX-License-Identifier: GPL-3.0-or-later
#include "power_profiles.hpp"
#include <QDBusArgument>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusVariant>
#include <QJsonArray>
#include <QQueue>
#include <QVariantMap>
#include <memory>
#include <utility>

namespace {
const QString service = "org.freedesktop.UPower.PowerProfiles";
const QString path = "/org/freedesktop/UPower/PowerProfiles";
const QString properties = "org.freedesktop.DBus.Properties";

bool knownProfile(const QString &profile)
{
    return profile == "power-saver" || profile == "balanced" || profile == "performance";
}

Protocol::Reply unavailable()
{
    return Protocol::Reply::failure("unavailable", "Power profiles daemon is unavailable");
}

Protocol::Reply snapshot(const QVariantMap &values)
{
    const QString active = values.value("ActiveProfile").toString();
    const auto profiles = qdbus_cast<QList<QVariantMap>>(values.value("Profiles"));
    QJsonArray available;
    for (const auto &entry : profiles) {
        const QString profile = entry.value("Profile").toString();
        if (knownProfile(profile) && !available.contains(profile)) {
            available.append(profile);
        }
    }
    if (!knownProfile(active) || !available.contains(active)
        || values.value("PerformanceDegraded").metaType() != QMetaType::fromType<QString>()) {
        return unavailable();
    }
    return {{{"profile", active}, {"available", available},
             {"degraded", values.value("PerformanceDegraded").toString()}}, {}, {}};
}
}

class PowerProfilesWorker final : public QObject {
    Q_OBJECT
public:
    using Callback = PowerProfiles::Callback;
    std::function<void(const QJsonObject &)> changed;

    ~PowerProfilesWorker() override { disconnectBus(); }

    void subscribe(bool value)
    {
        subscribed = value;
        if (subscribed) {
            connectBus();
        } else {
            release();
        }
    }

    void request(const QString &profile, Callback ready)
    {
        requests.enqueue({profile, std::move(ready)});
        if (requests.size() == 1) {
            next();
        }
    }

private:
    struct Request {
        QString profile;
        Callback ready;
    };
    QQueue<Request> requests;
    std::unique_ptr<QDBusConnection> bus;
    QString connectionName;
    bool subscribed = false;
    int reads = 0;
    quint64 generation = 0;

    void connectBus()
    {
        if (bus) {
            return;
        }
        connectionName = QString("rgbcd-profiles-%1").arg(++generation);
        bus = std::make_unique<QDBusConnection>(
            QDBusConnection::connectToBus(QDBusConnection::SystemBus, connectionName));
        bus->connect(service, path, properties, "PropertiesChanged", this,
                     SLOT(propertiesChanged(QString,QVariantMap,QStringList)));
    }

    void disconnectBus()
    {
        if (bus) {
            bus.reset();
            QDBusConnection::disconnectFromBus(connectionName);
        }
    }

    void release()
    {
        if (!subscribed && requests.isEmpty() && reads == 0) {
            disconnectBus();
        }
    }

    void read(Callback ready)
    {
        if (!bus->isConnected()) {
            ready(unavailable());
            release();
            return;
        }
        ++reads;
        auto message = QDBusMessage::createMethodCall(service, path, properties, "GetAll");
        message.setAutoStartService(false);
        message << service;
        auto *watcher = new QDBusPendingCallWatcher(bus->asyncCall(message, 3000), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this,
                [this, watcher, ready = std::move(ready)] {
            const QDBusPendingReply<QVariantMap> reply = *watcher;
            watcher->deleteLater();
            --reads;
            ready(reply.isError() ? unavailable() : snapshot(reply.value()));
            release();
        });
    }

    void finish(const Protocol::Reply &reply)
    {
        auto request = requests.dequeue();
        request.ready(reply);
        if (!requests.isEmpty()) {
            next();
        }
        release();
    }

    void next()
    {
        connectBus();
        read([this](const Protocol::Reply &reply) {
            const QString profile = requests.head().profile;
            if (!reply.ok() || profile.isEmpty()) {
                finish(reply);
                return;
            }
            if (!reply.result.value("available").toArray().contains(profile)) {
                finish(Protocol::Reply::failure("bad_request", "Profile is not available"));
                return;
            }
            auto message = QDBusMessage::createMethodCall(service, path, properties, "Set");
            message.setAutoStartService(false);
            message << service << QString("ActiveProfile")
                    << QVariant::fromValue(QDBusVariant(profile));
            auto *watcher = new QDBusPendingCallWatcher(bus->asyncCall(message, 3000), this);
            connect(watcher, &QDBusPendingCallWatcher::finished, this, [this, watcher, profile] {
                const QDBusPendingReply<> written = *watcher;
                watcher->deleteLater();
                if (written.isError()) {
                    const auto code = written.error().type() == QDBusError::AccessDenied
                        ? "blocked" : "unavailable";
                    finish(Protocol::Reply::failure(code, "Power profile change failed"));
                    return;
                }
                read([this, profile](const Protocol::Reply &confirmed) {
                    finish(confirmed.ok() && confirmed.result.value("profile") != profile
                               ? unavailable() : confirmed);
                });
            });
        });
    }

private slots:
    void propertiesChanged(const QString &interface, const QVariantMap &values,
                           const QStringList &invalidated)
    {
        if (!subscribed || interface != service) {
            return;
        }
        for (const auto &key : {"ActiveProfile", "Profiles", "PerformanceDegraded"}) {
            if (values.contains(key) || invalidated.contains(key)) {
                // Re-read once per signal, including invalidated properties, never on a timer.
                read([this](const Protocol::Reply &reply) {
                    if (subscribed && reply.ok()) {
                        changed(reply.result);
                    }
                });
                return;
            }
        }
    }
};

PowerProfiles::PowerProfiles(std::function<void(const QJsonObject &)> changed)
    : worker(new PowerProfilesWorker)
{
    worker->changed = [this, changed = std::move(changed)](const auto &data) {
        QMetaObject::invokeMethod(this, [changed, data] { changed(data); }, Qt::QueuedConnection);
    };
    worker->moveToThread(&thread);
    connect(&thread, &QThread::finished, worker, &QObject::deleteLater);
    thread.start();
}

PowerProfiles::~PowerProfiles()
{
    thread.quit();
    thread.wait();
}

void PowerProfiles::request(const QString &profile, Callback ready)
{
    QMetaObject::invokeMethod(worker, [this, profile, ready = std::move(ready)] {
        worker->request(profile, [this, ready](const auto &reply) {
            QMetaObject::invokeMethod(this, [ready, reply] { ready(reply); }, Qt::QueuedConnection);
        });
    }, Qt::QueuedConnection);
}

void PowerProfiles::setSubscribed(bool subscribed)
{
    QMetaObject::invokeMethod(worker, [this, subscribed] { worker->subscribe(subscribed); },
                              Qt::QueuedConnection);
}

#include "power_profiles.moc"
