#include <switch.h>

#include <sys/socket.h>
#include <errno.h>

// ZeroTier's lwIP/Unix compatibility layer expects a POSIX errno object.
// libnx/newlib normally exposes errno through __errno(), while the lwIP Unix
// port used by libzt declares a plain external errno. Keep a dedicated errno
// object for that compatibility boundary.
#ifdef errno
#undef errno
#endif
extern "C" int errno = 0;

// ZeroTier's VirtualTap/NodeService use pipe() only as a pair of pollable
// wake-up descriptors. Switch/libnx does not provide POSIX pipe(), but its BSD
// socket layer provides socketpair(), which gives us the same full-duplex
// descriptor semantics needed by those internal wake-up paths.
extern "C" int pipe(int fds[2])
{
    if (!fds) {
        errno = EINVAL;
        return -1;
    }

    const int rc = socketpair(AF_UNIX, SOCK_STREAM, 0, fds);
    if (rc < 0) {
        return -1;
    }

    return 0;
}
