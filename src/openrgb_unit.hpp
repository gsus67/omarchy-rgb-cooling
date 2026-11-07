// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QObject>
#include <QTimer>
#include <functional>
#include <memory>

class OpenRgbUnitWorker;
class OpenRgbUnit final : public QObject {
public:
    explicit OpenRgbUnit(QObject *parent = nullptr);
    ~OpenRgbUnit() override;
    void start(std::function<void(bool)> ready);
    void stop(std::function<void(bool)> ready);
    void activity();
    void setSaved(bool saved);
    void setSubscribed(bool subscribed);
    bool owned() const;
    bool transitioning() const;
    std::function<void()> stopped;
    std::function<void()> settled;

private:
    std::unique_ptr<OpenRgbUnitWorker> worker;
};
