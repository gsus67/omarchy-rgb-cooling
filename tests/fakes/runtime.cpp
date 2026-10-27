// SPDX-License-Identifier: GPL-3.0-or-later
// Isolate CPU identity and optionally control monotonic time in contract-test children.
#include <arpa/inet.h>
#include <cerrno>
#include <cstdarg>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

extern "C" int open64(const char *path, int flags, ...)
{
    mode_t mode = 0;
    if ((flags & O_CREAT) || (flags & O_TMPFILE) == O_TMPFILE) {
        va_list arguments;
        va_start(arguments, flags);
        mode = va_arg(arguments, mode_t);
        va_end(arguments);
    }
    // Hwmon's fallback must never read the runner's CPU vendor.
    if (std::strcmp(path, "/proc/cpuinfo") == 0) {
        path = "/dev/null";
    }
    return static_cast<int>(::syscall(SYS_openat, AT_FDCWD, path, flags, mode));
}

extern "C" int clock_gettime(clockid_t clock, timespec *result) noexcept
{
    using Function = int (*)(clockid_t, timespec *);
    static const auto original = reinterpret_cast<Function>(dlsym(RTLD_NEXT, "clock_gettime"));
    if (clock == CLOCK_MONOTONIC) {
        const char *path = std::getenv("CORE_TEST_CLOCK");
        if (path) {
            const int saved = errno;
            const int fd = static_cast<int>(::syscall(SYS_openat, AT_FDCWD, path, O_RDONLY, 0));
            struct Clock {
                long long nanoseconds;
                long long realStarted;
            } value{};
            const auto size = fd < 0 ? -1 : ::read(fd, &value, sizeof(value));
            if (fd >= 0) {
                ::close(fd);
            }
            if (size != sizeof(value)) {
                // A missing/partial clock is a fixture error, never fall back to host time.
                std::abort();
            }
            if (value.realStarted) {
                timespec real{};
                if (original(clock, &real) != 0) {
                    return -1;
                }
                value.nanoseconds += real.tv_sec * 1000000000LL + real.tv_nsec - value.realStarted;
            }
            result->tv_sec = value.nanoseconds / 1000000000LL;
            result->tv_nsec = value.nanoseconds % 1000000000LL;
            errno = saved;
            return 0;
        }
    }
    return original(clock, result);
}

// Redirect the production SDK endpoint to a private fake; never contact a host engine.
extern "C" int connect(int fd, const sockaddr *address, socklen_t length)
{
    using Function = int (*)(int, const sockaddr *, socklen_t);
    static const auto original = reinterpret_cast<Function>(dlsym(RTLD_NEXT, "connect"));
    if (address->sa_family == AF_INET && length >= sizeof(sockaddr_in)) {
        auto target = *reinterpret_cast<const sockaddr_in *>(address);
        if (target.sin_addr.s_addr == htonl(INADDR_LOOPBACK) && target.sin_port == htons(6742)) {
            if (const char *log = std::getenv("CORE_TEST_OPENRGB_CONNECTS")) {
                timespec now{};
                clock_gettime(CLOCK_MONOTONIC, &now);
                const long long stamp = now.tv_sec * 1000000000LL + now.tv_nsec;
                const int output = static_cast<int>(::syscall(
                    SYS_openat, AT_FDCWD, log, O_WRONLY | O_CREAT | O_APPEND, 0600));
                if (output < 0 || ::write(output, &stamp, sizeof(stamp)) != sizeof(stamp)) {
                    std::abort();
                }
                ::close(output);
            }
            const char *port = std::getenv("CORE_TEST_OPENRGB_PORT");
            if (!port) {
                errno = ECONNREFUSED;
                return -1;
            }
            target.sin_port = htons(static_cast<unsigned short>(std::atoi(port)));
            return original(fd, reinterpret_cast<const sockaddr *>(&target), sizeof(target));
        }
    }
    return original(fd, address, length);
}
