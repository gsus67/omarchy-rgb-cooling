// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "openrgb.hpp"
#include "openrgb_unit.hpp"
#include "sdk_mode.hpp"
#include "usb_devices.hpp"
#include <QElapsedTimer>
#include <QTcpSocket>
#include <QQueue>
#include <QTimer>

class OpenRgbWorker final : public QObject {
public:
    OpenRgbWorker(const QString &root, const QString &rules);
    ~OpenRgbWorker() override;
    using Callback = OpenRgbAdapter::Callback;
    std::function<void(QJsonObject, QJsonArray, bool)> changed;
    void perform(const QString &operation, const QJsonObject &params, Callback ready);
    void refresh();
    void hotplug(const QVector<HotplugEvent> &events, bool discover);
    void subscribed(bool value);

private:
    enum class Phase { Disconnected, Starting, Connecting, Version, Count, Controller, Idle, Read };
    struct Request {
        QString operation;
        QJsonObject params;
        Callback ready;
        bool join;
        int retries = 0;
        QJsonObject applied;
    };
    QQueue<Request> requests;
    QString root, rules;
    QElapsedTimer lastScan;
    quint64 scanGeneration = 0;
    OpenRgbUnit unit;
    UsbDevices usb;
    QSet<QString> launchedDevices;
    QMap<QString, QString> launchedNodes;
    QTcpSocket socket;
    QTimer timeout;
    QTimer startupRetry, startupDeadline;
    QTimer recoveryDebounce, recoveryDeadline, writeFailure;
    bool recovering = false, recoveryDue = false, recoveryRestarted = false;
    bool recoveryDirty = false;
    QSet<QString> reconnecting;
    QString pendingFailure;
    void recover();
    void suspendOperation();
    void completeAppliedWrite();
    QElapsedTimer startup;
    QByteArray input;
    Phase phase = Phase::Disconnected;
    QString state = "absent", reason = "OpenRGB has not been requested";
    unsigned version = 6;
    quint32 count = 0, index = 0;
    QVector<quint32> controllerIds;
    QMap<quint64, int> acknowledgements;
    bool awaitingWriteAck = false;
    bool writeAckFailed = false;
    QString writtenColor;
    int writtenMode = -1;
    qint64 writtenBrightness = -1;
    SdkMode writtenDescriptor;
    // Persistence belongs to the physical device, even if hidraw numbering changes.
    QSet<QString> unsaved;
    QMap<QString, QByteArray> appliedModes;
    QMap<QString, QElapsedTimer> lastSave;
    bool saving = false;
    QMap<QString, SdkController> controllers;
    QMap<QString, SdkController> pendingControllers;
    QMap<QString, QJsonObject> inventory;
    QString reading;
    bool scanning = false, writing = false, idleStopped = false;
    void next();
    void scan();
    void connectServer();
    void connectionFailed(const QString &message);
    void endStartup();
    void send(quint32 device, quint32 command, const QByteArray &payload = {});
    void receive();
    bool packet(quint32 device, quint32 command, const QByteArray &payload);
    bool signalUpdate(quint32 device, const QByteArray &payload);
    void fail(const QString &message, bool allowGrace = true);
    void publish();
    void gates();
    void identify(SdkController &controller, const SdkController *known = nullptr);
    void notify();
    void finish(const Protocol::Reply &reply);
    Protocol::Reply lighting(const QString &device) const;
    Protocol::Reply write(const QString &device, const QJsonObject &params);
    void updateSaved();
};
