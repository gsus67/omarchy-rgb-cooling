// SPDX-License-Identifier: GPL-3.0-or-later
// Inject a kernel credential mismatch without requiring root or changing system users.
#include <dlfcn.h>
#include <sys/socket.h>

extern "C" int getsockopt(int fd, int level, int option, void *value, socklen_t *length)
{
    using Function = int (*)(int, int, int, void *, socklen_t *);
    static const auto original = reinterpret_cast<Function>(dlsym(RTLD_NEXT, "getsockopt"));
    if (original == nullptr) {
        return -1;
    }
    const int result = original(fd, level, option, value, length);
    if (result == 0 && level == SOL_SOCKET && option == SO_PEERCRED
        && *length == sizeof(struct ucred)) {
        auto *credentials = static_cast<struct ucred *>(value);
        ++credentials->uid;
    }
    return result;
}
