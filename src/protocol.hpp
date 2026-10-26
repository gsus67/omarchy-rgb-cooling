// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QByteArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QString>

namespace Protocol {
constexpr qsizetype MaxLine = 64 * 1024;
constexpr int MaxConnections = 8;
constexpr int IdleMilliseconds = 30000;
constexpr int ExitMilliseconds = 60000;

struct Reply {
    QJsonObject result;
    QString code;
    QString message;
    bool ok() const;
    static Reply failure(const QString &code, const QString &message);
};

struct Request {
    QJsonValue id = QJsonValue::Null;
    QString operation;
    QJsonObject params;
};

bool integer(const QJsonValue &value);
Reply parse(const QByteArray &line, Request &request);
QJsonObject response(const QJsonValue &id, const Reply &reply);
QJsonObject event(const QString &topic, const QJsonObject &data);
} // namespace Protocol
