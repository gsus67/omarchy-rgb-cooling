// SPDX-License-Identifier: GPL-3.0-or-later
#include "hwmon.hpp"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QRegularExpression>
#include <QSet>
#include <cmath>
#include <utility>

Hwmon::Hwmon(QString root) : root(std::move(root))
{
    clock.start();
}

QString Hwmon::readText(const QString &path)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return {};
    }
    return QString::fromUtf8(file.read(4096)).trimmed();
}

QString Hwmon::devicePath(const QString &directory) const
{
    QString canonical = QFileInfo(directory + "/device").canonicalFilePath();
    if (canonical.isEmpty()) {
        canonical = QFileInfo(directory).canonicalFilePath();
        const auto suffix = canonical.lastIndexOf("/hwmon/");
        if (suffix >= 0) {
            canonical.truncate(suffix);
        } else if (QFileInfo(canonical).fileName().startsWith("hwmon")) {
            canonical = QFileInfo(canonical).dir().absolutePath();
        }
    }
    // A class number is never an identity. Refuse fixtures/nodes without a parent.
    if (canonical.isEmpty() || QFileInfo(canonical).fileName().startsWith("hwmon")) {
        return {};
    }
    const auto devices = canonical.indexOf("/devices/");
    return devices >= 0 ? canonical.mid(devices + 9) : canonical;
}

void Hwmon::sample(int intervalMilliseconds)
{
    Q_UNUSED(intervalMilliseconds);
    QSet<QString> present;
    const QDir directory(root);
    const auto entries = directory.entryList({"hwmon*"}, QDir::Dirs | QDir::NoDotAndDotDot,
                                            QDir::Name);
    static const QRegularExpression channelPattern("^(temp|fan)[0-9]+_(input|label)$");
    for (const auto &entry : entries) {
        const QString path = directory.filePath(entry);
        const QString name = readText(path + "/name");
        const QString device = devicePath(path);
        if (name.isEmpty() || device.isEmpty()) {
            continue;
        }
        const auto inputs = QDir(path).entryList(QDir::Files, QDir::Name);
        for (const auto &input : inputs) {
            const auto match = channelPattern.match(input);
            if (!match.hasMatch()) {
                continue;
            }
            const QString channel = input.left(input.lastIndexOf('_'));
            const QString id = name + ":" + device + ":" + channel;
            if (!sensors.contains(id) && sensors.size() >= 4096) {
                continue;
            }
            Sensor &sensor = sensors[id];
            sensor.id = id;
            sensor.device = name + ":" + device;
            sensor.kind = match.captured(1);
            sensor.label = readText(path + "/" + channel + "_label");
            if (sensor.label.isEmpty()) {
                sensor.label = name + " " + channel;
            }
            sensor.cpuPackage = name == "coretemp"
                && sensor.label.contains("package", Qt::CaseInsensitive);
            sensor.path = path + "/" + channel + "_input";
            present.insert(id);
        }
    }
    for (auto &sensor : sensors) {
        sensor.value = QJsonValue::Null;
        if (!present.contains(sensor.id)) {
            continue;
        }
        bool converted = false;
        double value = readText(sensor.path).toDouble(&converted);
        if (converted && std::isfinite(value)) {
            if (sensor.kind == "temp") {
                value /= 1000.0;
            }
            sensor.value = value;
            sensor.lastSuccess = clock.elapsed();
        }
    }
}

QJsonObject Hwmon::snapshot(int intervalMilliseconds) const
{
    QJsonArray result;
    QString primary;
    bool primaryPackage = false;
    for (const auto &sensor : sensors) {
        const bool stale = sensor.lastSuccess < 0
            || clock.elapsed() - sensor.lastSuccess > qint64(intervalMilliseconds) * 3;
        result.append(QJsonObject{
            {"id", sensor.id}, {"label", sensor.label}, {"device", sensor.device},
            {"kind", sensor.kind}, {"value", sensor.value},
            {"unit", sensor.kind == "temp" ? "C" : "rpm"},
            {"source", "hwmon"}, {"stale", stale}
        });
        const bool preferPackage = !primaryPackage && sensor.cpuPackage;
        if (sensor.kind == "temp" && (primary.isEmpty() || preferPackage)) {
            primary = sensor.id;
            primaryPackage = sensor.cpuPackage;
        }
    }
    return {{"sensors", result}, {"primary", primary}};
}
