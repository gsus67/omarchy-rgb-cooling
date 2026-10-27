// SPDX-License-Identifier: GPL-3.0-or-later
// Feed libudev notifications through a private FIFO without touching host devices.
#include <libudev.h>
#include <cstdlib>
#include <string>
#include <sstream>
#include <vector>
#include <fcntl.h>
#include <unistd.h>

namespace {
struct Monitor {
    int fd;
};
int context;
struct Device {
    std::string action, node, identity, path, vid, pid, serial;
} device;
}

extern "C" udev *udev_new()
{
    return reinterpret_cast<udev *>(&context);
}

extern "C" udev *udev_unref(udev *)
{
    return nullptr;
}

extern "C" udev_monitor *udev_monitor_new_from_netlink(udev *, const char *)
{
    const char *path = std::getenv("CORE_TEST_UDEV_FIFO");
    const int fd = path ? ::open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC) : -1;
    return fd < 0 ? nullptr : reinterpret_cast<udev_monitor *>(new Monitor{fd});
}

extern "C" udev_monitor *udev_monitor_unref(udev_monitor *monitor)
{
    auto *value = reinterpret_cast<Monitor *>(monitor);
    ::close(value->fd);
    delete value;
    return nullptr;
}

extern "C" int udev_monitor_filter_add_match_subsystem_devtype(
    udev_monitor *, const char *, const char *)
{
    return 0;
}

extern "C" int udev_monitor_enable_receiving(udev_monitor *)
{
    return 0;
}

extern "C" int udev_monitor_get_fd(udev_monitor *monitor)
{
    return reinterpret_cast<Monitor *>(monitor)->fd;
}

extern "C" udev_device *udev_monitor_receive_device(udev_monitor *monitor)
{
    char byte;
    if (::read(reinterpret_cast<Monitor *>(monitor)->fd, &byte, 1) != 1) {
        return nullptr;
    }
    device = {};
    if (byte != '+') {
        std::string line(1, byte);
        while (::read(reinterpret_cast<Monitor *>(monitor)->fd, &byte, 1) == 1 && byte != '\n') {
            line += byte;
        }
        std::istringstream stream(line);
        std::getline(stream, device.action, '|');
        std::getline(stream, device.node, '|');
        std::getline(stream, device.identity, '|');
        std::getline(stream, device.path, '|');
        if (device.identity.size() >= 14) {
            device.vid = device.identity.substr(4, 4);
            device.pid = device.identity.substr(9, 4);
            device.serial = device.identity.substr(14);
        }
    }
    return reinterpret_cast<udev_device *>(&device);
}

extern "C" udev_device *udev_device_unref(udev_device *)
{
    if (const char *path = std::getenv("CORE_TEST_UDEV_ACK_FIFO")) {
        const int fd = ::open(path, O_WRONLY | O_NONBLOCK | O_CLOEXEC);
        if (fd >= 0) {
            const char byte = '+';
            ::write(fd, &byte, 1);
            ::close(fd);
        }
    }
    return nullptr;
}

extern "C" const char *udev_device_get_action(udev_device *) { return device.action.c_str(); }
extern "C" const char *udev_device_get_devnode(udev_device *) { return device.node.c_str(); }
extern "C" const char *udev_device_get_syspath(udev_device *) { return device.path.c_str(); }
extern "C" const char *udev_device_get_subsystem(udev_device *) { return "hidraw"; }
extern "C" const char *udev_device_get_devtype(udev_device *) { return nullptr; }
extern "C" udev_device *udev_device_get_parent_with_subsystem_devtype(
    udev_device *value, const char *, const char *)
{
    return device.identity.empty() ? nullptr : value;
}
extern "C" const char *udev_device_get_sysattr_value(udev_device *, const char *key)
{
    const std::string name(key);
    if (name == "idVendor") { return device.vid.c_str(); }
    if (name == "idProduct") { return device.pid.c_str(); }
    if (name == "serial") { return device.serial.c_str(); }
    return nullptr;
}
