// SPDX-License-Identifier: GPL-3.0-or-later
// Private session manager; never calls systemctl or launches a process.
#include <QCoreApplication>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusObjectPath>
#include <QDBusVirtualObject>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSocketNotifier>
#include <QTextStream>
#include <QTimer>
#include <optional>
#include <unistd.h>

namespace {
const QString path = "/org/freedesktop/systemd1";
const QString manager = "org.freedesktop.systemd1.Manager";
void output(const QJsonObject &value)
{
    QTextStream(stdout) << QJsonDocument(value).toJson(QJsonDocument::Compact) << Qt::endl;
}
}
class Fake final : public QDBusVirtualObject {
public:
    QDBusConnection bus;
    QJsonArray calls;
    bool hold = false, reject = false;
    QString result = "done";
    std::optional<QDBusMessage> held;
    uint serial = 0;
    explicit Fake(QDBusConnection bus) : bus(std::move(bus)) {}
    QString introspect(const QString &) const override { return {}; }
    void complete(const QDBusMessage &message)
    {
        if (reject) {
            bus.send(message.createErrorReply("org.freedesktop.DBus.Error.AccessDenied", "Denied"));
            return;
        }
        const auto id = ++serial;
        const QDBusObjectPath job("/org/freedesktop/systemd1/job/" + QString::number(id));
        bus.send(message.createReply(QVariantList{QVariant::fromValue(job)}));
        QTimer::singleShot(0, this, [this, id, job, message] {
            auto signal = QDBusMessage::createSignal(path, manager, "JobRemoved");
            signal << id << QVariant::fromValue(job) << message.arguments()[0].toString() << result;
            bus.send(signal);
        });
    }
    bool handleMessage(const QDBusMessage &message, const QDBusConnection &) override
    {
        if (message.interface() != manager) {
            return false;
        }
        if (message.member() == "Subscribe") {
            bus.send(message.createReply());
            return true;
        }
        if ((message.member() != "StartUnit" && message.member() != "StopUnit")
            || message.arguments().size() != 2) {
            return false;
        }
        calls.append(QJsonArray{message.member(), message.arguments()[0].toString(),
                                message.arguments()[1].toString()});
        message.setDelayedReply(true);
        if (hold) {
            held = message;
        } else {
            complete(message);
        }
        return true;
    }
    void command(const QJsonObject &value)
    {
        if (value.contains("hold")) {
            hold = value["hold"].toBool();
        }
        if (value.contains("reject")) {
            reject = value["reject"].toBool();
        }
        if (value.contains("result")) {
            result = value["result"].toString();
        }
        if (value["action"] == "release" && held) {
            complete(*held);
            held.reset();
        }
        output({{"calls", calls}, {"held", held.has_value()}});
    }
};
int main(int argc, char **argv)
{
    QCoreApplication application(argc, argv);
    Fake fake(QDBusConnection::connectToBus(QDBusConnection::SessionBus, "fake-systemd"));
    if (!fake.bus.registerVirtualObject(path, &fake)
        || !fake.bus.registerService("org.freedesktop.systemd1")) {
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
