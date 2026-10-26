// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <algorithm>

class RetryBackoff {
public:
    int next()
    {
        const int current = milliseconds;
        milliseconds = std::min(60000, milliseconds * 2);
        return current;
    }
    void reset() { milliseconds = 2000; }

private:
    int milliseconds = 2000;
};
