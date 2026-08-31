#include "zt_bridge.hpp"

namespace ztbridge {

// Stubs-first build: keep initialization non-fatal so the control service can boot.
int init() { return 0; }
int socket(int, int, int) { return -1; }
int bind(int, const sockaddr_in *) { return -1; }
int listen(int, int) { return -1; }
int accept(int) { return -1; }
int connect(int, const sockaddr_in *) { return -1; }
int close(int) { return 0; }
ssize_t send(int, const void *, size_t) { return -1; }
ssize_t sendto(int, const void *, size_t, const sockaddr_in *) { return -1; }
ssize_t recv(int, void *, size_t) { return -1; }
int poll(PollFd *, size_t, int) { return -1; }
int local_ip_host_order(uint32_t *out) {
    if (out) *out = 0;
    return 0;
}
uint32_t peer_ip_host_order() { return 0; }

}
