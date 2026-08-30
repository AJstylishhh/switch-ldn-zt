#include "zt_bridge.hpp"
#include "debug.hpp"
#include <ZeroTierSockets.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <stdio.h>
#include <string.h>

extern "C" int pipe(int fd[2]) {
    return socketpair(AF_UNIX, SOCK_STREAM, 0, fd);
}

namespace ztbridge {

static constexpr const char *ConfigDir = "sdmc:/config/switch-ldn-zt";
static constexpr const char *NetworkFile = "sdmc:/config/switch-ldn-zt/network_id.txt";
static constexpr const char *PeerFile = "sdmc:/config/switch-ldn-zt/peer_ip.txt";
static constexpr unsigned short LdnPort = 11452;
static uint64_t gNetworkId = 0;
static char gPeerIp[ZTS_INET_ADDRSTRLEN] = {0};
static char gLocalIp[ZTS_INET_ADDRSTRLEN] = {0};
static bool gStarted = false;

static bool read_line(const char *path, char *out, size_t len) {
    FILE *f = fopen(path, "r");
    if (!f) return false;
    bool ok = fgets(out, (int)len, f) != nullptr;
    fclose(f);
    if (!ok) return false;
    for (size_t i = 0; i < len; ++i) {
        if (out[i] == '\0') break;
        if (out[i] == '\n' || out[i] == '\r' || out[i] == ' ' || out[i] == '\t') out[i] = '\0';
    }
    return out[0] != '\0';
}

int init() {
    if (gStarted) return 0;
    char nwid[32] = {0};
    if (!read_line(NetworkFile, nwid, sizeof(nwid))) {
        LogFormat("ZT-LDN: missing %s", NetworkFile);
        return -1;
    }
    unsigned long long parsed = 0;
    if (sscanf(nwid, "%llx", &parsed) != 1 || parsed == 0) {
        LogFormat("ZT-LDN: invalid network id");
        return -1;
    }
    gNetworkId = (uint64_t)parsed;
    if (!read_line(PeerFile, gPeerIp, sizeof(gPeerIp))) {
        LogFormat("ZT-LDN: missing %s", PeerFile);
        return -1;
    }

    int rc = zts_init_from_storage(ConfigDir);
    if (rc != ZTS_ERR_OK) {
        LogFormat("ZT-LDN: init_from_storage rc=%d", rc);
        return rc;
    }
    rc = zts_node_start();
    if (rc != ZTS_ERR_OK) {
        LogFormat("ZT-LDN: node_start rc=%d", rc);
        return rc;
    }
    for (int i = 0; i < 300 && !zts_node_is_online(); ++i) zts_util_delay(100);
    if (!zts_node_is_online()) {
        LogFormat("ZT-LDN: node stayed offline");
        return -1;
    }
    LogFormat("ZT-LDN: node=%010llx ONLINE", (unsigned long long)zts_node_get_id());

    rc = zts_net_join(gNetworkId);
    if (rc != ZTS_ERR_OK) {
        LogFormat("ZT-LDN: net_join rc=%d", rc);
        return rc;
    }
    for (int i = 0; i < 300 && !zts_net_transport_is_ready(gNetworkId); ++i) zts_util_delay(100);
    if (!zts_net_transport_is_ready(gNetworkId)) {
        LogFormat("ZT-LDN: network not ready");
        return -1;
    }
    if (zts_addr_get_str(gNetworkId, ZTS_AF_INET, gLocalIp, sizeof(gLocalIp)) != ZTS_ERR_OK) {
        LogFormat("ZT-LDN: failed to get assigned IPv4");
        return -1;
    }
    gStarted = true;
    LogFormat("ZT-LDN: network=%016llx local=%s peer=%s", (unsigned long long)gNetworkId, gLocalIp, gPeerIp);
    return 0;
}

int socket(int family, int type, int protocol) { return zts_bsd_socket(family, type, protocol); }

int bind(int fd, const sockaddr_in *addr) {
    unsigned short port = ntohs(addr->sin_port);
    zts_sockaddr zaddr{};
    zts_socklen_t zlen = sizeof(zaddr);
    if (zts_util_ipstr_to_saddr("0.0.0.0", port, &zaddr, &zlen) != ZTS_ERR_OK) return -1;
    return zts_bsd_bind(fd, &zaddr, zlen);
}

int listen(int fd, int backlog) { return zts_bsd_listen(fd, backlog); }

int accept(int fd) {
    zts_sockaddr addr{};
    zts_socklen_t len = sizeof(addr);
    return zts_bsd_accept(fd, &addr, &len);
}

int connect(int fd, const sockaddr_in *addr) {
    return zts_connect(fd, gPeerIp, ntohs(addr->sin_port), 5000);
}

int close(int fd) { return zts_bsd_close(fd); }
ssize_t send(int fd, const void *buf, size_t len) { return zts_bsd_send(fd, buf, len, 0); }

ssize_t sendto(int fd, const void *buf, size_t len, const sockaddr_in *addr) {
    (void)addr;
    zts_sockaddr zaddr{};
    zts_socklen_t zlen = sizeof(zaddr);
    if (zts_util_ipstr_to_saddr(gPeerIp, LdnPort, &zaddr, &zlen) != ZTS_ERR_OK) return -1;
    return zts_bsd_sendto(fd, buf, len, 0, &zaddr, zlen);
}

ssize_t recv(int fd, void *buf, size_t len) { return zts_bsd_recv(fd, buf, len, 0); }

int poll(PollFd *fds, size_t nfds, int timeout_ms) {
    zts_pollfd local[nfds];
    for (size_t i = 0; i < nfds; ++i) {
        local[i].fd = fds[i].fd;
        local[i].events = fds[i].events;
        local[i].revents = 0;
    }
    int rc = zts_bsd_poll(local, (zts_nfds_t)nfds, timeout_ms);
    for (size_t i = 0; i < nfds; ++i) fds[i].revents = local[i].revents;
    return rc;
}

int local_ip_host_order(uint32_t *out) {
    if (!gStarted || gLocalIp[0] == '\0') return MAKERESULT(0xFD, 0x40);
    struct in_addr a{};
    if (inet_pton(AF_INET, gLocalIp, &a) != 1) return MAKERESULT(0xFD, 0x41);
    *out = ntohl(a.s_addr);
    return 0;
}

uint32_t peer_ip_host_order() {
    struct in_addr a{};
    if (inet_pton(AF_INET, gPeerIp, &a) != 1) return 0;
    return ntohl(a.s_addr);
}

}
