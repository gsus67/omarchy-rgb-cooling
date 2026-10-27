// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "protocol.hpp"
#include <QElapsedTimer>
#include <QLocalSocket>
#include <QObject>
#include <QQueue>
#include <QSet>
#include <QTimer>
#include <functional>

class Connection final : public QObject {
public:
    Connection(qintptr descriptor, QObject *parent);
    ~Connection() override;
    QSet<QString> topics;
    int intervalMilliseconds = 2000;
    qint64 nextEvent = 0;
    quint64 subscriptionRevision = 0;
    std::function<void(Connection *, const Protocol::Request &)> requestReceived;
    std::function<void(Connection *)> closed;
    void send(const QJsonObject &object);
    void subscriptionChanged();
    bool allowLightingWrite();
    bool allowProfileWrite();
    void start();

private:
    QLocalSocket socket;
    QTimer idle;
    QElapsedTimer clock;
    QQueue<qint64> writeTimes;
    QQueue<qint64> profileWriteTimes;
    QByteArray input;
    bool closing = false;
    void receive();
};
