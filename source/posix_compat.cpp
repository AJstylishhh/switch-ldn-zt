#include <switch.h>

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>

// ZeroTier's lwIP/Unix compatibility layer expects a POSIX errno object.
// libnx/newlib normally exposes errno through __errno(), while the lwIP Unix
// port used by libzt declares a plain external errno. Keep a dedicated errno
// object for that compatibility boundary.
#ifdef errno
#undef errno
#endif
extern "C" int errno = 0;

// ZeroTier's Phy layer uses pipe() only as a pair of pollable wake-up
// descriptors. AF_UNIX/socketpair() is not a safe assumption on Switch BSD,
// so emulate POSIX pipe() with a loopback TCP connection instead. This is the
// same basic technique ZeroTier already uses for its Windows pipe emulation.
extern "C" int pipe(int fds[2])
{
    if (!fds) {
        errno = 22; // EINVAL
        return -1;
    }

    fds[0] = -1;
    fds[1] = -1;

    const int listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (listener < 0) {
        return -1;
    }

    struct sockaddr_in addr;
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = 0;

    if (bind(listener, reinterpret_cast<const struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(listener);
        return -1;
    }

    if (listen(listener, 1) < 0) {
        close(listener);
        return -1;
    }

    socklen_t addr_len = sizeof(addr);
    if (getsockname(listener, reinterpret_cast<struct sockaddr*>(&addr), &addr_len) < 0) {
        close(listener);
        return -1;
    }

    fds[0] = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (fds[0] < 0) {
        close(listener);
        return -1;
    }

    if (connect(fds[0], reinterpret_cast<const struct sockaddr*>(&addr), addr_len) < 0) {
        close(fds[0]);
        fds[0] = -1;
        close(listener);
        return -1;
    }

    fds[1] = accept(listener, nullptr, nullptr);
    close(listener);

    if (fds[1] < 0) {
        close(fds[0]);
        fds[0] = -1;
        return -1;
    }

    return 0;
}
