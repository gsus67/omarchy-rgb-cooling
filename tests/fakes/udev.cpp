// SPDX-License-Identifier: GPL-3.0-or-later
// Feed libudev notifications through a private FIFO without touching host devices.
#include <libudev.h>
#include <cstdlib>
#include <fcntl.h>
#include <unistd.h>

namespace {
struct Monitor {
    int fd;
};
int context;
int device;
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
    return ::read(reinterpret_cast<Monitor *>(monitor)->fd, &byte, 1) == 1
        ? reinterpret_cast<udev_device *>(&device) : nullptr;
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
