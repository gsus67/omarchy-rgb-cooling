// SPDX-License-Identifier: GPL-3.0-or-later
#include "openrgb_worker.hpp"
#include <algorithm>

void OpenRgbWorker::updateSaved()
{
    bool saved = true;
    for (const auto &identity : unsaved) {
        if (usb.enabled.contains(identity)) {
            saved = false;
            break;
        }
    }
    unit.setSaved(saved);
}

Protocol::Reply OpenRgbWorker::write(const QString &id, const QJsonObject &params)
{
    auto error = [](const QString &message) {
        return Protocol::Reply::failure("bad_request", message);
    };
    if (!inventory[id].value("writable").toBool()) {
        return Protocol::Reply::failure("blocked", inventory[id]["blocked_reason"].toString());
    }
    const auto &controller = controllers[id];
    const auto identity = controller.device.value("usb").toString();
    saving = requests.head().operation == "lighting.save";
    writeAckFailed = false;
    writtenMode = -1;
    writtenColor.clear();
    if (saving) {
        const auto &mode = controller.modes[controller.active];
        if (!mode.savable() || mode.name == "Direct") {
            return Protocol::Reply::failure("unsupported", "The active mode cannot be saved");
        }
        if (requests.head().retries == 0 && lastSave[identity].isValid()
            && lastSave[identity].elapsed() < 10000) {
            return Protocol::Reply::failure("rate_limited", "Saves must be at least 10 s apart");
        }
        auto payload = appliedModes.value(identity);
        SdkReader reader(payload);
        reader.u32();
        const auto applied = reader.u32();
        const auto appliedName = reader.string();
        if (payload.isEmpty() || !reader.valid() || applied != controller.active
            || appliedName != mode.name) {
            payload = sdkWord(controller.active) + mode.encode(version);
            payload.prepend(sdkWord(payload.size() + 4));
        }
        // Reserve the interval before sending: even a lost acknowledgement may have saved.
        lastSave[identity].start();
        awaitingWriteAck = version >= 6;
        send(controller.index, 1102, payload);
        return {};
    }
    int modeIndex = controller.active;
    const auto requested = params.value("mode").toString();
    if (params.contains("mode")) {
        modeIndex = -1;
        for (qsizetype i = 0; i < controller.modes.size(); ++i) {
            if (controller.modes[i].name == requested && requested != "Direct") {
                modeIndex = i;
                break;
            }
        }
    } else if (controller.modes[modeIndex].name == "Direct") {
        modeIndex = controller.staticMode();
    }
    if (modeIndex < 0) {
        return error("Unknown or unsupported mode");
    }
    auto mode = controller.modes[modeIndex];
    if ((params.contains("color") && !mode.singleColor())
        || (params.contains("speed") && !(mode.flags & 1U))
        || (params.contains("random") && !(mode.flags & 128U))) {
        return error("Parameter is not supported by the selected mode");
    }
    const auto current = controller.lighting();
    const bool native = mode.flags & 16U;
    const int brightness = params.value("brightness").toInt(
        current.value("brightness").toInt(100));
    if (params.contains("brightness") && !native && !mode.singleColor()) {
        return error("Brightness cannot be emulated for this mode");
    }
    if (native && (params.contains("brightness") || unsigned(modeIndex) != controller.active)) {
        mode.brightness = modeRange(brightness, mode.brightnessMin, mode.brightnessMax);
    }
    if ((mode.flags & 1U)
        && (params.contains("speed") || unsigned(modeIndex) != controller.active)) {
        const int speed = params.value("speed").toInt(current.value("speed").toInt(
            modePercent(mode.speed, mode.speedMin, mode.speedMax)));
        mode.speed = modeRange(speed, mode.speedMin, mode.speedMax);
    }
    const bool random = (mode.flags & 128U)
        && params.value("random").toBool(current.value("random").toBool());
    mode.colorMode = random ? 3 : (mode.flags & 32U) ? 1 : (mode.flags & 64U) ? 2
        : 0;
    QByteArray leds;
    const auto color = params.value("color").toString(
        mode.colorMode == 2 && unsigned(modeIndex) != controller.active
            ? current.value("color").toString() : QString());
    if (!color.isEmpty()) {
        const auto rgb = color.mid(1).toUInt(nullptr, 16);
        auto component = [&](int shift) {
            const auto value = (rgb >> shift) & 255;
            return native ? value : (value * brightness + 50) / 100;
        };
        const auto packed = component(16) | (component(8) << 8) | (component(0) << 16);
        if (mode.colorMode == 1) {
            if (controller.colors.isEmpty()) {
                return error("Mode requires controller LEDs");
            }
            mode.colors.clear();
            leds = sdkHalf(controller.colors.size());
            for (qsizetype i = 0; i < controller.colors.size(); ++i) {
                leds += sdkWord(packed);
            }
            leds.prepend(sdkWord(leds.size() + 4));
        } else if (mode.colorMode == 2) {
            const auto count = std::max(1U, mode.colorsMin);
            if (count > mode.colorsMax) {
                return error("Mode has no colour slots");
            }
            mode.colors.fill(packed, count);
        }
        if (!random) {
            writtenColor = QString("#%1%2%3").arg(packed & 255, 2, 16, QChar('0'))
                .arg((packed >> 8) & 255, 2, 16, QChar('0'))
                .arg((packed >> 16) & 255, 2, 16, QChar('0'));
        }
    }
    auto payload = sdkWord(modeIndex) + mode.encode(version);
    payload.prepend(sdkWord(payload.size() + 4));
    writtenMode = modeIndex;
    writtenDescriptor = mode;
    writtenBrightness = native ? qint64(mode.brightness) : -1;
    // A partial/rejected write must be saved from a fresh descriptor, not this attempt.
    appliedModes.remove(identity);
    unsaved.insert(identity);
    updateSaved();
    awaitingWriteAck = version >= 6;
    send(controller.index, 1101, payload);
    if (!leds.isEmpty()) {
        send(controller.index, 1050, leds);
    }
    return {};
}
