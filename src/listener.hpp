// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QLocalServer>
#include <QSocketNotifier>
#include <functional>
#include <memory>

class PeerServer final : public QLocalServer {
public:
    std::function<void(qintptr)> accepted;

protected:
    void incomingConnection(quintptr descriptor) override;
};

// QLocalServer owns only private endpoints; activation never gives Qt the listener.
class Listener final : public QObject {
public:
    ~Listener() override;
    std::function<void(qintptr)> accepted;
    bool listen(const QString &path, QString &error);
    bool adopt(qintptr descriptor, QString &error);

private:
    PeerServer owned;
    int activation = -1;
    std::unique_ptr<QSocketNotifier> notifier;
    void drain();
};
