// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <QString>

namespace SensorNames {
QString device(const QString &hwmonName, const QString &parentPath,
               const QString &driver, const QString &cpuVendor, int nvmeNumber = 0);
QString label(const QString &hwmonName, const QString &channel, const QString &customLabel);
}
