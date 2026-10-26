// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include "adapter.hpp"

class DemoAdapter final : public LightingAdapter {
public:
    QJsonObject engine() const override;
    QJsonArray devices() const override;
    Protocol::Reply lighting(const QString &device) const override;
    Protocol::Reply setLighting(const QString &device, const QString &color,
                               int brightness) override;
    QJsonObject sensors() const;

private:
    QString color = "#4080ff";
    int brightness = 100;
};
