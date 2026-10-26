// SPDX-License-Identifier: GPL-3.0-or-later
#include "protocol.hpp"
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QMap>
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

namespace {
enum class Type { Device, Color, Brightness, Topics, Interval };
struct Field {
    const char *name;
    Type type;
    bool required = true;
};

bool matches(const QJsonValue &value, Type type)
{
    switch (type) {
    case Type::Device:
        return value.isString() && !value.toString().isEmpty();
    case Type::Color: {
        static const QRegularExpression pattern("\\A#[0-9a-fA-F]{6}\\z");
        return value.isString() && pattern.match(value.toString()).hasMatch();
    }
    case Type::Brightness:
        return integer(value) && value.toDouble() >= 0 && value.toDouble() <= 100;
    case Type::Topics:
        if (!value.isArray()) {
            return false;
        }
        for (const auto &topic : value.toArray()) {
            if (!topic.isString() || (topic != "sensors" && topic != "devices")) {
                return false;
            }
        }
        return true;
    case Type::Interval:
        return integer(value);
    }
    return false;
}

Reply validate(const QString &operation, const QJsonObject &params)
{
    // Closed operation set with an explicit parameter schema for every operation.
    static const QMap<QString, QList<Field>> schemas{
        {"hello", {}}, {"status", {}}, {"sensors", {}}, {"devices", {}},
        {"unsubscribe", {}},
        {"subscribe", {{"topics", Type::Topics}, {"interval_ms", Type::Interval, false}}},
        {"lighting.get", {{"device", Type::Device}}},
        {"lighting.set", {{"device", Type::Device}, {"color", Type::Color},
                          {"brightness", Type::Brightness}}}
    };
    const auto schema = schemas.constFind(operation);
    if (schema == schemas.cend()) {
        return Reply::failure("unknown_op", "Operation is not supported by API v1");
    }
    for (const auto &field : *schema) {
        if (!field.required && !params.contains(field.name)) {
            continue;
        }
        if (!matches(params.value(field.name), field.type)) {
            return Reply::failure("bad_request", QString("Invalid parameter: %1").arg(field.name));
        }
    }
    return {};
}
} // namespace

Reply parse(const QByteArray &line, Request &request)
{
    request = {};
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
    if (integer(id) && id.toDouble() >= 1 && id.toDouble() <= 9007199254740991.0) {
        request.id = id;
    }
    if (!integer(object.value("v")) || object.value("v").toDouble() != 1
        || request.id.isNull() || !object.value("op").isString()) {
        return invalid("Expected API v=1, an integer id in 1..2^53-1 and a string op");
    }
    if (object.contains("params") && !object.value("params").isObject()) {
        return invalid("params must be an object");
    }
    request.operation = object.value("op").toString();
    request.params = object.value("params").toObject();
    const auto validation = validate(request.operation, request.params);
    if (validation.ok() && request.operation == "lighting.set") {
        request.params.insert("color", request.params.value("color").toString().toLower());
    }
    return validation;
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
