// SPDX-License-Identifier: GPL-3.0-or-later
#include "sdk_reader.hpp"
#include <QStringDecoder>
#include <QtEndian>

SdkReader::SdkReader(const QByteArray &bytes) : bytes(bytes)
{
}

quint16 SdkReader::u16()
{
    if (!skip(2)) {
        return 0;
    }
    return qFromLittleEndian<quint16>(bytes.constData() + offset - 2);
}

quint32 SdkReader::u32()
{
    if (!skip(4)) {
        return 0;
    }
    return qFromLittleEndian<quint32>(bytes.constData() + offset - 4);
}

QString SdkReader::string(bool wide)
{
    const auto length = wide ? u32() : u16();
    if (length == 0 || length > 4096 || !skip(length)) {
        good = false;
        return {};
    }
    const QByteArray value = bytes.mid(offset - length, length);
    if (value.back() != '\0' || value.indexOf('\0') != length - 1) {
        good = false;
        return {};
    }
    QStringDecoder decoder(QStringDecoder::Utf8);
    const QString decoded = decoder.decode(value.first(length - 1));
    if (decoder.hasError()) {
        good = false;
    }
    return decoded;
}

bool SdkReader::skip(qsizetype count)
{
    if (!good || count < 0 || count > bytes.size() - offset) {
        good = false;
        return false;
    }
    offset += count;
    return true;
}

bool SdkReader::done() const
{
    return good && offset == bytes.size();
}

bool SdkReader::valid() const
{
    return good;
}
