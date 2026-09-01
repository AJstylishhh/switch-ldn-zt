#include <sys/socket.h>

// libzt's Switch build expects a POSIX pipe. Keep this shim in Sys B only;
// Sys A never links libzt.
extern "C" int pipe(int fd[2]) {
    return socketpair(AF_UNIX, SOCK_STREAM, 0, fd);
}
