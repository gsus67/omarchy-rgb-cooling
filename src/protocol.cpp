// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.hpp"
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QRegularExpression>
#include <QStringDecoder>
#include <cmath>

namespace Protocol {
bool Reply::ok() const
{
    return code.isEmpty();
}

Reply Reply::failure(const QString &code, const QString &message)
{
    return {{}, code, message};
}

bool integer(const QJsonValue &value)
{
    if (!value.isDouble()) {
        return false;
    }
    const double number = value.toDouble();
    return std::isfinite(number) && std::trunc(number) == number;
}

Reply parse(const QByteArray &line, Request &request)
{
    auto invalid = [](const QString &message) {
        return Reply::failure("bad_request", message);
    };
    QStringDecoder decoder(QStringDecoder::Utf8);
    const QString decoded = decoder.decode(line);
    Q_UNUSED(decoded);
    if (decoder.hasError()) {
        return invalid("Request must be valid UTF-8");
    }
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(line, &error);
    if (error.error != QJsonParseError::NoError || !document.isObject()) {
        return invalid("Request must be one JSON object");
    }
    const auto object = document.object();
    const auto id = object.value("id");
    if (integer(id) && id.toDouble() > 0) {
        request.id = id;
    }
    if (!integer(object.value("v")) || object.value("v").toDouble() != 1
        || request.id.isNull() || !object.value("op").isString()) {
        return invalid("Expected API v=1, a positive integer id and a string op");
    }
    if (object.contains("params") && !object.value("params").isObject()) {
        return invalid("params must be an object");
    }
    request.operation = object.value("op").toString();
    request.params = object.value("params").toObject();
    const auto &params = request.params;
    if (request.operation == "subscribe") {
        if (!params.value("topics").isArray()) {
            return invalid("topics must be an array");
        }
        for (const auto &topic : params.value("topics").toArray()) {
            if (!topic.isString()
                || (topic.toString() != "sensors" && topic.toString() != "devices")) {
                return invalid("Supported topics are sensors and devices");
            }
        }
        if (params.contains("interval_ms") && !integer(params.value("interval_ms"))) {
            return invalid("interval_ms must be an integer");
        }
    }
    if (request.operation == "lighting.get" || request.operation == "lighting.set") {
        if (!params.value("device").isString() || params.value("device").toString().isEmpty()) {
            return invalid("device must be a nonempty string");
        }
    }
    if (request.operation == "lighting.set") {
        static const QRegularExpression color("\\A#[0-9a-fA-F]{6}\\z");
        if (!params.value("color").isString()
            || !color.match(params.value("color").toString()).hasMatch()
            || !integer(params.value("brightness"))
            || params.value("brightness").toDouble() < 0
            || params.value("brightness").toDouble() > 100) {
            return invalid("Expected #rrggbb color and integer brightness from 0 to 100");
        }
    }
    return {};
}

QJsonObject response(const QJsonValue &id, const Reply &reply)
{
    QJsonObject result{{"v", 1}, {"id", id}, {"ok", reply.ok()}};
    if (reply.ok()) {
        result.insert("result", reply.result);
    } else {
        result.insert("error", QJsonObject{{"code", reply.code}, {"message", reply.message}});
    }
    return result;
}

QJsonObject event(const QString &topic, const QJsonObject &data)
{
    return {{"v", 1}, {"event", topic}, {"data", data}};
}
} // namespace Protocol
