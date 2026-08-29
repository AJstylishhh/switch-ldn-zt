#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("ldn_mitm/ldn_mitm/source")
PROTO_CPP = ROOT / "lan_protocol.cpp"
DISC_CPP = ROOT / "lan_discovery.cpp"
MAIN_CPP = ROOT / "ldnmitm_main.cpp"
ZT_HPP = ROOT / "zt_transport.hpp"
ZT_CPP = ROOT / "zt_transport.cpp"
MAKEFILE = Path("ldn_mitm/ldn_mitm/Makefile")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))

# -----------------------------------------------------------------------------
# LAN socket backend: keep the upstream ldn:u protocol/state machine and move
# only its transport sockets onto the libzt socket namespace.
# -----------------------------------------------------------------------------
replace_once(PROTO_CPP, '#include "debug.hpp"\n#include <poll.h>', '#include "debug.hpp"\n#include <poll.h>\n#include <ZeroTierSockets.h>')
replace_once(PROTO_CPP, '#define POLL_UNKNOWN (~(POLLIN | POLLPRI | POLLOUT))', '''#define POLL_UNKNOWN (~(POLLIN | POLLPRI | POLLOUT))

static zts_sockaddr_in to_zt_addr(const sockaddr_in *addr) {
    zts_sockaddr_in out{};
    out.sin_len = sizeof(out);
    out.sin_family = ZTS_AF_INET;
    if (addr) {
        out.sin_port = addr->sin_port;
        out.sin_addr.s_addr = addr->sin_addr.s_addr;
    }
    return out;
}

static void from_zt_addr(const zts_sockaddr_in &in, sockaddr_in *addr) {
    if (!addr) return;
    std::memset(addr, 0, sizeof(*addr));
    addr->sin_family = AF_INET;
    addr->sin_port = in.sin_port;
    addr->sin_addr.s_addr = in.sin_addr.s_addr;
}''')

replace_once(PROTO_CPP,
'''    struct pollfd pfds[nfds];
    for (size_t i = 0; i < nfds; i++) {
        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;
        pfds[i].events = POLLIN;
        pfds[i].revents = 0;
    }
    int rc = poll(pfds, nfds, timeout);''',
'''    struct zts_pollfd pfds[nfds];
    for (size_t i = 0; i < nfds; i++) {
        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;
        pfds[i].events = ZTS_POLLIN;
        pfds[i].revents = 0;
    }
    int rc = zts_bsd_poll(pfds, static_cast<zts_nfds_t>(nfds), timeout);''')
replace_once(PROTO_CPP, 'const struct pollfd &pfd = pfds[i];', 'const struct zts_pollfd &pfd = pfds[i];')
replace_once(PROTO_CPP, 'pfd.revents & (POLLERR | POLLHUP)', 'pfd.revents & (ZTS_POLLERR | ZTS_POLLHUP | ZTS_POLLNVAL)')
replace_once(PROTO_CPP, 'pfd.revents & (POLLIN | POLLPRI)', 'pfd.revents & ZTS_POLLIN')
replace_once(PROTO_CPP, '::close(this->fd);', 'zts_bsd_close(this->fd);')
replace_once(PROTO_CPP, 'auto rc = ::recvfrom(this->fd, buf, len, 0, nullptr, 0);', 'auto rc = zts_bsd_recv(this->fd, buf, len, 0);')
replace_once(PROTO_CPP, 'return ::sendto(this->fd, buf, len, 0, nullptr, 0);', 'return static_cast<int>(zts_bsd_send(this->fd, buf, len, 0));')
replace_once(PROTO_CPP,
'''    socklen_t addr_len = sizeof(*addr);
    return ::recvfrom(this->fd, buf, len, 0, (struct sockaddr *)addr, &addr_len);''',
'''    zts_sockaddr_in zaddr{};
    zts_socklen_t zlen = sizeof(zaddr);
    const auto rc = zts_bsd_recvfrom(this->fd, buf, len, 0, reinterpret_cast<zts_sockaddr*>(&zaddr), &zlen);
    if (rc >= 0) from_zt_addr(zaddr, addr);
    return rc;''')
replace_once(PROTO_CPP,
'''    return ::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr));''',
'''    const auto zaddr = to_zt_addr(addr);
    return static_cast<int>(zts_bsd_sendto(this->fd, buf, len, 0, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)));''')

