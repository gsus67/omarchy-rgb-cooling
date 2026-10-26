// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "adapter.hpp"
#include <QElapsedTimer>
#include <QMap>
#include <QObject>
#include <QTcpSocket>
#include <QTimer>
#include <functional>
#include <vector>

class OpenRgbAdapter final : public QObject, public LightingAdapter {
public:
    explicit OpenRgbAdapter(std::function<void()> changed);
    ~OpenRgbAdapter() override;
    QJsonObject engine() const override;
    QJsonArray devices() const override;
    Protocol::Reply lighting(const QString &device) const override;
    Protocol::Reply setLighting(const QString &device, const QString &color,
                               int brightness) override;
    void refresh();
    void request(std::function<void()> ready);
    bool rescan(std::function<void()> ready);
    static bool decodeController(const QByteArray &payload, unsigned version,
                                 QJsonObject &device, QJsonObject &lighting);

private:
    static const QString WriteGate;
    static const QString TrofeoGate;
    enum class Phase { Disconnected, Connecting, Version, Count, Controller };
    QElapsedTimer lastScan;
    std::vector<std::function<void()>> pending;
    Phase phase = Phase::Disconnected;
    QTcpSocket socket;
    QTimer timeout;
    QByteArray input;
    QString state = "absent";
    QString reason = "OpenRGB SDK is not connected";
    QMap<QString, QJsonObject> inventory;
    QMap<QString, QJsonObject> colors;
    QMap<QString, QJsonObject> pendingInventory;
    QMap<QString, QJsonObject> pendingColors;
    unsigned protocolVersion = 1;
    quint32 controllerCount = 0;
    quint32 controllerIndex = 0;
    std::function<void()> changed;
    void settleRequests();
    void connectServer();
    void fail(const QString &newState, const QString &message);
    void send(quint32 device, quint32 command, const QByteArray &payload = {});
    void receive();
    bool packet(quint32 device, quint32 command, const QByteArray &payload);
    void publish();
    static QByteArray word(quint32 value);
};
