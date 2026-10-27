// SPDX-License-Identifier: GPL-3.0-or-later
#include "selftest.hpp"
#include "demo.hpp"
#include "fan_headers.hpp"
#include "hwmon.hpp"
#include "openrgb.hpp"
#include "sdk_mode.hpp"
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
    checks.verify(valid({}, "profile.get")
                  && valid({{"topics", QJsonArray{"profile"}}}, "subscribe")
                  && valid({{"profile", "balanced"}}, "profile.set")
                  && valid({{"profile", "power-saver"}}, "profile.set")
                  && valid({{"profile", "performance"}}, "profile.set")
                  && !valid({{"profile", "turbo"}}, "profile.set")
                  && !valid({{"profile", true}}, "profile.set")
                  && !valid({}, "profile.set"), "power profiles use the closed API schema");
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
    SdkMode staticMode;
    staticMode.name = "Static";
    staticMode.flags = 16 | 32 | 256;
    staticMode.brightnessMin = 10;
    staticMode.brightnessMax = 90;
    staticMode.brightness = 50;
    staticMode.colorMode = 1;
    staticMode.colors = {0x332211};
    QByteArray modern = word(0) + text("Fake RGB") + text("Vendor") + text("USB")
        + text("1") + text("serial") + text("HID: /dev/hidraw9");
    modern += halfWord(1) + word(0) + staticMode.encode();
    modern += halfWord(0); // No zones.
    modern += halfWord(1) + text("LED"); // Protocol 6 omits led.value too.
    modern += halfWord(1) + word(0x332211);
    modern += halfWord(0) + word(0) + text("") + word(3) + QByteArray("{}\0", 3);
    modern.prepend(word(modern.size() + 4));
    SdkController decoded;
    checks.verify(SdkController::decode(modern, 6, decoded) && decoded.staticMode() == 0
                  && decoded.lighting().value("brightness").toInt() == 50,
                  "SDK v6 exact Static flags and native brightness decode");
    bool modernBounds = true;
    for (qsizetype length = 0; length < modern.size(); ++length) {
        modernBounds = modernBounds
            && !SdkController::decode(modern.first(length), 6, decoded);
    }
    checks.verify(modernBounds && !SdkController::decode(modern + 'x', 6, decoded),
                  "SDK v6 rejects every truncated descriptor and trailing bytes");
    quint32 modernSeed = 0x197912;
    for (int i = 0; i < 4000; ++i) {
        modernSeed = modernSeed * 1664525U + 1013904223U;
        auto mutated = modern;
        mutated[modernSeed % mutated.size()] = static_cast<char>(modernSeed >> 24);
        SdkController::decode(mutated, 6, decoded);
    }
    checks.verify(true, "SDK v6 malformed-input sanitizer corpus completed");
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
    checks.verify(hwmon.snapshot(500).value("sensors").toArray().first().toObject()
                  .value("value").isNull(), "hwmon non-finite values are null");
    QFile::remove(node + "/temp1_input");
    hwmon.sample(500);
    checks.verify(hwmon.snapshot(500).value("sensors").toArray().first().toObject()
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
    // Regression: CI hosts with another CPU vendor renamed a fake coretemp sensor.
    checks.verify(SensorNames::device("coretemp", "platform/coretemp.0", "", "AuthenticAMD")
                  == "Intel CPU"
                  && SensorNames::device("k10temp", "platform/k10temp.0", "", "GenuineIntel")
                  == "AMD CPU",
                  "the hwmon driver wins over the host cpuinfo vendor");
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
    checks.verify(SensorNames::device("r8169_0_600:00", "platform/mdio_bus", "mdio_bus", "")
                  == "Ethernet"
                  && SensorNames::device("igc_0", "", "other_driver", "") == "Ethernet"
                  && SensorNames::device("other", "platform/net/eth0", "", "") == "Ethernet",
                  "Ethernet names match hwmon prefixes or network parents");
    bool motherboard = true;
    for (const auto &name : {"nct6683", "nct6687", "nct6775", "nct6779", "it87", "it8689"}) {
        motherboard = motherboard && SensorNames::device(name, "", "", "") == "Motherboard"
            && SensorNames::label(name, "fan1", "CPU_FAN") == "Fan 1"
            && SensorNames::label(name, "fan2", "") == "Fan 2";
    }
    checks.verify(motherboard, "Super I/O sensors use Motherboard and numbered fan labels");
    checks.verify(SensorNames::label("", "temp1", "") == "Temperature"
                  && SensorNames::label("", "temp2", "") == "Temperature 2"
                  && SensorNames::label("", "fan1", "") == "Fan"
                  && SensorNames::label("", "fan2", "") == "Fan 2"
                  && SensorNames::label("", "temp1", "Package id 0") == "Package id 0",
                  "sensor labels use hwmon labels or human channel names");
}

