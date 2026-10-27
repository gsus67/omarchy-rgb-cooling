// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "protocol.hpp"
#include <QObject>
#include <QThread>
#include <functional>

class PowerProfilesWorker;

// The worker also keeps D-Bus's initial connection handshake off the API thread.
class PowerProfiles final : public QObject {
public:
    using Callback = std::function<void(const Protocol::Reply &)>;
    explicit PowerProfiles(std::function<void(const QJsonObject &)> changed);
    ~PowerProfiles() override;
    void request(const QString &profile, Callback ready);
    void setSubscribed(bool subscribed);

private:
    QThread thread;
    PowerProfilesWorker *worker;
};
