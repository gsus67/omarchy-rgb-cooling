// SPDX-License-Identifier: GPL-3.0-or-later
#include "hwmon.hpp"
#include "sensor_names.hpp"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QRegularExpression>
#include <QSet>
#include <algorithm>
#include <climits>
#include <cmath>
#include <tuple>
#include <utility>

Hwmon::Hwmon(QString root) : root(std::move(root))
{
    clock.start();
}

void Hwmon::loadFanHeaders(const QString &dataDirectory, const QString &dmiRoot)
{
    fanHeaders.load(dataDirectory, dmiRoot);
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
    struct Node {
        QString path;
        QString name;
        QString parent;
        QString driver;
    };
    QVector<Node> nodes;
    for (const auto &entry : entries) {
        const QString path = directory.filePath(entry);
        const QString name = readText(path + "/name");
        const QString parent = devicePath(path);
        if (name.isEmpty() || parent.isEmpty()) {
            continue;
        }
        QString driver = QFileInfo(path + "/device/driver").symLinkTarget();
        if (!driver.isEmpty()) {
            driver = QFileInfo(driver).fileName();
        }
        nodes.push_back({path, name, parent, driver});
    }
    auto pciAddress = [](const QString &path) {
        static const QRegularExpression pci("[0-9a-fA-F]{4}:[0-9a-fA-F]{2}:"
                                           "[0-9a-fA-F]{2}\\.[0-7]");
        auto matches = pci.globalMatch(path);
        QString address;
        while (matches.hasNext()) {
            address = matches.next().captured().toLower();
        }
        return address;
    };
    QVector<QString> nvmeAddresses;
    auto isRam = [](const Node &node) {
        return node.name == "spd5118" || node.name == "jc42" || node.name == "ee1004";
    };
    auto i2cOrder = [](const QString &path) {
        static const QRegularExpression busPattern("(?:^|/)i2c-([0-9]+)(?:/|$)");
        static const QRegularExpression addressPattern("(?:^|/)([0-9]+)-([0-9a-fA-F]{4})$");
        const auto busMatch = busPattern.match(path);
        const auto addressMatch = addressPattern.match(path);
        const int bus = busMatch.hasMatch() ? busMatch.captured(1).toInt() : INT_MAX;
        const int addressBus = addressMatch.hasMatch() ? addressMatch.captured(1).toInt() : INT_MAX;
        bool addressOk = false;
        const int address = addressMatch.hasMatch()
            ? addressMatch.captured(2).toInt(&addressOk, 16) : INT_MAX;
        return std::tuple(bus, addressBus, addressOk ? address : INT_MAX, path);
    };
    QVector<QString> ramParents;
    for (const auto &node : nodes) {
        if (node.name.startsWith("nvme") || node.driver == "nvme") {
            nvmeAddresses.push_back(pciAddress(node.parent) + ":" + node.parent);
        }
        if (isRam(node) && !ramParents.contains(node.parent)) {
            ramParents.push_back(node.parent);
        }
    }
    std::sort(nvmeAddresses.begin(), nvmeAddresses.end());
    nvmeAddresses.erase(std::unique(nvmeAddresses.begin(), nvmeAddresses.end()),
                        nvmeAddresses.end());
    std::sort(ramParents.begin(), ramParents.end(), [&](const QString &left, const QString &right) {
        return i2cOrder(left) < i2cOrder(right);
    });
    QString cpuVendor;
    const QString cpuInfo = readText("/proc/cpuinfo");
    static const QRegularExpression vendorPattern("^vendor_id\\s*:\\s*(\\S+)",
                                                  QRegularExpression::MultilineOption);
    cpuVendor = vendorPattern.match(cpuInfo).captured(1);
    for (const auto &node : nodes) {
        const QString &path = node.path;
        const QString &name = node.name;
        const auto inputs = QDir(path).entryList(QDir::Files, QDir::Name);
        QSet<QString> fans;
        for (const auto &input : inputs) {
            const auto match = channelPattern.match(input);
            if (match.hasMatch() && match.captured(1) == "fan") {
                fans.insert(input.left(input.lastIndexOf('_')));
            }
        }
        for (const auto &input : inputs) {
            const auto match = channelPattern.match(input);
            if (!match.hasMatch()) {
                continue;
            }
            const QString channel = input.left(input.lastIndexOf('_'));
            const QString id = name + ":" + node.parent + ":" + channel;
            if (!sensors.contains(id) && sensors.size() >= 4096) {
                continue;
            }
            Sensor &sensor = sensors[id];
            sensor.id = id;
            int nvmeNumber = 0;
            if (name.startsWith("nvme") || node.driver == "nvme") {
                const QString key = pciAddress(node.parent) + ":" + node.parent;
                nvmeNumber = nvmeAddresses.indexOf(key) + 1;
            }
            sensor.device = SensorNames::device(name, node.parent, node.driver, cpuVendor,
                                                nvmeNumber);
            sensor.kind = match.captured(1);
            sensor.channel = channel;
            sensor.header = fanHeaders.header(name, channel);
            sensor.label = SensorNames::label(name, channel,
                                              readText(path + "/" + channel + "_label"));
            if (isRam(node)) {
                sensor.label = QString("DIMM %1").arg(ramParents.indexOf(node.parent) + 1);
            }
            if (sensor.kind == "fan" && fans.size() > 1) {
                sensor.label = "Fan " + channel.mid(3);
            }
            if (!sensor.header.isEmpty()) {
                sensor.label = sensor.header;
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
    QVector<const Sensor *> ordered;
    for (const auto &sensor : sensors) {
        ordered.append(&sensor);
    }
    std::sort(ordered.begin(), ordered.end(), [](const Sensor *left, const Sensor *right) {
        const auto leftEnd = left->id.lastIndexOf(':');
        const auto rightEnd = right->id.lastIndexOf(':');
        const auto leftDevice = left->id.left(leftEnd);
        const auto rightDevice = right->id.left(rightEnd);
        if (leftDevice != rightDevice) {
            return leftDevice < rightDevice;
        }
        if (left->kind != right->kind) {
            return left->kind == "temp";
        }
        const auto leftChannel = left->id.mid(leftEnd + 1);
        const auto rightChannel = right->id.mid(rightEnd + 1);
        return leftChannel.size() != rightChannel.size()
            ? leftChannel.size() < rightChannel.size() : leftChannel < rightChannel;
    });
    for (const auto *entry : ordered) {
        const auto &sensor = *entry;
        const bool stale = sensor.lastSuccess < 0
            || clock.elapsed() - sensor.lastSuccess > qint64(intervalMilliseconds) * 3;
        result.append(QJsonObject{
            {"id", sensor.id}, {"label", sensor.label}, {"device", sensor.device},
            {"kind", sensor.kind}, {"value", sensor.value},
            {"channel", sensor.channel}, {"header", sensor.header},
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
