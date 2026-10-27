// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QByteArray>
#include <QString>

// Bounds are checked before every access; peer lengths never control allocation.
class SdkReader {
public:
    explicit SdkReader(const QByteArray &bytes);
    quint16 u16();
    quint32 u32();
    QString string(bool wide = false);
    bool skip(qsizetype count);
    bool done() const;
    bool valid() const;

private:
    const QByteArray &bytes;
    qsizetype offset = 0;
    bool good = true;
};
