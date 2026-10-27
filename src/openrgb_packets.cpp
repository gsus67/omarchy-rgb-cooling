// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb_worker.hpp"
#include <QRegularExpression>
#include <QtEndian>
#include <algorithm>

bool OpenRgbWorker::packet(quint32 device, quint32 command, const QByteArray &payload)
{
    if (version >= 6 && command == 51 && device == 0 && !payload.isEmpty()
        && payload.size() <= 4096) {
        const auto encoded = sdkHalf(payload.size()) + payload;
        SdkReader reader(encoded);
        reader.string();
        return reader.done();
    }
    if (version >= 6 && command == 10) {
        if (payload.size() != 8) {
            return false;
        }
        SdkReader reader(payload);
        const auto acknowledged = reader.u32();
        const auto status = reader.u32();
        const auto key = (quint64(device) << 32) | acknowledged;
        if (status != 0 || acknowledgements.value(key) < 1) {
            return false;
        }
        if (--acknowledgements[key] == 0) {
            acknowledgements.remove(key);
        }
        if (acknowledged == 1101 || acknowledged == 1050) {
            const auto prefix = quint64(device) << 32;
            awaitingWriteAck = acknowledgements.contains(prefix | 1101)
                || acknowledgements.contains(prefix | 1050);
        }
        return true;
    }
    if (command == 100 && device == 0 && payload.isEmpty()) {
        fail("OpenRGB list changed; request a fresh scan");
        return true;
    }
    if (phase == Phase::Version && command == 40 && device == 0 && payload.size() == 4) {
        version = std::min(6U, qFromLittleEndian<quint32>(payload.constData()));
        if (version < 6) {
            acknowledgements.clear();
        }
        phase = Phase::Count;
        send(0, 0);
        return true;
    }
    if (phase == Phase::Count && command == 0 && device == 0 && payload.size() >= 4) {
        SdkReader reader(payload);
        count = reader.u32();
        if (count > 128 || payload.size() != qsizetype(4 + (version >= 6 ? count * 4 : 0))) {
            return false;
        }
        QSet<quint32> unique;
        for (quint32 i = 0; i < count; ++i) {
            const auto controller = version >= 6 ? reader.u32() : i;
            if (unique.contains(controller)) {
                return false;
            }
            unique.insert(controller);
            controllerIds.append(controller);
        }
        index = 0;
        if (!count) {
            publish();
        } else {
            phase = Phase::Controller;
            send(controllerIds[index], 1, version >= 6 ? QByteArray() : sdkWord(version));
        }
        return true;
    }
    if (command != 1 || (phase != Phase::Controller && phase != Phase::Read)) {
        return false;
    }
    const auto expected = phase == Phase::Read ? controllers.value(reading).index
                                              : controllerIds[index];
    SdkController controller;
    if (device != expected || !SdkController::decode(payload, version, controller)) {
        return false;
    }
    controller.index = device;
    const auto id = controller.device.value("id").toString();
    if (phase == Phase::Read) {
        if (id != reading) {
            return false;
        }
        controllers[id] = controller;
        // Opt-out and hotplug must also take effect between scans and a lighting write.
        usb = UsbDevices::scan(root, rules);
        gates();
        if (writing) {
            writing = false;
            const auto params = requests.head().params;
            if (!write(id, params.value("color").toString(), params.value("brightness").toInt())) {
                reading.clear();
                phase = Phase::Idle;
                timeout.stop();
                finish(Protocol::Reply::failure(
                    "blocked", inventory[id]["blocked_reason"].toString()));
                return true;
            }
            send(device, 1, version >= 6 ? QByteArray() : sdkWord(version));
        } else {
            if (awaitingWriteAck) {
                return false;
            }
            timeout.stop();
            reading.clear();
            phase = Phase::Idle;
            notify();
            auto result = lighting(id);
            if (writtenMode >= 0 && (controller.active != unsigned(writtenMode)
                || !result.ok() || result.result.value("color").toString() != writtenColor
                || (writtenBrightness >= 0
                    && controller.modes[controller.active].brightness != writtenBrightness))) {
                result = Protocol::Reply::failure("unsupported",
                    "OpenRGB did not apply the Static colour or brightness");
            }
            writtenColor.clear();
            writtenMode = -1;
            finish(result);
        }
        return true;
    }
    if (controllers.contains(id)) {
        return false;
    }
    controllers.insert(id, controller);
    if (++index == count) {
        publish();
    } else {
        send(controllerIds[index], 1, version >= 6 ? QByteArray() : sdkWord(version));
    }
    return true;
}