# -----------------------------------------------------------------------------
# Discovery socket lifecycle: use the same ZT descriptor namespace.
# -----------------------------------------------------------------------------
replace_once(DISC_CPP, '#include "lan_discovery.hpp"', '''#include "lan_discovery.hpp"
#include <ZeroTierSockets.h>
#include <cstring>

static zts_sockaddr_in to_zt_addr(const sockaddr_in *addr) {
    zts_sockaddr_in out{};
    out.sin_len = sizeof(out);
    out.sin_family = ZTS_AF_INET;
    if (addr) {
        out.sin_port = addr->sin_port;
        out.sin_addr.s_addr = addr->sin_addr.s_addr;
    }
    return out;
}''')
replace_once(DISC_CPP, 'close(new_fd);', 'zts_bsd_close(new_fd);')
replace_once(DISC_CPP, 'close(new_fd);', 'zts_bsd_close(new_fd);')
replace_once(DISC_CPP, 'setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &b, sizeof(b))', 'zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_BROADCAST, &b, sizeof(b))')
replace_once(DISC_CPP, 'setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes))', 'zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_REUSEADDR, &yes, sizeof(yes))')
replace_once(DISC_CPP, 'fd = ::socket(AF_INET, SOCK_STREAM, 0);', 'fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_STREAM, 0);')
replace_once(DISC_CPP, 'fd = ::socket(AF_INET, SOCK_DGRAM, 0);', 'fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_DGRAM, 0);')
replace_once(DISC_CPP,
'''            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htons(INADDR_ANY);
            addr.sin_port = htons(listenPort);
            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
                return MAKERESULT(ModuleID, 7);
            }
            if (listen(fd, 10) != 0) {''',
'''            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htonl(INADDR_ANY);
            addr.sin_port = htons(listenPort);
            const auto zaddr = to_zt_addr(&addr);
            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {
                return MAKERESULT(ModuleID, 7);
            }
            if (zts_bsd_listen(fd, 10) != 0) {''')
replace_once(DISC_CPP,
'''            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htons(INADDR_ANY);
            addr.sin_port = htons(listenPort);
            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {
                return MAKERESULT(ModuleID, 2);
            }''',
'''            addr.sin_family = AF_INET;
            addr.sin_addr.s_addr = htonl(INADDR_ANY);
            addr.sin_port = htons(listenPort);
            const auto zaddr = to_zt_addr(&addr);
            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {
                return MAKERESULT(ModuleID, 2);
            }''')
replace_once(DISC_CPP,
'''            struct sockaddr_in addr;
            socklen_t addrlen = sizeof(addr);
            int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);''',
'''            zts_sockaddr_in zaddr{};
            zts_socklen_t zaddrlen = sizeof(zaddr);
            int new_fd = zts_bsd_accept(this->getFd(), reinterpret_cast<zts_sockaddr*>(&zaddr), &zaddrlen);''')

# -----------------------------------------------------------------------------
# Start libzt inside ldn_mitm. The network id is intentionally supplied by a
# text file so no network identifier is hard-coded into the binary.
# -----------------------------------------------------------------------------
ZT_HPP.write_text('''#pragma once
int zt_ldn_initialize();
''')
ZT_CPP.write_text('''#include "zt_transport.hpp"
#include <stratosphere.hpp>
#include <ZeroTierSockets.h>
#include <cstdio>
#include <cstdlib>

namespace {
uint64_t g_net_id = 0;

bool read_network_id(uint64_t &out) {
    FILE *f = std::fopen("sdmc:/config/zerotier-switch/network_id.txt", "rb");
    if (!f) return false;
    char buf[64]{};
    const size_t n = std::fread(buf, 1, sizeof(buf) - 1, f);
    std::fclose(f);
    if (!n) return false;
    char *end = nullptr;
    const unsigned long long v = std::strtoull(buf, &end, 16);
    if (end == buf || v == 0) return false;
    out = static_cast<uint64_t>(v);
    return true;
}
}

int zt_ldn_initialize() {
    if (!read_network_id(g_net_id)) {
        std::printf("[LDN-ZT] network_id.txt missing/invalid\\n");
        return ZTS_ERR_ARG;
    }

    int rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    if (rc != ZTS_ERR_OK) return rc;
    zts_init_set_port(9993);
    zts_init_allow_secondary_port(1);
    zts_init_allow_port_mapping(1);

    rc = zts_node_start();
    if (rc != ZTS_ERR_OK) return rc;
    rc = zts_net_join(g_net_id);
    std::printf("[LDN-ZT] join %016llx rc=%d\\n", (unsigned long long)g_net_id, rc);
    return rc;
}
''')

replace_once(MAIN_CPP, '#include "ldnmitm_service.hpp"', '#include "ldnmitm_service.hpp"\n#include "zt_transport.hpp"')
replace_once(MAIN_CPP,
'''            R_ABORT_UNLESS(socketInitialize(&LibnxSocketInitConfig));''',
'''            R_ABORT_UNLESS(socketInitialize(&LibnxSocketInitConfig));
            const int zt_rc = zt_ldn_initialize();
            if (zt_rc != ZTS_ERR_OK) {
                LogFormat("[LDN-ZT] initialization failed: %d", zt_rc);
            }''')

# Link the staged static library into the sysmodule. The Makefile is patched in
# the checked-out submodule during CI, so the upstream source remains untouched.
make_text = MAKEFILE.read_text()
if 'LIBZT_LDN_TRANSPORT' not in make_text:
    marker = 'CXXFLAGS\t+= $(VERSION_DEFINES)\n'
    if marker not in make_text:
        raise SystemExit('ldn_mitm Makefile marker not found')
    make_text = make_text.replace(marker, marker + '''
# ZeroTier transport
INCLUDES += $(TOPDIR)/../../third_party/libzt/include
LIBDIRS += $(TOPDIR)/../../third_party/libzt
LIBS += zt
CXXFLAGS += -DLIBZT_LDN_TRANSPORT
''', 1)
    MAKEFILE.write_text(make_text)

print("LDN ZeroTier transport patch applied")
