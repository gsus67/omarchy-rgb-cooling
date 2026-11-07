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
        {"modes", QJsonArray{QJsonObject{{"name", "Static"}, {"speed", false},
            {"brightness", false}, {"color", "single"}, {"random", false}, {"savable", true}}}},
        {"capabilities", QJsonArray{"lighting.read", "lighting.write", "brightness"}}
    }};
}

Protocol::Reply DemoAdapter::lighting(const QString &device) const
{
    if (device != "demo:rgb0") {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    return {{{"device", device}, {"color", color}, {"brightness", brightness},
             {"brightness_emulated", true}, {"mode", "Static"}, {"speed", QJsonValue::Null},
             {"random", false}, {"saved", saved}}, {}, {}};
}

Protocol::Reply DemoAdapter::setLighting(const QString &device, const QString &newColor,
                                       int newBrightness)
{
    if (device != "demo:rgb0") {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    saved = false;
    color = newColor.toLower();
    brightness = newBrightness;
    return lighting(device);
}

Protocol::Reply DemoAdapter::updateLighting(const QJsonObject &params)
{
    const auto id = params.value("device").toString();
    if (!lighting(id).ok()) {
        return lighting(id);
    }
    if ((params.contains("mode") && params.value("mode") != "Static")
        || params.contains("speed") || params.contains("random")) {
        return Protocol::Reply::failure("bad_request", "Unsupported field for Static");
    }
    return setLighting(id, params.value("color").toString(color),
                       params.value("brightness").toInt(brightness));
}

Protocol::Reply DemoAdapter::saveLighting(const QString &id)
{
    if (!lighting(id).ok()) {
        return lighting(id);
    }
    if (lastSave.isValid() && lastSave.elapsed() < 10000) {
        return Protocol::Reply::failure("rate_limited", "Saves must be at least 10 s apart");
    }
    saved = true;
    lastSave.start();
    return lighting(id);
}

QJsonObject DemoAdapter::sensors() const
{
    return {{"sensors", QJsonArray{
        QJsonObject{{"id", "demo:cpu:temp1"}, {"label", "CPU Package"}, {"device", "demo:cpu"},
                    {"kind", "temp"}, {"value", 42.5}, {"unit", "C"},
                    {"channel", "temp1"}, {"header", ""},
                    {"source", "demo"}, {"stale", false}},
        QJsonObject{{"id", "demo:gpu:fan1"}, {"label", "GPU fan"}, {"device", "demo:gpu"},
                    {"kind", "fan"}, {"value", 900}, {"unit", "rpm"},
                    {"channel", "fan1"}, {"header", ""},
                    {"source", "demo"}, {"stale", false}}
    }}, {"primary", "demo:cpu:temp1"}};
}
