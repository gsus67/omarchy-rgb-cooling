// SPDX-License-Identifier: GPL-3.0-or-later
#include "selftest.hpp"
#include "demo.hpp"
#include "hwmon.hpp"
#include "openrgb.hpp"
#include "protocol.hpp"
#include "sdk_reader.hpp"
#include "server.hpp"
#include "sensor_names.hpp"
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <QTextStream>
#include <QtEndian>
#include <unistd.h>

namespace {
class Checks {
public:
    int failures = 0;
    void verify(bool condition, const char *name)
    {
        QTextStream(condition ? stdout : stderr)
            << (condition ? "PASS " : "FAIL ") << name << '\n';
        if (!condition) {
            ++failures;
        }
    }
};

QByteArray word(quint32 value)
{
    QByteArray result(4, '\0');
    qToLittleEndian(value, result.data());
    return result;
}

QByteArray halfWord(quint16 value)
{
    QByteArray result(2, '\0');
    qToLittleEndian(value, result.data());
    return result;
}

QByteArray text(const QByteArray &value)
{
    return halfWord(value.size() + 1) + value + '\0';
}

void testProtocol(Checks &checks)
{
    Protocol::Request request;
    checks.verify(Protocol::parse(R"({"v":1,"id":7,"op":"hello"})", request).ok()
                  && request.id.toInt() == 7, "API v1 request envelope");
    bool rejected = true;
    for (const auto &line : {QByteArray("[]"), QByteArray("\xff"),
                             QByteArray(R"({"v":true,"id":1,"op":"hello"})"),
                             QByteArray(R"({"v":1,"id":0,"op":"hello"})"),
                             QByteArray(R"({"v":1,"id":1,"op":"hello","params":[]})"),
                             QByteArray(R"({"v":1,"id":1.5,"op":"hello"})")}) {
        Protocol::Request invalid;
        rejected = rejected && !Protocol::parse(line, invalid).ok();
    }
    checks.verify(rejected, "bad_request rejects invalid envelope types and UTF-8");
    auto valid = [](const QJsonObject &params, const QString &op) {
        const QJsonObject envelope{{"v", 1}, {"id", 7}, {"op", op}, {"params", params}};
        Protocol::Request parsed;
        return Protocol::parse(QJsonDocument(envelope).toJson(), parsed).ok();
    };
    checks.verify(valid({}, "devices.rescan"), "devices.rescan accepts empty parameters");
    const QJsonObject lighting{{"device", "demo:rgb0"}, {"color", "#aAbBcC"},
                               {"brightness", 50}};
    checks.verify(valid(lighting, "lighting.set"), "lighting.set accepts RGB and brightness");
    bool badColor = true;
    for (const auto &color : {"#123456\n", "#123", "red", "#gg1234"}) {
        auto invalid = lighting;
        invalid.insert("color", color);
        badColor = badColor && !valid(invalid, "lighting.set");
    }
    checks.verify(badColor, "lighting.set rejects malformed and newline-suffixed colors");
    bool badBrightness = true;
    for (const auto &brightness : {QJsonValue(-1), QJsonValue(101), QJsonValue(1.5),
                                   QJsonValue(true), QJsonValue("50")}) {
        auto invalid = lighting;
        invalid.insert("brightness", brightness);
        badBrightness = badBrightness && !valid(invalid, "lighting.set");
    }
    checks.verify(badBrightness, "lighting.set rejects invalid brightness types and bounds");
    checks.verify(valid({{"topics", QJsonArray{"sensors"}}, {"interval_ms", -10}}, "subscribe")
                  && !valid({{"topics", QJsonArray{false}}}, "subscribe")
                  && !valid({{"topics", QJsonArray{"unknown"}}}, "subscribe"),
                  "subscribe validates topic types and leaves interval clamping to server");
    const auto failure = Protocol::response(7, Protocol::Reply::failure("blocked", "Plain text"));
    checks.verify(!failure.value("ok").toBool() && failure.value("id").toInt() == 7,
                  "error envelope echoes id");
    checks.verify(!Protocol::event("sensors", {}).contains("id"), "events have no id");
}

QByteArray controller(const QByteArray &location)
{
    QByteArray result = word(0) + text("Fake RGB") + text("Vendor") + text("USB")
        + text("1") + text("serial") + text(location);
    result += halfWord(1) + word(0) + text("Static");
    for (int field = 0; field < 9; ++field) {
        result += word(0);
    }
    result += halfWord(1) + word(0x00332211);
    result += halfWord(1) + text("All") + word(1) + word(1) + word(1) + word(1);
    result += halfWord(12) + word(1) + word(1) + word(0); // One matrix cell.
    result += halfWord(1) + text("LED") + word(0);
    result += halfWord(1) + word(0x00332211);
    result.prepend(word(result.size() + 4));
    return result;
}

void testSdk(Checks &checks)
{
    const QByteArray empty;
    SdkReader reader(empty);
    checks.verify(reader.u32() == 0 && !reader.valid(), "SDK truncated integer bounds");
    const auto descriptor = controller("USB:1462:7d98:port1");
    QJsonObject device;
    QJsonObject lighting;
    checks.verify(OpenRgbAdapter::decodeController(descriptor, 1, device, lighting)
                  && !device.value("writable").toBool()
                  && lighting.value("color").toString() == "#112233",
                  "SDK modes, matrix, LEDs and colors decode read-only");
    bool allRejected = true;
    for (qsizetype length = 0; length < descriptor.size(); ++length) {
        allRejected = allRejected
            && !OpenRgbAdapter::decodeController(descriptor.first(length), 1, device, lighting);
    }
    checks.verify(allRejected, "SDK rejects every truncated descriptor");
    checks.verify(!OpenRgbAdapter::decodeController(descriptor + 'x', 1, device, lighting)
                  && !OpenRgbAdapter::decodeController(descriptor, 6, device, lighting),
                  "SDK rejects trailing bytes and unnegotiated descriptor versions");
    for (const auto &location : {"USB:0416:5302:port1", "HID:VID_0416&PID_5302", "Trofeo"}) {
        QJsonObject excluded;
        QJsonObject noLighting;
        checks.verify(OpenRgbAdapter::decodeController(controller(location), 1,
                                                       excluded, noLighting)
                      && excluded.value("excluded").toBool()
                      && excluded.value("capabilities").toArray().isEmpty()
                      && noLighting.isEmpty(), "0416:5302 exclusion has no lighting capabilities");
    }
    quint32 seed = 0x12345678;
    for (int index = 0; index < 4000; ++index) {
        seed = seed * 1664525U + 1013904223U;
        QByteArray mutated = descriptor;
        const auto position = seed % static_cast<quint32>(mutated.size());
        mutated[position] = static_cast<char>(seed >> 24);
        OpenRgbAdapter::decodeController(mutated, 1, device, lighting);
        Protocol::Request malformed;
        Protocol::parse(mutated, malformed);
    }
    checks.verify(true, "SDK and JSON malformed-input sanitizer corpus completed");
}

bool writeFixture(const QString &path, const QByteArray &value)
{
    QFile file(path);
    return file.open(QIODevice::WriteOnly) && file.write(value) == value.size();
}

void testHwmon(Checks &checks)
{
    QTemporaryDir temporary;
    const QString parent = temporary.path() + "/devices/platform/coretemp.0";
    const QString node = parent + "/hwmon/hwmon8";
    const QString root = temporary.path() + "/class/hwmon";
    bool fixture = QDir().mkpath(node) && QDir().mkpath(root);
    fixture = fixture && writeFixture(node + "/name", "coretemp\n")
        && writeFixture(node + "/temp1_label", "Package id 0\n")
        && writeFixture(node + "/temp1_input", "42500\n")
        && writeFixture(node + "/fan1_input", "0\n")
        && writeFixture(node + "/pwm1", "38\n")
        && QFile::link(node, root + "/hwmon8");
    checks.verify(fixture, "fake hwmon fixture created");
    Hwmon hwmon(root);
    checks.verify(hwmon.snapshot(500).value("sensors").toArray().isEmpty(),
                  "hwmon construction performs no value reads");
    hwmon.sample(500);
    const auto snapshot = hwmon.snapshot(500);
    checks.verify(snapshot.value("primary").toString() == "coretemp:platform/coretemp.0:temp1",
                  "hwmon stable canonical parent and CPU package primary");
    bool temperature = false;
    bool fan = false;
    for (const auto &item : snapshot.value("sensors").toArray()) {
        const auto sensor = item.toObject();
        temperature = temperature || (sensor.value("kind") == "temp"
                                      && sensor.value("value").toDouble() == 42.5);
        fan = fan || (sensor.value("kind") == "fan" && sensor.value("value").toInt(-1) == 0);
    }
    checks.verify(temperature && fan, "hwmon converts millidegrees and preserves zero RPM");
    writeFixture(node + "/temp1_input", "NaN\n");
    hwmon.sample(500);
    checks.verify(hwmon.snapshot(500).value("sensors").toArray().last().toObject()
                  .value("value").isNull(), "hwmon non-finite values are null");
    QFile::remove(node + "/temp1_input");
    hwmon.sample(500);
    checks.verify(hwmon.snapshot(500).value("sensors").toArray().last().toObject()
                  .value("value").isNull(), "hwmon missing input is null");
    QFile pwm(node + "/pwm1");
    checks.verify(pwm.open(QIODevice::ReadOnly) && pwm.readAll() == "38\n",
                  "hwmon leaves PWM bytes unchanged");
}

void testSensorNames(Checks &checks)
{
    checks.verify(SensorNames::device("coretemp", "platform/coretemp.0", "", "")
                  == "Intel CPU", "coretemp names the Intel CPU");
    checks.verify(SensorNames::device("k10temp", "platform/k10temp.0", "", "")
                  == "AMD CPU"
                  && SensorNames::device("cpu_thermal", "", "", "AuthenticAMD") == "AMD CPU",
                  "AMD CPU name uses hwmon driver or cpuinfo vendor");
    checks.verify(SensorNames::device("amdgpu", "", "amdgpu", "") == "AMD GPU"
                  && SensorNames::device("gpu", "", "nouveau", "") == "NVIDIA GPU"
                  && SensorNames::device("xe", "", "xe", "") == "Intel GPU",
                  "GPU names follow their kernel driver");
    checks.verify(SensorNames::device("nvme", "", "", "", 2) == "NVMe 2"
                  && SensorNames::device("spd5118", "", "", "") == "RAM"
                  && SensorNames::device("iwlwifi_1", "", "", "") == "Wi-Fi"
                  && SensorNames::device("r8169", "", "", "") == "Ethernet"
                  && SensorNames::device("acpitz", "", "", "") == "ACPI",
                  "storage, memory, network and ACPI names follow the contract");
    checks.verify(SensorNames::label("", "temp1", "") == "Temperature"
                  && SensorNames::label("", "temp2", "") == "Temperature 2"
                  && SensorNames::label("", "fan1", "") == "Fan"
                  && SensorNames::label("", "fan2", "") == "Fan 2"
                  && SensorNames::label("", "temp1", "Package id 0") == "Package id 0",
                  "sensor labels use hwmon labels or human channel names");
}

void testDemo(Checks &checks)
{
    DemoAdapter demo;
    checks.verify(demo.setLighting("demo:rgb0", "#123456", 30).ok(), "demo is writable");
    checks.verify(demo.lighting("demo:rgb0").result.value("brightness").toInt() == 30,
                  "lighting.get returns applied brightness");
    checks.verify(!demo.setLighting("missing", "#123456", 10).ok(),
                  "missing demo device is unavailable");
}
} // namespace

int runSelfTests()
{
    Checks checks;
    testProtocol(checks);
    testSdk(checks);
    testSensorNames(checks);
    testHwmon(checks);
    testDemo(checks);
    checks.verify(!Server::peerAllowed(-1, ::getuid()), "SO_PEERCRED rejects invalid descriptors");
    QTextStream(stdout) << "Self-tests: " << checks.failures << " failures\n";
    return checks.failures == 0 ? 0 : 1;
}
