// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QJsonObject>
#include <QMap>
#include <QSet>

struct UsbDevices {
    QMap<QString, QString> nodes;
    QMap<QString, QSet<QString>> locations;
    QMap<QString, QJsonObject> candidates;
    QSet<QString> enabled;
    bool valid = true;
    static UsbDevices scan(const QString &root, const QString &rules);
};
