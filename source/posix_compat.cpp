#include <switch.h>

#include <sys/socket.h>
#include <unistd.h>
#include <errno.h>

#ifdef errno
#undef errno
#endif
extern "C" int errno = 0;

extern "C" int pipe(int fds[2])
{
    if (!fds) {
        errno = 22;
        return -1;
    }

    fds[0] = -1;
    fds[1] = -1;

    if (socketpair(AF_UNIX, SOCK_STREAM, 0, fds) < 0) {
        return -1;
    }

    return 0;
}