void OpenRgbWorker::gates()
{
    inventory = usb.candidates;
    QMap<QString, int> identities;
    const QRegularExpression hid("\\AHID: (/dev/hidraw[0-9]+)\\z");
    for (auto &controller : controllers) {
        const auto match = hid.match(controller.location);
        const auto identity = match.hasMatch() ? usb.nodes.value(match.captured(1)) : QString();
        controller.device.insert("usb", identity);
        if (!identity.isEmpty()) {
            ++identities[identity];
        }
    }
    for (auto &controller : controllers) {
        auto &device = controller.device;
        const auto identity = device.value("usb").toString();
        const bool enabled = usb.enabled.contains(identity);
        const bool excluded = device.value("excluded").toBool()
            || identity.startsWith("usb:0416:5302:");
        QString gate;
        if (excluded) {
            gate = "0416:5302 is reserved exclusively for omarchy-trcc";
        } else if (identity.isEmpty()) {
            gate = "USB identity is unknown";
        } else if (identities.value(identity) != 1 || usb.locations.value(identity).size() != 1) {
            gate = "USB identity is not unique";
        } else if (!enabled || !usb.valid) {
            gate = "RGB control is disabled for this device";
        } else if (!unit.owned()) {
            gate = "OpenRGB is not running through the plugin's own unit";
        } else if (version != 6 || controller.staticMode() < 0) {
            gate = "A supported Static mode with colour is required (SDK protocol 6)";
        }
        device.insert("enabled", enabled);
        device.insert("excluded", excluded);
        device.insert("writable", gate.isEmpty());
        device.insert("blocked_reason", gate);
        QJsonArray capabilities;
        if (!excluded && !controller.lighting().isEmpty()) {
            capabilities.append("lighting.read");
        }
        if (gate.isEmpty()) {
            capabilities.append("lighting.write");
            capabilities.append("brightness");
        }
        device.insert("capabilities", capabilities);
        inventory.remove(identity);
        inventory.insert(device.value("id").toString(), device);
    }
}

Protocol::Reply OpenRgbWorker::lighting(const QString &id) const
{
    if (!inventory.contains(id)) {
        return Protocol::Reply::failure("unavailable", "Device is not available");
    }
    if (inventory[id].value("excluded").toBool()) {
        return Protocol::Reply::failure(
            "blocked", inventory[id].value("blocked_reason").toString());
    }
    if (!controllers.contains(id)) {
        return Protocol::Reply::failure("unavailable", "OpenRGB controller is not available");
    }
    const auto value = controllers[id].lighting();
    if (value.isEmpty()) {
        return Protocol::Reply::failure("unsupported", "No uniform current colour is available");
    }
    return {value, {}, {}};
}

bool OpenRgbWorker::write(const QString &id, const QString &color, int brightness)
{
    if (!inventory[id].value("writable").toBool()) {
        return false;
    }
    const auto &controller = controllers[id];
    const auto modeIndex = controller.staticMode();
    if (modeIndex < 0 || version != 6) {
        return false;
    }
    auto mode = controller.modes[modeIndex];
    const bool native = (mode.flags & 16U) && mode.brightnessMax > mode.brightnessMin;
    if (native) {
        mode.brightness = mode.brightnessMin
            + (quint64(mode.brightnessMax - mode.brightnessMin) * brightness + 50) / 100;
    }
    bool valid = false;
    const auto rgb = color.mid(1).toUInt(&valid, 16);
    if (!valid || color.size() != 7 || brightness < 0 || brightness > 100) {
        return false;
    }
    auto component = [&](int shift) {
        const auto value = (rgb >> shift) & 255;
        return native ? value : (value * brightness + 50) / 100;
    };
    const auto packed = component(16) | (component(8) << 8) | (component(0) << 16);
    mode.colorMode = mode.flags & 32U ? 1 : 2;
    // colors was decoded with a matching LED count and a 4096-LED limit.
    const auto count = mode.colorMode == 1 ? controller.colors.size()
                                         : qsizetype(std::max(1U, mode.colorsMin));
    if (count < 1 || count > 4096 || (mode.colorMode == 2 && count > mode.colorsMax)) {
        return false;
    }
    QByteArray leds;
    if (mode.colorMode == 1) {
        mode.colors.clear();
        leds = sdkHalf(count);
        for (qsizetype i = 0; i < count; ++i) {
            leds += sdkWord(packed);
        }
        leds.prepend(sdkWord(leds.size() + 4));
    } else {
        mode.colors.fill(packed, count);
    }
    auto payload = sdkWord(modeIndex) + mode.encode();
    payload.prepend(sdkWord(payload.size() + 4));
    // Select Static; per-LED modes require a separate, strictly uniform LED buffer.
    writtenColor = QString("#%1%2%3").arg(packed & 255, 2, 16, QChar('0'))
        .arg((packed >> 8) & 255, 2, 16, QChar('0'))
        .arg((packed >> 16) & 255, 2, 16, QChar('0'));
    writtenMode = modeIndex;
    writtenBrightness = native ? qint64(mode.brightness) : -1;
    awaitingWriteAck = true;
    send(controller.index, 1101, payload);
    if (!leds.isEmpty()) {
        send(controller.index, 1050, leds);
    }
    return true;
}
