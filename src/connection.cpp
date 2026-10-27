// SPDX-License-Identifier: GPL-3.0-or-later
#include "connection.hpp"
#include <QJsonDocument>

Connection::Connection(qintptr descriptor, QObject *parent) : QObject(parent)
{
    clock.start();
    socket.setReadBufferSize(Protocol::MaxLine + 1);
    socket.setSocketDescriptor(descriptor);
    idle.setSingleShot(true);
    idle.setInterval(Protocol::IdleMilliseconds);
    idle.setTimerType(Qt::PreciseTimer);
    connect(&idle, &QTimer::timeout, this, [this] { socket.disconnectFromServer(); });
    connect(&socket, &QLocalSocket::readyRead, this, [this] { receive(); });
    connect(&socket, &QLocalSocket::disconnected, this, [this] {
        closing = true;
        if (closed) {
            closed(this);
        }
        deleteLater();
    });
}

Connection::~Connection()
{
    socket.disconnect(this);
    socket.abort();
}

void Connection::start()
{
    idle.start();
    // setSocketDescriptor can find data already pending at accept time.
    if (socket.bytesAvailable() > 0) {
        QTimer::singleShot(0, this, [this] { receive(); });
    }
}

void Connection::send(const QJsonObject &object)
{
    const QByteArray line = QJsonDocument(object).toJson(QJsonDocument::Compact) + '\n';
    // Bound queued output too: a subscriber that stops reading must not consume memory forever.
    if (socket.bytesToWrite() + line.size() > 2 * 1024 * 1024) {
        closing = true;
        socket.abort();
        return;
    }
    socket.write(line);
}

void Connection::subscriptionChanged()
{
    if (topics.isEmpty()) {
        idle.start();
    } else {
        idle.stop();
    }
}

bool Connection::allowLightingWrite()
{
    const auto now = clock.elapsed();
    while (!writeTimes.isEmpty() && now - writeTimes.head() >= 1000) {
        writeTimes.dequeue();
    }
    if (writeTimes.size() >= 10) {
        return false;
    }
    writeTimes.enqueue(now);
    return true;
}

bool Connection::allowProfileWrite()
{
    const auto now = clock.elapsed();
    while (!profileWriteTimes.isEmpty() && now - profileWriteTimes.head() >= 1000) {
        profileWriteTimes.dequeue();
    }
    if (profileWriteTimes.size() >= 2) {
        return false;
    }
    profileWriteTimes.enqueue(now);
    return true;
}

void Connection::receive()
{
    if (closing) {
        return;
    }
    const auto received = socket.read(Protocol::MaxLine + 1 - input.size());
    if (!received.isEmpty() && topics.isEmpty()) {
        idle.start();
    }
    input.append(received);
    // Yield between batches so a client with many short requests cannot starve timers.
    for (int budget = 0; budget < 32 && !closing; ++budget) {
        const auto newline = input.indexOf('\n');
        if (newline > Protocol::MaxLine || (newline < 0 && input.size() > Protocol::MaxLine)) {
            send(Protocol::response(QJsonValue::Null,
                 Protocol::Reply::failure("too_large", "Request line exceeds 64 KiB")));
            closing = true;
            socket.disconnectFromServer();
            return;
        }
        if (newline < 0) {
            break;
        }
        const auto line = input.first(newline);
        input.remove(0, newline + 1);
        Protocol::Request request;
        const auto validation = Protocol::parse(line, request);
        if (topics.isEmpty()) {
            idle.start();
        }
        if (!validation.ok()) {
            send(Protocol::response(request.id, validation));
        } else if (requestReceived) {
            requestReceived(this, request);
        }
    }
    if (!closing && (input.contains('\n') || socket.bytesAvailable() > 0)) {
        QTimer::singleShot(0, this, [this] { receive(); });
    }
}
