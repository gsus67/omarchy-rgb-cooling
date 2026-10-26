// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QElapsedTimer>
#include <QJsonObject>
#include <QMap>
#include <QString>

class Hwmon {
public:
    explicit Hwmon(QString root);
    void sample(int intervalMilliseconds);
    QJsonObject snapshot(int intervalMilliseconds) const;

private:
    struct Sensor {
        QString id;
        QString label;
        QString device;
        QString kind;
        QString path;
        bool cpuPackage = false;
        QJsonValue value = QJsonValue::Null;
        qint64 lastSuccess = -1;
    };
    QString root;
    QMap<QString, Sensor> sensors;
    QElapsedTimer clock;
    static QString readText(const QString &path);
    QString devicePath(const QString &directory) const;
};
