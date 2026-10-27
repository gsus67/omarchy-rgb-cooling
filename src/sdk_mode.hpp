// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QByteArray>
#include <QJsonObject>
#include <QVector>
#include "sdk_reader.hpp"

struct SdkMode {
    QString name;
    quint32 value = 0;
    quint32 flags = 0, speedMin = 0, speedMax = 0, brightnessMin = 0, brightnessMax = 0;
    quint32 colorsMin = 0, colorsMax = 0, speed = 0, brightness = 0, direction = 0;
    quint32 colorMode = 0;
    QVector<quint32> colors;
    static bool decode(SdkReader &reader, unsigned version, SdkMode &mode);
    QByteArray encode(unsigned version = 6) const;
    QJsonObject description() const;
    bool singleColor() const { return flags & (32U | 64U); }
    bool savable() const { return flags & (256U | 512U); }
};

struct SdkController {
    QJsonObject device;
    QString location, serial;
    bool ambiguous = false;
    QVector<SdkMode> modes;
    QVector<quint32> colors;
    quint32 active = 0, index = 0;
    unsigned version = 0;
    int staticMode() const;
    QJsonObject lighting() const;
    void identify(const QString &usb = {});
    bool sameController(const SdkController &other) const;
    static bool decode(const QByteArray &payload, unsigned version, SdkController &controller);
    static bool decodeUpdate(const QByteArray &, unsigned version, SdkController &controller);
};

quint32 modeRange(int percent, quint32 minimum, quint32 maximum);
int modePercent(quint32 value, quint32 minimum, quint32 maximum);
QByteArray sdkWord(quint32 value);
QByteArray sdkHalf(quint16 value);
QByteArray sdkText(const QString &value);
