// SPDX-License-Identifier: GPL-3.0-or-later
#include "hotplug.hpp"
#include <libudev.h>

Hotplug::Hotplug(std::function<void(QVector<HotplugEvent>)> reconcile)
{
    context = udev_new();
    if (context == nullptr) {
        return;
    }
    // The processed udev channel includes resolved parents; kernel events do not.
    monitor = udev_monitor_new_from_netlink(context, "udev");
    if (monitor == nullptr
        || udev_monitor_filter_add_match_subsystem_devtype(monitor, "hwmon", nullptr) < 0
        || udev_monitor_filter_add_match_subsystem_devtype(monitor, "usb", nullptr) < 0
        || udev_monitor_filter_add_match_subsystem_devtype(monitor, "hidraw", nullptr) < 0
        || udev_monitor_enable_receiving(monitor) < 0) {
        return;
    }
    notifier = std::make_unique<QSocketNotifier>(udev_monitor_get_fd(monitor),
                                                 QSocketNotifier::Read);
    connect(notifier.get(), &QSocketNotifier::activated, this,
            [this, reconcile] { drain(reconcile); });
}

Hotplug::~Hotplug()
{
    notifier.reset();
    if (monitor != nullptr) {
        udev_monitor_unref(monitor);
    }
    if (context != nullptr) {
        udev_unref(context);
    }
}

bool Hotplug::active() const
{
    return notifier != nullptr;
}

void Hotplug::drain(const std::function<void(QVector<HotplugEvent>)> &reconcile)
{
    // Reconcile the complete inventory instead of treating event payloads as paths.
    QVector<HotplugEvent> events;
    for (int count = 0; count < 256; ++count) {
        udev_device *device = udev_monitor_receive_device(monitor);
        if (device == nullptr) {
            break;
        }
        HotplugEvent event;
        event.action = QString::fromUtf8(udev_device_get_action(device));
        event.node = QString::fromUtf8(udev_device_get_devnode(device));
        event.path = QString::fromUtf8(udev_device_get_syspath(device));
        auto *parent = udev_device_get_parent_with_subsystem_devtype(device, "usb", "usb_device");
        if (QString::fromUtf8(udev_device_get_subsystem(device)) == "usb"
            && QString::fromUtf8(udev_device_get_devtype(device)) == "usb_device") {
            parent = device;
        }
        if (parent) {
            const auto vid = QString::fromUtf8(udev_device_get_sysattr_value(parent, "idVendor"));
            const auto pid = QString::fromUtf8(udev_device_get_sysattr_value(parent, "idProduct"));
            const auto serial = QString::fromUtf8(udev_device_get_sysattr_value(parent, "serial"));
            if (!vid.isEmpty() && !pid.isEmpty()) {
                event.identity = "usb:" + vid.toLower() + ":" + pid.toLower() + ":" + serial;
            }
        }
        events.append(event);
        udev_device_unref(device);
    }
    if (!events.isEmpty()) {
        reconcile(events);
    }
}
