#pragma once

#include <sys/socket.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stddef.h>

namespace ztbridge {

struct PollFd {
    int fd;
    short events;
    short revents;
};

enum {
    ZT_POLLIN = 0x001,
    ZT_POLLPRI = 0x040,
    ZT_POLLOUT = 0x004,
    ZT_POLLERR = 0x008,
    ZT_POLLNVAL = 0x020,
    ZT_POLLHUP = 0x010
};

int init();
int socket(int family, int type, int protocol);
int bind(int fd, const sockaddr_in *addr);
int listen(int fd, int backlog);
int accept(int fd);
int connect(int fd, const sockaddr_in *addr);
int close(int fd);
ssize_t send(int fd, const void *buf, size_t len);
ssize_t sendto(int fd, const void *buf, size_t len, const sockaddr_in *addr);
ssize_t recv(int fd, void *buf, size_t len);
int poll(PollFd *fds, size_t nfds, int timeout_ms);
int local_ip_host_order(uint32_t *out);
uint32_t peer_ip_host_order();

}

#define ZT_POLLIN ztbridge::ZT_POLLIN
#define ZT_POLLPRI ztbridge::ZT_POLLPRI
#define ZT_POLLERR ztbridge::ZT_POLLERR
#define ZT_POLLNVAL ztbridge::ZT_POLLNVAL
#define ZT_POLLHUP ztbridge::ZT_POLLHUP
