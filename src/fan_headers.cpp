// SPDX-License-Identifier: GPL-3.0-or-later
#include "fan_headers.hpp"
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QRegularExpression>
#include <QStringDecoder>
#include <QTextStream>
#include <cerrno>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

namespace {
QByteArray readBounded(const QString &path, qint64 maximum, bool &ok)
{
    ok = false;
    // Opening a FIFO must never stall startup or the sensor worker.
    const int descriptor = ::open(QFile::encodeName(path).constData(),
                                  O_RDONLY | O_NONBLOCK | O_CLOEXEC);
    if (descriptor < 0) {
        return {};
    }
    struct stat status{};
    if (::fstat(descriptor, &status) != 0 || !S_ISREG(status.st_mode)
        || status.st_size > maximum) {
        ::close(descriptor);
        return {};
    }
    // Read through the same descriptor that fstat() checked, never by name again.
    QByteArray data;
    char buffer[4096];
    while (data.size() <= maximum) {
        const ssize_t count = ::read(descriptor, buffer, sizeof(buffer));
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count < 0) {
            ::close(descriptor);
            return {};
        }
        if (count == 0) {
            break;
        }
        data.append(buffer, count);
    }
    ::close(descriptor);
    ok = data.size() <= maximum;
    return data;
}

QString identity(const QString &path)
{
    bool ok = false;
    auto data = readBounded(path, 4096, ok);
    if (!ok) {
        return {};
    }
    if (data.endsWith('\n')) {
        data.chop(1);
    }
    return QString::fromUtf8(data);
}

bool keys(const QJsonObject &object, const QStringList &allowed)
{
    for (auto item = object.begin(); item != object.end(); ++item) {
        if (!allowed.contains(item.key())) {
            return false;
        }
    }
    return true;
}

bool strings(const QJsonValue &value)
{
    if (!value.isArray()) {
        return false;
    }
    for (const auto &item : value.toArray()) {
        if (!item.isString() || item.toString().isEmpty()) {
            return false;
        }
    }
    return true;
}
} // namespace

bool FanHeaders::parse(const QByteArray &data, QJsonObject &table)
{
    if (data.size() > MaximumBytes) {
        return false;
    }
    QStringDecoder decoder(QStringDecoder::Utf8);
    const auto decoded = decoder.decode(data);
    Q_UNUSED(decoded);
    if (decoder.hasError()) {
        return false;
    }
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(data, &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        return false;
    }
    table = document.object();
    const auto version = table.value("version");
    if (!keys(table, {"version", "entries"}) || !version.isDouble()
        || version.toDouble() != 1 || !table.value("entries").isArray()) {
        return false;
    }
    static const QRegularExpression channelPattern("\\Afan[0-9]{1,2}\\z");
    static const QRegularExpression namePattern("\\A[A-Z0-9_]{1,16}\\z");
    for (const auto &value : table.value("entries").toArray()) {
        if (!value.isObject()) {
            return false;
        }
        const auto entry = value.toObject();
        if (!keys(entry, {"chip", "dmi_vendor", "dmi_boards", "status", "headers",
                          "verified", "sources"})
            || !entry.value("chip").isString() || entry.value("chip").toString().isEmpty()
            || !entry.value("dmi_vendor").isString()
            || entry.value("dmi_vendor").toString().isEmpty()
            || !strings(entry.value("dmi_boards"))
            || entry.value("dmi_boards").toArray().isEmpty()
            || !entry.value("status").isString()
            || (entry.value("status") != "user-verified"
                && entry.value("status") != "source-derived")
            || !entry.value("headers").isObject()
            || (entry.contains("verified") && !entry.value("verified").isString())
            || (entry.contains("sources") && !strings(entry.value("sources")))) {
            return false;
        }
        const auto headers = entry.value("headers").toObject();
        for (auto item = headers.begin(); item != headers.end(); ++item) {
            if (!channelPattern.match(item.key()).hasMatch() || !item.value().isString()
                || !namePattern.match(item.value().toString()).hasMatch()) {
                return false;
            }
        }
    }
    return true;
}

bool FanHeaders::validate(const QByteArray &data)
{
    QJsonObject table;
    return parse(data, table);
}

bool FanHeaders::load(const QString &dataDirectory, const QString &dmiRoot)
{
    chips.clear();
    bool ok = false;
    const auto path = dataDirectory.isEmpty() ? QString{}
                                            : QDir(dataDirectory).filePath("fan-headers.json");
    const auto data = readBounded(path, MaximumBytes, ok);
    QJsonObject table;
    if (!ok || !parse(data, table)) {
        QTextStream(stderr) << "rgbcd: warning: fan-headers.json missing, oversized or invalid; "
                               "ignoring the entire table\n";
        return false;
    }
    const auto vendor = identity(QDir(dmiRoot).filePath("board_vendor"));
    const auto board = identity(QDir(dmiRoot).filePath("board_name"));
    if (vendor.isEmpty() || board.isEmpty()) {
        return true;
    }
    for (const auto &value : table.value("entries").toArray()) {
        const auto entry = value.toObject();
        if (entry.value("status") != "user-verified" || entry.value("dmi_vendor") != vendor
            || !entry.value("dmi_boards").toArray().contains(board)) {
            continue;
        }
        const auto headers = entry.value("headers").toObject();
        auto &channels = chips[entry.value("chip").toString()];
        for (auto item = headers.begin(); item != headers.end(); ++item) {
            channels.insert(item.key(), item.value().toString());
        }
    }
    return true;
}

QString FanHeaders::header(const QString &chip, const QString &channel) const
{
    const auto found = chips.constFind(chip);
    return found == chips.cend() ? QString{} : found->value(channel);
}
