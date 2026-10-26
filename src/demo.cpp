// SPDX-License-Identifier: GPL-3.0-or-later
#include "demo.hpp"

QJsonObject DemoAdapter::engine() const
{
    return {{"id", "openrgb"}, {"state", "ready"}, {"reason", "Demo simulation only"}};
}

QJsonArray DemoAdapter::devices() const
{
    return {QJsonObject{
        {"id", "demo:rgb0"}, {"name", "Demo RGB"}, {"vendor", "Simulation"},
        {"engine", "demo"}, {"support", "simulation-tested"}, {"writable", true},
        {"blocked_reason", ""}, {"excluded", false},
        {"capabilities", QJsonArray{"lighting.read", "lighting.write", "brightness"}}
    }};
}

Protocol::Reply DemoAdapter::lighting(const QString &device) const
{
    if (device != "demo:rgb0") {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    return {{{"device", device}, {"color", color}, {"brightness", brightness},
             {"brightness_emulated", true}}, {}, {}};
}

Protocol::Reply DemoAdapter::setLighting(const QString &device, const QString &newColor,
                                       int newBrightness)
{
    if (device != "demo:rgb0") {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    color = newColor.toLower();
    brightness = newBrightness;
    return lighting(device);
}

QJsonObject DemoAdapter::sensors() const
{
    return {{"sensors", QJsonArray{
        QJsonObject{{"id", "demo:cpu:temp1"}, {"label", "CPU Package"}, {"device", "demo:cpu"},
                    {"kind", "temp"}, {"value", 42.5}, {"unit", "C"},
                    {"source", "demo"}, {"stale", false}},
        QJsonObject{{"id", "demo:gpu:fan1"}, {"label", "GPU fan"}, {"device", "demo:gpu"},
                    {"kind", "fan"}, {"value", 900}, {"unit", "rpm"},
                    {"source", "demo"}, {"stale", false}}
    }}, {"primary", "demo:cpu:temp1"}};
}
