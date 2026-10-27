// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QByteArray>
#include <QJsonObject>
#include <QMap>
#include <QString>

class FanHeaders {
public:
    static constexpr qint64 MaximumBytes = 256 * 1024;
    bool load(const QString &dataDirectory, const QString &dmiRoot);
    static bool validate(const QByteArray &data);
    QString header(const QString &chip, const QString &channel) const;

private:
    QMap<QString, QMap<QString, QString>> chips;
    static bool parse(const QByteArray &data, QJsonObject &table);
};