void testRamNames(Checks &checks)
{
    QTemporaryDir temporary;
    const QString root = temporary.path() + "/class/hwmon";
    auto add = [&](const QString &number, const QString &address, const QString &value) {
        const QString parent = temporary.path() + "/devices/platform/i2c-8/8-" + address;
        const QString node = parent + "/hwmon/" + number;
        QDir().mkpath(node);
        QDir().mkpath(root);
        QFile name(node + "/name");
        name.open(QIODevice::WriteOnly);
        name.write("spd5118\n");
        QFile input(node + "/temp1_input");
        input.open(QIODevice::WriteOnly);
        input.write(value.toUtf8() + "\n");
        return QFile::link(node, root + "/" + number);
    };
    const bool created = add("hwmon1", "0053", "43000")
        && add("hwmon2", "0051", "42000");
    Hwmon hwmon(root);
    hwmon.sample(500);
    const auto sensors = hwmon.snapshot(500).value("sensors").toArray();
    QMap<QString, QString> labels;
    for (const auto &value : sensors) {
        const auto sensor = value.toObject();
        labels.insert(sensor.value("id").toString(), sensor.value("label").toString());
    }
    checks.verify(created && labels.value("spd5118:platform/i2c-8/8-0051:temp1") == "DIMM 1"
                  && labels.value("spd5118:platform/i2c-8/8-0053:temp1") == "DIMM 2",
                  "RAM labels follow numeric I2C bus and address order");
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

void testFanHeaders(Checks &checks, const QString &dataDirectory)
{
    const QByteArray valid = R"({"version":1,"entries":[{
        "chip":"nct6687","dmi_vendor":"MSI","dmi_boards":["MS-7D98"],
        "status":"user-verified","headers":{"fan5":"SYS_FAN3"}}]})";
    checks.verify(FanHeaders::validate(valid), "fan headers accept the v1 schema");
    bool rejected = true;
    for (const auto &invalid : {QByteArray("[]"), QByteArray("{"), QByteArray("\xff"),
                                QByteArray(FanHeaders::MaximumBytes + 1, ' ')}) {
        rejected = rejected && !FanHeaders::validate(invalid);
    }
    for (const auto &field : {"chip", "dmi_vendor", "dmi_boards", "status", "headers",
                              "verified", "sources"}) {
        auto table = QJsonDocument::fromJson(valid).object();
        auto entry = table.value("entries").toArray().first().toObject();
        entry.insert(field, true);
        table.insert("entries", QJsonArray{entry});
        rejected = rejected && !FanHeaders::validate(QJsonDocument(table).toJson());
    }
    for (const auto &name : {"sys_fan3", "<b>CPU</b>", "CPU_FAN1\n", "", "ABCDEFGHIJKLMNOPQ"}) {
        auto invalid = valid;
        // Replace a whole JSON string so escaped newlines also reach the validator.
        const auto quoted = QJsonDocument(QJsonArray{name}).toJson(QJsonDocument::Compact);
        invalid.replace("\"SYS_FAN3\"", quoted.sliced(1).chopped(1));
        rejected = rejected && !FanHeaders::validate(invalid);
    }
    checks.verify(rejected, "fan headers reject invalid types, names, UTF-8 and oversized JSON");
    quint32 seed = 0xabcdef;
    for (int index = 0; index < 1000; ++index) {
        seed = seed * 1664525U + 1013904223U;
        auto mutated = valid;
        mutated[seed % static_cast<quint32>(mutated.size())] = static_cast<char>(seed >> 24);
        FanHeaders::validate(mutated);
    }
    checks.verify(true, "fan headers malformed-input sanitizer corpus completed");
    if (!dataDirectory.isEmpty()) {
        QFile file(QDir(dataDirectory).filePath("fan-headers.json"));
        checks.verify(file.open(QIODevice::ReadOnly)
                      && FanHeaders::validate(file.read(FanHeaders::MaximumBytes + 1)),
                      "repository fan-headers.json passes the runtime schema");
    }
}
} // namespace

int runSelfTests(const QString &dataDirectory)
{
    Checks checks;
    testProtocol(checks);
    testSdk(checks);
    testSensorNames(checks);
    testRamNames(checks);
    testHwmon(checks);
    testDemo(checks);
    testFanHeaders(checks, dataDirectory);
    checks.verify(!Server::peerAllowed(-1, ::getuid()), "SO_PEERCRED rejects invalid descriptors");
    QTextStream(stdout) << "Self-tests: " << checks.failures << " failures\n";
    return checks.failures == 0 ? 0 : 1;
}
