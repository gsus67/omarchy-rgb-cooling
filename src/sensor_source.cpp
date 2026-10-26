// SPDX-License-Identifier: GPL-3.0-or-later
#include "sensor_source.hpp"
#include <utility>

SensorSource::SensorSource(const QString &root) : worker(new QObject), hwmon(root)
{
    worker->moveToThread(&thread);
    connect(&thread, &QThread::finished, worker, &QObject::deleteLater);
    thread.start();
}

SensorSource::~SensorSource()
{
    thread.quit();
    thread.wait();
}

void SensorSource::invalidate()
{
    ++generation;
    age.invalidate();
}

void SensorSource::request(int intervalMilliseconds, Callback ready)
{
    if (age.isValid() && age.elapsed() < 500) {
        ready(cached);
        return;
    }
    pending.push_back(std::move(ready));
    if (sampling) {
        return;
    }
    sampling = true;
    const auto startedGeneration = generation;
    QMetaObject::invokeMethod(worker, [this, intervalMilliseconds, startedGeneration] {
        hwmon.sample(intervalMilliseconds);
        const auto result = hwmon.snapshot(intervalMilliseconds);
        QElapsedTimer sampled;
        sampled.start();
        QMetaObject::invokeMethod(this, [this, result, startedGeneration, sampled] {
            sampling = false;
            cached = result;
            if (generation == startedGeneration) {
                age = sampled;
            }
            auto callbacks = std::exchange(pending, {});
            for (const auto &callback : callbacks) {
                callback(cached);
            }
        }, Qt::QueuedConnection);
    }, Qt::QueuedConnection);
}
