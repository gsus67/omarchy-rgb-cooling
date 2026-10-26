// SPDX-License-Identifier: GPL-3.0-or-later
#include "listener.hpp"
#include "protocol.hpp"
#include <QFile>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

void PeerServer::incomingConnection(quintptr descriptor)
{
    if (accepted) {
        accepted(descriptor);
    } else {
        ::close(static_cast<int>(descriptor));
    }
}

Listener::~Listener()
{
    notifier.reset();
    if (activation >= 0) {
        ::close(activation);
    }
}

bool Listener::listen(const QString &path, QString &error)
{
    const auto encoded = QFile::encodeName(path);
    struct stat metadata {};
    if (::lstat(encoded.constData(), &metadata) == 0) {
        error = S_ISSOCK(metadata.st_mode) ? "Socket path already exists"
                                         : "Refusing to replace a non-socket file";
        return false;
    }
    if (errno != ENOENT) {
        error = QString::fromLocal8Bit(std::strerror(errno));
        return false;
    }
    owned.accepted = [this](qintptr fd) { accepted(fd); };
    owned.setMaxPendingConnections(Protocol::MaxConnections);
    owned.setSocketOptions(QLocalServer::UserAccessOption);
    if (!owned.listen(path)) {
        error = owned.errorString();
        return false;
    }
    if (::chmod(encoded.constData(), 0600) != 0) {
        error = "Could not restrict socket permissions";
        owned.close();
        return false;
    }
    return true;
}

bool Listener::adopt(qintptr descriptor, QString &error)
{
    const int fd = static_cast<int>(descriptor);
    int type = 0;
    int accepting = 0;
    socklen_t length = sizeof(type);
    sockaddr_un address {};
    socklen_t addressLength = sizeof(address);
    if (::getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &length) != 0 || type != SOCK_STREAM
        || ::getsockopt(fd, SOL_SOCKET, SO_ACCEPTCONN, &accepting, &length) != 0 || !accepting
        || ::getsockname(fd, reinterpret_cast<sockaddr *>(&address), &addressLength) != 0
        || address.sun_family != AF_UNIX) {
        error = "Activation descriptor must be a listening Unix stream socket";
        return false;
    }
    const int flags = ::fcntl(fd, F_GETFD);
    const int status = ::fcntl(fd, F_GETFL);
    if (flags < 0 || status < 0 || ::fcntl(fd, F_SETFD, flags | FD_CLOEXEC) < 0
        || ::fcntl(fd, F_SETFL, status | O_NONBLOCK) < 0) {
        error = "Could not adopt activation socket";
        return false;
    }
    activation = fd;
    notifier = std::make_unique<QSocketNotifier>(fd, QSocketNotifier::Read);
    connect(notifier.get(), &QSocketNotifier::activated, this, [this] { drain(); });
    return true;
}

void Listener::drain()
{
    // Bound each batch so a connection flood cannot starve the event loop.
    for (int budget = 0; budget < 32; ++budget) {
        const int fd = ::accept4(activation, nullptr, nullptr, SOCK_CLOEXEC | SOCK_NONBLOCK);
        if (fd < 0) {
            if (errno == EINTR) {
                continue;
            }
            break;
        }
        accepted(fd);
    }
}
