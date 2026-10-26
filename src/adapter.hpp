// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "protocol.hpp"
#include <QJsonArray>
#include <QString>

class LightingAdapter {
public:
    virtual ~LightingAdapter() = default;
    virtual QJsonObject engine() const = 0;
    virtual QJsonArray devices() const = 0;
    virtual Protocol::Reply lighting(const QString &device) const = 0;
    virtual Protocol::Reply setLighting(const QString &device, const QString &color,
                                       int brightness) = 0;
};
