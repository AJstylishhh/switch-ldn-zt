#!/usr/bin/env python3
"""Patch the upstream ldn_mitm tree to use libzt sockets for its LAN transport.

This is intentionally a build-time patch: ldn_mitm remains a pinned upstream
submodule, while all ZeroTier-specific code lives in this repository.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LDN = ROOT / "ldn_mitm"
SRC = LDN / "ldn_mitm" / "source"
BRIDGE = ROOT / "ldn-zt"

if not (SRC / "lan_protocol.cpp").exists():
    raise SystemExit("ldn_mitm submodule is missing; checkout with submodules: recursive")

# Copy our small bridge into the upstream sysmodule source tree.
(SRC / "zt_bridge.hpp").write_text((BRIDGE / "zt_bridge.hpp").read_text())
(SRC / "zt_bridge.cpp").write_text((BRIDGE / "zt_bridge.cpp").read_text())

# ---------------------------------------------------------------------------
# lan_protocol.cpp: make Pollable/LanSocket operate on libzt's lwIP sockets.
# ---------------------------------------------------------------------------
p = SRC / "lan_protocol.cpp"
s = p.read_text()
if '#include "zt_bridge.hpp"' not in s:
    s = s.replace('#include "lan_protocol.hpp"', '#include "lan_protocol.hpp"\n#include "zt_bridge.hpp"', 1)

poll_pat = re.compile(r'int Pollable::Poll\(Pollable \*fds\[\], size_t nfds, int timeout\) \{.*?\n\}\n\nLanSocket::~LanSocket', re.S)
poll_repl = r'''int Pollable::Poll(Pollable *fds[], size_t nfds, int timeout) {
    zts_pollfd pfds[nfds];
    for (size_t i = 0; i < nfds; i++) {
        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;
        pfds[i].events = ZTS_POLLIN;
        pfds[i].revents = 0;
    }

    int rc = zts_bsd_poll(pfds, static_cast<zts_nfds_t>(nfds), timeout);
    if (rc < 0) {
        LogFormat("Pollable::Poll failed %d errno=%d", rc, zts_errno);
        return -1;
    }
    if (rc == 0) return 0;

    for (size_t i = 0; i < nfds; i++) {
        const zts_pollfd &pfd = pfds[i];
        if (pfd.revents == 0) continue;

        if (pfd.revents & (ZTS_POLLERR | ZTS_POLLHUP | ZTS_POLLNVAL)) {
            LogFormat("Poll: close %zu(%d) revents=0x%x", i, pfd.fd, pfd.revents);
            fds[i]->onClose();
        } else if (pfd.revents & (ZTS_POLLIN | ZTS_POLLPRI)) {
            int read_rc = fds[i]->onRead();
            if (read_rc != 0) {
                LogFormat("Pollable::Poll close %d", read_rc);
                fds[i]->onClose();
            }
        }
    }
    return 0;
}

LanSocket::~LanSocket'''
s, n = poll_pat.subn(poll_repl, s, count=1)
if n != 1:
    raise SystemExit("failed to patch Pollable::Poll")

s = s.replace('::close(this->fd);', 'zts_bsd_close(this->fd);', 1)

tcp_recv = '''ssize_t TcpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {
\tAMS_UNUSED(addr);
    auto rc = ::recvfrom(this->fd, buf, len, 0, nullptr, 0);
    if (rc == 0) {
        return -0xFD23;
    }
    return rc;
}'''
tcp_recv_new = '''ssize_t TcpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {
    AMS_UNUSED(addr);
    auto rc = zts_bsd_recv(this->fd, buf, len, 0);
    if (rc == 0) return -0xFD23;
    return rc;
}'''
if tcp_recv not in s:
    raise SystemExit("TCP recv anchor not found")
s = s.replace(tcp_recv, tcp_recv_new, 1)

tcp_send = '''int TcpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {
\tAMS_UNUSED(addr);
    return ::sendto(this->fd, buf, len, 0, nullptr, 0);
}'''
tcp_send_new = '''int TcpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {
    AMS_UNUSED(addr);
    return static_cast<int>(zts_bsd_send(this->fd, buf, len, 0));
}'''
if tcp_send not in s:
    raise SystemExit("TCP send anchor not found")
s = s.replace(tcp_send, tcp_send_new, 1)

udp_recv = '''ssize_t UdpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {
    socklen_t addr_len = sizeof(*addr);
    return ::recvfrom(this->fd, buf, len, 0, (struct sockaddr *)addr, &addr_len);
}'''
udp_recv_new = '''ssize_t UdpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {
    zts_sockaddr_in zaddr{};
    zts_socklen_t zlen = sizeof(zaddr);
    const ssize_t rc = zts_bsd_recvfrom(this->fd, buf, len, 0,
                                        reinterpret_cast<zts_sockaddr*>(&zaddr), &zlen);
    if (rc >= 0 && addr != nullptr) {
        std::memset(addr, 0, sizeof(*addr));
        addr->sin_family = AF_INET;
        addr->sin_port = zaddr.sin_port;
        addr->sin_addr.s_addr = zaddr.sin_addr.s_addr;
    }
    return rc;
}'''
if udp_recv not in s:
    raise SystemExit("UDP recv anchor not found")
s = s.replace(udp_recv, udp_recv_new, 1)

udp_send = '''int UdpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {
    return ::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr));
}'''
udp_send_new = '''int UdpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {
    if (addr == nullptr) return -1;
    zts_sockaddr_in zaddr{};
    zaddr.sin_len = sizeof(zaddr);
    zaddr.sin_family = ZTS_AF_INET;
    zaddr.sin_port = addr->sin_port;
    zaddr.sin_addr.s_addr = addr->sin_addr.s_addr;
    return static_cast<int>(zts_bsd_sendto(this->fd, buf, len, 0,
                                            reinterpret_cast<zts_sockaddr*>(&zaddr), sizeof(zaddr)));
}'''
if udp_send not in s:
    raise SystemExit("UDP send anchor not found")
s = s.replace(udp_send, udp_send_new, 1)

p.write_text(s)

# ---------------------------------------------------------------------------
# lan_discovery.cpp: sockets, accept/connect, broadcast, and local IP become ZT.
# ---------------------------------------------------------------------------
p = SRC / "lan_discovery.cpp"
s = p.read_text()
if '#include "zt_bridge.hpp"' not in s:
    s = s.replace('#include "lan_discovery.hpp"', '#include "lan_discovery.hpp"\n#include "zt_bridge.hpp"', 1)

# Host BSSID and node IP must be derived from the ZeroTier address, not Wi-Fi.
old = '''    u32 ip;
        Result rc = nifmGetCurrentIpAddress(&ip);
        if (R_SUCCEEDED(rc)) {
            ip = ntohl(ip);
            memcpy(mac->raw + 2, &ip, sizeof(ip));
        }

        return rc;'''
new = '''    const u32 ip = zt_bridge::ipv4_address();
        if (ip == 0) return MAKERESULT(ModuleID, 11);
        memcpy(mac->raw + 2, &ip, sizeof(ip));
        return 0;'''
if old not in s:
    raise SystemExit("getFakeMac anchor not found")
s = s.replace(old, new, 1)

old = '''        u32 ipAddress;
        Result rc = nifmGetCurrentIpAddress(&ipAddress);
        if (R_FAILED(rc))
        {
            return rc;
        }
        ipAddress = ntohl(ipAddress);'''
new = '''        const u32 ipAddress = zt_bridge::ipv4_address();
        if (ipAddress == 0) {
            return MAKERESULT(ModuleID, 12);
        }
        Result rc = 0;'''
if old not in s:
    raise SystemExit("getNodeInfo IP anchor not found")
s = s.replace(old, new, 1)

# setSocketOpts only needs options supported by the ZT socket layer.
setopt_pat = re.compile(r'Result LANDiscovery::setSocketOpts\(int fd\) \{.*?\n    \}\n\n    Result LANDiscovery::initTcp', re.S)
setopt_repl = '''Result LANDiscovery::setSocketOpts(int fd) {
        int yes = 1;
        const int rc = zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_REUSEADDR,
                                          &yes, sizeof(yes));
        if (rc != ZTS_ERR_OK) {
            LogFormat("ZTS SO_REUSEADDR failed rc=%d errno=%d", rc, zts_errno);
        }
        return 0;
    }

    Result LANDiscovery::initTcp'''
s, n = setopt_pat.subn(setopt_repl, s, count=1)
if n != 1:
    raise SystemExit("setSocketOpts block not found")

# Replace initTcp/initUdp blocks with ZT socket equivalents.
tcp_pat = re.compile(r'Result LANDiscovery::initTcp\(bool listening\) \{.*?\n    \}\n\n    Result LANDiscovery::initUdp', re.S)
tcp_repl = '''Result LANDiscovery::initTcp(bool listening) {
        Result rc;
        std::scoped_lock lock(this->pollMutex);

        if (this->tcp) this->tcp->close();
        const int fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_STREAM, 0);
        if (fd < 0) return MAKERESULT(ModuleID, 6);
        auto tcpSocket = std::make_unique<LDTcpSocket>(fd, this);

        if (listening) {
            zts_sockaddr_in addr{};
            addr.sin_len = sizeof(addr);
            addr.sin_family = ZTS_AF_INET;
            addr.sin_addr.s_addr = htonl(ZTS_INADDR_ANY);
            addr.sin_port = htons(listenPort);
            if (zts_bsd_bind(fd, reinterpret_cast<zts_sockaddr*>(&addr), sizeof(addr)) != ZTS_ERR_OK) {
                zts_bsd_close(fd);
                return MAKERESULT(ModuleID, 7);
            }
            if (zts_bsd_listen(fd, 10) != ZTS_ERR_OK) {
                zts_bsd_close(fd);
                return MAKERESULT(ModuleID, 8);
            }
        }

        rc = setSocketOpts(fd);
        if (R_FAILED(rc)) {
            zts_bsd_close(fd);
            return rc;
        }
        this->tcp = std::move(tcpSocket);
        return 0;
    }

    Result LANDiscovery::initUdp'''
s, n = tcp_pat.subn(tcp_repl, s, count=1)
if n != 1:
    raise SystemExit("initTcp block not found")

udp_pat = re.compile(r'Result LANDiscovery::initUdp\(bool listening\) \{.*?\n    \}\n\n    void LANDiscovery::initNodeStateChange', re.S)
udp_repl = '''Result LANDiscovery::initUdp(bool listening) {
        Result rc;
        std::scoped_lock lock(this->pollMutex);

        if (this->udp) this->udp->close();
        const int fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_DGRAM, 0);
        if (fd < 0) return MAKERESULT(ModuleID, 1);
        auto udpSocket = std::make_unique<LDUdpSocket>(fd, this);

        int yes = 1;
        if (zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_BROADCAST, &yes, sizeof(yes)) != ZTS_ERR_OK) {
            LogFormat("ZTS SO_BROADCAST failed errno=%d", zts_errno);
        }

        if (listening) {
            zts_sockaddr_in addr{};
            addr.sin_len = sizeof(addr);
            addr.sin_family = ZTS_AF_INET;
            addr.sin_addr.s_addr = htonl(ZTS_INADDR_ANY);
            addr.sin_port = htons(listenPort);
            if (zts_bsd_bind(fd, reinterpret_cast<zts_sockaddr*>(&addr), sizeof(addr)) != ZTS_ERR_OK) {
                zts_bsd_close(fd);
                return MAKERESULT(ModuleID, 2);
            }
        }
        rc = setSocketOpts(fd);
        if (R_FAILED(rc)) {
            zts_bsd_close(fd);
            return rc;
        }
        this->udp = std::move(udpSocket);
        return 0;
    }

    void LANDiscovery::initNodeStateChange'''
s, n = udp_pat.subn(udp_repl, s, count=1)
if n != 1:
    raise SystemExit("initUdp block not found")

# TCP accept now goes through the ZT socket API.
s = s.replace('''            struct sockaddr_in addr;
            socklen_t addrlen = sizeof(addr);
            int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);''', '''            zts_sockaddr addr{};
            zts_socklen_t addrlen = sizeof(addr);
            int new_fd = zts_bsd_accept(this->getFd(), &addr, &addrlen);''', 1)

# Station connect uses the ZT socket API.
s = s.replace('''        int ret = ::connect(this->tcp->getFd(), (struct sockaddr *)&addr, sizeof(addr));''', '''        zts_sockaddr_in zaddr{};
        zaddr.sin_len = sizeof(zaddr);
        zaddr.sin_family = ZTS_AF_INET;
        zaddr.sin_addr.s_addr = addr.sin_addr.s_addr;
        zaddr.sin_port = addr.sin_port;
        int ret = zts_bsd_connect(this->tcp->getFd(), reinterpret_cast<zts_sockaddr*>(&zaddr), sizeof(zaddr));''', 1)

# Broadcast is a ZeroTier-managed broadcast group. The network must have broadcast enabled.
s = re.sub(r'u32 LDUdpSocket::getBroadcast\(\) \{.*?\n    \}', '''u32 LDUdpSocket::getBroadcast() {
        if (zt_bridge::network_id() == 0 || !zts_net_get_broadcast(zt_bridge::network_id())) {
            LogFormat("ZeroTier broadcast is disabled");
        }
        return 0xFFFFFFFFu;
    }''', s, count=1, flags=re.S)

p.write_text(s)

# ---------------------------------------------------------------------------
# ldn_icommunication.cpp: expose the same ZT address to the game.
# ---------------------------------------------------------------------------
p = SRC / "ldn_icommunication.cpp"
s = p.read_text()
if '#include "zt_bridge.hpp"' not in s:
    s = s.replace('#include "ldn_icommunication.hpp"', '#include "ldn_icommunication.hpp"\n#include "zt_bridge.hpp"', 1)
old = '''        u32 gateway, primary_dns, secondary_dns;
        Result rc = nifmGetCurrentIpConfigInfo(address.GetPointer(), netmask.GetPointer(), &gateway, &primary_dns, &secondary_dns);

        address.SetValue(ntohl(address.GetValue()));
        netmask.SetValue(ntohl(netmask.GetValue()));

        LogFormat("get_ipv4_address %x %x", address.GetValue(), netmask.GetValue());

        return rc;'''
new = '''        const u32 ip = zt_bridge::ipv4_address();
        const u32 mask = zt_bridge::ipv4_netmask();
        if (ip == 0 || mask == 0) {
            return MAKERESULT(0x10, 33);
        }
        address.SetValue(ip);
        netmask.SetValue(mask);
        LogFormat("get_ipv4_address(ZT) %x %x", ip, mask);
        return 0;'''
if old not in s:
    raise SystemExit("GetIpv4Address anchor not found")
s = s.replace(old, new, 1)

# Start ZT before the LDN transport is initialized.
old = '''        R_TRY(lanDiscovery.initialize([&](){'''
new = '''        R_TRY(zt_bridge::start());

        R_TRY(lanDiscovery.initialize([&](){'''
if old not in s:
    raise SystemExit("Initialize anchor not found")
s = s.replace(old, new, 1)

# Free ZT after ldn transport has shut down.
old = '''        Result rc = lanDiscovery.finalize();
        if (this->state_event) {'''
new = '''        Result rc = lanDiscovery.finalize();
        const Result zt_rc = zt_bridge::stop();
        if (R_SUCCEEDED(rc) && R_FAILED(zt_rc)) rc = zt_rc;
        if (this->state_event) {'''
if old not in s:
    raise SystemExit("Finalize anchor not found")
s = s.replace(old, new, 1)

p.write_text(s)

print("ldn_mitm ZeroTier transport patch applied")
