#include "zt_bridge.hpp"
#include "debug.hpp"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <stdio.h>
#include <string.h>

namespace ztbridge {

int init() {
    LogFormat("ZT-LDN: init isolation stub (no zts_* calls)");
    return 0;
}

int socket(int family, int type, int protocol) {
    (void)family; (void)type; (void)protocol;
    return -1;
}

int bind(int fd, const sockaddr_in *addr) {
    (void)fd; (void)addr;
    return -1;
}

int listen(int fd, int backlog) {
    (void)fd; (void)backlog;
    return -1;
}

int accept(int fd) {
    (void)fd;
    return -1;
}

int connect(int fd, const sockaddr_in *addr) {
    (void)fd; (void)addr;
    return -1;
}

int close(int fd) {
    (void)fd;
    return 0;
}

ssize_t send(int fd, const void *buf, size_t len) {
    (void)fd; (void)buf; (void)len;
    return -1;
}

ssize_t sendto(int fd, const void *buf, size_t len, const sockaddr_in *addr) {
    (void)fd; (void)buf; (void)len; (void)addr;
    return -1;
}

ssize_t recv(int fd, void *buf, size_t len) {
    (void)fd; (void)buf; (void)len;
    return -1;
}

int poll(PollFd *fds, size_t nfds, int timeout_ms) {
    (void)fds; (void)nfds; (void)timeout_ms;
    return 0;
}

int local_ip_host_order(uint32_t *out) {
    if (out) *out = 0;
    return MAKERESULT(0xFD, 0x40);
}

uint32_t peer_ip_host_order() {
    return 0;
}

}
