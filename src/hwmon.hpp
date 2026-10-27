// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "fan_headers.hpp"
#include <QElapsedTimer>
#include <QJsonObject>
#include <QMap>
#include <QString>

class Hwmon {
public:
    explicit Hwmon(QString root);
    void loadFanHeaders(const QString &dataDirectory, const QString &dmiRoot);
    void sample(int intervalMilliseconds);
    QJsonObject snapshot(int intervalMilliseconds) const;

private:
    struct Sensor {
        QString id;
        QString label;
        QString device;
        QString kind;
        QString channel;
        QString header;
        QString path;
        bool cpuPackage = false;
        QJsonValue value = QJsonValue::Null;
        qint64 lastSuccess = -1;
    };
    QString root;
    FanHeaders fanHeaders;
    QMap<QString, Sensor> sensors;
    QElapsedTimer clock;
    static QString readText(const QString &path);
    QString devicePath(const QString &directory) const;
};
