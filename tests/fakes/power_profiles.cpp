// SPDX-License-Identifier: GPL-3.0-or-later
// Private D-Bus service; stdin JSON controls external changes and delayed Set replies.
#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusMetaType>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusVariant>
#include <QDBusVirtualObject>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QTextStream>
#include <optional>
#include <unistd.h>

namespace {
const QString service = "org.freedesktop.UPower.PowerProfiles";
const QString path = "/org/freedesktop/UPower/PowerProfiles";
const QString properties = "org.freedesktop.DBus.Properties";

void output(const QJsonObject &value)
{
    QTextStream(stdout) << QJsonDocument(value).toJson(QJsonDocument::Compact) << Qt::endl;
}
}

class Fake final : public QDBusVirtualObject {
public:
    QDBusConnection bus;
    QString active = "balanced";
    QStringList available{"power-saver", "balanced", "performance"};
    QString degraded;
    int gets = 0;
    int sets = 0;
    bool hold = false;
    bool ignore = false;
    bool reject = false;
    std::optional<QDBusMessage> held;
    explicit Fake(QDBusConnection connection) : bus(std::move(connection)) {}

    QVariantMap values() const
    {
        QList<QVariantMap> profiles;
        for (const auto &profile : available) {
            profiles.append({{"Profile", profile}, {"Driver", "test"}});
        }
        return {{"ActiveProfile", active}, {"Profiles", QVariant::fromValue(profiles)},
                {"PerformanceDegraded", degraded}};
    }

    QString introspect(const QString &) const override { return {}; }

    void signal(bool invalidated = false)
    {
        auto message = QDBusMessage::createSignal(path, properties, "PropertiesChanged");
        message << service << (invalidated ? QVariantMap{} : values())
                << (invalidated ? QStringList{"ActiveProfile", "Profiles", "PerformanceDegraded"}
                                : QStringList{});
        bus.send(message);
    }

    void apply(const QDBusMessage &message)
    {
        if (reject) {
            bus.send(message.createErrorReply("org.freedesktop.DBus.Error.AccessDenied", "Denied"));
            return;
        }
        if (!ignore) {
            active = qvariant_cast<QDBusVariant>(message.arguments().at(2)).variant().toString();
            signal();
        }
        bus.send(message.createReply());
    }

    bool handleMessage(const QDBusMessage &message, const QDBusConnection &) override
    {
        if (message.interface() != properties || message.arguments().isEmpty()
            || message.arguments().first().toString() != service) {
            return false;
        }
        if (message.member() == "GetAll") {
            ++gets;
            bus.send(message.createReply(QVariantList{values()}));
            return true;
        }
        if (message.member() == "Set" && message.arguments().size() == 3
            && message.arguments().at(1).toString() == "ActiveProfile") {
            ++sets;
            message.setDelayedReply(true);
            if (hold) {
                held = message;
            } else {
                apply(message);
            }
            return true;
        }
        return false;
    }

    void command(const QJsonObject &command)
    {
        if (command.value("action") == "names") {
            auto message = QDBusMessage::createMethodCall("org.freedesktop.DBus",
                "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames");
            auto *watcher = new QDBusPendingCallWatcher(bus.asyncCall(message), this);
            QObject::connect(watcher, &QDBusPendingCallWatcher::finished, this, [watcher] {
                const QDBusPendingReply<QStringList> reply = *watcher;
                output({{"names", QJsonArray::fromStringList(reply.value())}});
                watcher->deleteLater();
            });
            return;
        }
        if (command.contains("available")) {
            available.clear();
            for (const auto &profile : command.value("available").toArray()) {
                available.append(profile.toString());
            }
        }
        if (command.contains("profile")) {
            active = command.value("profile").toString();
        }
        if (command.contains("degraded")) {
            degraded = command.value("degraded").toString();
        }
        if (command.contains("hold")) {
            hold = command.value("hold").toBool();
        }
        if (command.contains("ignore")) {
            ignore = command.value("ignore").toBool();
        }
        if (command.contains("reject")) {
            reject = command.value("reject").toBool();
        }
        if (command.value("action") == "release" && held) {
            apply(*held);
            held.reset();
        }
        if (command.value("action") == "change") {
            signal(command.value("invalidated").toBool());
        }
        output({{"gets", gets}, {"sets", sets}, {"held", held.has_value()}});
    }
};

int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    qDBusRegisterMetaType<QList<QVariantMap>>();
    Fake fake(QDBusConnection::connectToBus(QDBusConnection::SystemBus, "fake-profiles"));
    if (!fake.bus.registerVirtualObject(path, &fake) || !fake.bus.registerService(service)) {
        return 1;
    }
    QSocketNotifier input(STDIN_FILENO, QSocketNotifier::Read);
    QByteArray buffer;
    QObject::connect(&input, &QSocketNotifier::activated, &application, [&] {
        char bytes[4096];
        const auto size = ::read(STDIN_FILENO, bytes, sizeof(bytes));
        if (size <= 0) {
            application.quit();
            return;
        }
        buffer.append(bytes, size);
        while (buffer.contains('\n')) {
            const auto end = buffer.indexOf('\n');
            fake.command(QJsonDocument::fromJson(buffer.left(end)).object());
            buffer.remove(0, end + 1);
        }
    });
    output({{"ready", true}});
    return application.exec();
}
