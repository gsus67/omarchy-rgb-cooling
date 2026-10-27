// SPDX-License-Identifier: GPL-3.0-or-later
#include "usb_devices.hpp"
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonArray>
#include <QRegularExpression>

namespace {
QByteArray read(const QString &path, int limit)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) {
        return {};
    }
    const auto bytes = file.read(limit + 1);
    return bytes.size() <= limit ? bytes : QByteArray();
}

const QRegularExpression identity("\\Ausb:[0-9a-f]{4}:[0-9a-f]{4}:[^\\x00-\\x1f\\x7f]{0,256}\\z");

bool readEnabled(QSet<QString> &result)
{
    QString config = qEnvironmentVariable("XDG_CONFIG_HOME");
    if (config.isEmpty()) {
        config = QDir::homePath() + "/.config";
    }
    if (!QDir::isAbsolutePath(config)) {
        return false;
    }
    const auto path = config + "/omarchy-rgb-cooling/devices.json";
    if (!QFileInfo::exists(path)) {
        return true;
    }
    const auto bytes = read(path, 262144);
    const auto doc = QJsonDocument::fromJson(bytes);
    const auto object = doc.object();
    if (!doc.isObject() || object.size() != 2 || object.value("v") != QJsonValue(1)
        || !object.value("enabled").isObject()
        || object.value("enabled").toObject().size() > 1024) {
        return false;
    }
    // Qt accepts repeated keys. Reject them explicitly, including escaped spellings.
    const QRegularExpression key("(\"(?:[^\"\\\\]|\\\\.)*\")\\s*:");
    auto matches = key.globalMatch(QString::fromUtf8(bytes));
    QSet<QString> keys;
    while (matches.hasNext()) {
        const auto encoded = matches.next().captured(1).toUtf8();
        const auto decoded = QJsonDocument::fromJson("[" + encoded + "]").array()[0].toString();
        if (keys.contains(decoded)) {
            return false;
        }
        keys.insert(decoded);
    }
    const auto choices = object.value("enabled").toObject();
    for (auto it = choices.begin(); it != choices.end(); ++it) {
        if (!identity.match(it.key()).hasMatch() || !it.value().isBool()) {
            return false;
        }
        if (it.value().toBool()) {
            result.insert(it.key());
        }
    }
    return true;
}
}

UsbDevices UsbDevices::scan(const QString &root, const QString &rules)
{
    UsbDevices result;
    result.valid = readEnabled(result.enabled);
    if (!result.valid) {
        result.enabled.clear();
    }
    const QString canonicalRoot = QFileInfo(root).canonicalFilePath();
    if (canonicalRoot.isEmpty()) {
        return result;
    }
    QDir hidraw(root + "/class/hidraw");
    const QRegularExpression nodeName("\\Ahidraw[0-9]+\\z");
    for (const auto &node : hidraw.entryList(QDir::Dirs | QDir::NoDotAndDotDot)) {
        if (!nodeName.match(node).hasMatch()) {
            continue;
        }
        QString parent = QFileInfo(hidraw.filePath(node + "/device")).canonicalFilePath();
        while (parent.startsWith(canonicalRoot + "/")) {
            if (QFileInfo::exists(parent + "/idVendor")) {
                const auto vid = read(parent + "/idVendor", 16).trimmed().toLower();
                const auto pid = read(parent + "/idProduct", 16).trimmed().toLower();
                const auto serial = read(parent + "/serial", 1024).trimmed();
                const QString usb = "usb:" + vid + ":" + pid + ":" + QString::fromUtf8(serial);
                if (identity.match(usb).hasMatch()) {
                    result.nodes.insert("/dev/" + node, usb);
                    result.locations[usb].insert(parent);
                }
                break;
            }
            parent = QFileInfo(parent).dir().absolutePath();
        }
    }
    const QRegularExpression rule(
        "\\ASUBSYSTEMS==\"usb\\|hidraw\",\\s*ATTRS\\{idVendor\\}==\"([0-9a-fA-F]{4})\","
        "\\s*ATTRS\\{idProduct\\}==\"([0-9a-fA-F]{4})\",\\s*TAG\\+=\"uaccess\","
        "\\s*TAG\\+=\"([A-Za-z0-9_ .()+-]{1,256})\"\\z");
    QMap<QString, QString> names;
    for (const auto &line : read(rules, 4 * 1024 * 1024).split('\n')) {
        const auto match = rule.match(QString::fromUtf8(line.trimmed()));
        if (match.hasMatch() && match.captured(3) != "uaccess") {
            names.insert(match.captured(1).toLower() + ":" + match.captured(2).toLower(),
                         match.captured(3));
        }
    }
    for (const auto &usb : result.nodes) {
        const auto pair = usb.mid(4, 9);
        if (!names.contains(pair) || pair == "0416:5302") {
            continue;
        }
        const bool optedIn = result.enabled.contains(usb);
        result.candidates.insert(usb, {{"id", usb}, {"usb", usb}, {"name", names.value(pair)},
            {"vendor", pair.first(4)}, {"engine", "openrgb"}, {"support", "recognized"},
            {"enabled", optedIn}, {"writable", false}, {"excluded", false},
            {"blocked_reason", optedIn ? "OpenRGB unit has not provided this controller"
                                      : "RGB control is disabled for this device"},
            {"modes", QJsonArray{}}, {"capabilities", QJsonArray{}}});
    }
    return result;
}
