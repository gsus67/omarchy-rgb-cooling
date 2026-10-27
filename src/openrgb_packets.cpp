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
        if (acknowledged == 1101 || acknowledged == 1050 || acknowledged == 1102) {
            const auto prefix = quint64(device) << 32;
            awaitingWriteAck = acknowledgements.contains(prefix | 1101)
                || acknowledgements.contains(prefix | 1050)
                || acknowledgements.contains(prefix | 1102);
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
            const auto result = write(id, params);
            if (!result.ok()) {
                saving = false;
                writtenMode = -1;
                reading.clear();
                phase = Phase::Idle;
                timeout.stop();
                finish(result);
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
            if (writtenMode >= 0) {
                if (controller.active >= unsigned(controller.modes.size())) {
                    return false;
                }
                const auto &actual = controller.modes[controller.active];
                if (controller.active != unsigned(writtenMode) || !result.ok()
                    || (!writtenColor.isEmpty()
                        && result.result.value("color").toString() != writtenColor)
                    || actual.speed != writtenDescriptor.speed
                    || actual.colorMode != writtenDescriptor.colorMode
                    || actual.colors != writtenDescriptor.colors
                    || (writtenBrightness >= 0 && actual.brightness != writtenBrightness)) {
                    result = Protocol::Reply::failure("unsupported",
                        "OpenRGB did not apply the requested mode values");
                }
            }
            if (writtenMode >= 0 && result.ok()) {
                auto payload = sdkWord(writtenMode) + writtenDescriptor.encode(version);
                payload.prepend(sdkWord(payload.size() + 4));
                appliedModes[inventory[id].value("usb").toString()] = payload;
            }
            if (saving && result.ok()) {
                unsaved.remove(inventory[id].value("usb").toString());
                updateSaved();
                result = lighting(id);
            }
            saving = false;
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
        } else if (version < 3 || controller.staticMode() < 0) {
            gate = "A supported Static mode with colour is required (SDK protocol 3 or later)";
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
    updateSaved();
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
    auto value = controllers[id].lighting();
    if (value.isEmpty()) {
        return Protocol::Reply::failure("unsupported", "No uniform current colour is available");
    }
    value.insert("saved", !unsaved.contains(controllers[id].device.value("usb").toString()));
    return {value, {}, {}};
}
