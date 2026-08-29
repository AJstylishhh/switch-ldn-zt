#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("ldn_mitm/ldn_mitm/source")
PROTO_HPP = ROOT / "lan_protocol.hpp"
PROTO_CPP = ROOT / "lan_protocol.cpp"
DISC_HPP = ROOT / "lan_discovery.hpp"
DISC_CPP = ROOT / "lan_discovery.cpp"
MAIN_CPP = ROOT / "ldnmitm_main.cpp"
MAKEFILE = Path("ldn_mitm/ldn_mitm/Makefile")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1))

# The upstream LAN abstraction is deliberately retained; only its socket backend is
# redirected to libzt. This keeps the ldn:u protocol/state machine unchanged.
replace_once(PROTO_HPP, '#include "lan_types.hpp"' if False else '#include "ldn_types.hpp"', '#include "ldn_types.hpp"\n#include <ZeroTierSockets.h>')

replace_once(PROTO_CPP,
'''#include "lan_protocol.hpp"\n#include "debug.hpp"''',
'''#include "lan_protocol.hpp"\n#include "debug.hpp"\n\nstatic struct zts_sockaddr_in to_zt_addr(const struct sockaddr_in *addr) {\n    struct zts_sockaddr_in out{};\n    out.sin_family = ZTS_AF_INET;\n    out.sin_port = addr ? addr->sin_port : 0;\n    out.sin_addr.s_addr = addr ? addr->sin_addr.s_addr : 0;\n    return out;\n}\n\nstatic void from_zt_addr(const struct zts_sockaddr_in &in, struct sockaddr_in *addr) {\n    if (!addr) return;\n    std::memset(addr, 0, sizeof(*addr));\n    addr->sin_family = AF_INET;\n    addr->sin_port = in.sin_port;\n    addr->sin_addr.s_addr = in.sin_addr.s_addr;\n}''')

old_poll = '''    struct pollfd pfds[nfds];\n    for (size_t i = 0; i < nfds; i++) {\n        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;\n        pfds[i].events = POLLIN;\n        pfds[i].revents = 0;\n    }\n    int rc = poll(pfds, nfds, timeout);\n    if (rc < 0) {\n        LogFormat("Pollable::Poll failed %d", rc);\n        return -1;\n    }\n    if (rc == 0) {\n        return 0;\n    }\n    for (size_t i = 0; i < nfds; i++) {\n        const struct pollfd &pfd = pfds[i];\n\n        if (pfd.revents != 0) {\n            if (pfd.revents & POLL_UNKNOWN) {\n                LogFormat("Poll: %zu(%d) revents=0x%08X", i, pfd.fd, pfd.revents);\n            }\n            if (pfd.revents & (POLLERR | POLLHUP)) {\n                LogFormat("Poll: (POLLERR | POLLHUP) %zu(%d) revents=0x%x", i, pfd.fd, pfd.revents);\n                fds[i]->onClose();\n            } else if (pfd.revents & (POLLIN | POLLPRI)) {\n                int rc = fds[i]->onRead();\n                if (rc != 0) {\n                    LogFormat("Pollable::Poll close %d", rc);\n                    fds[i]->onClose();\n                }\n            }\n        }\n    }'''
new_poll = '''    struct zts_pollfd pfds[nfds];\n    for (size_t i = 0; i < nfds; i++) {\n        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;\n        pfds[i].events = ZTS_POLLIN;\n        pfds[i].revents = 0;\n    }\n    int rc = zts_bsd_poll(pfds, static_cast<zts_nfds_t>(nfds), timeout);\n    if (rc < 0) {\n        LogFormat("Pollable::Poll failed %d errno=%d", rc, zts_errno);\n        return -1;\n    }\n    if (rc == 0) return 0;\n    for (size_t i = 0; i < nfds; i++) {\n        const struct zts_pollfd &pfd = pfds[i];\n        if (pfd.revents != 0) {\n            if (pfd.revents & (ZTS_POLLERR | ZTS_POLLHUP | ZTS_POLLNVAL)) {\n                LogFormat("Poll: close %zu(%d) revents=0x%x", i, pfd.fd, pfd.revents);\n                fds[i]->onClose();\n            } else if (pfd.revents & ZTS_POLLIN) {\n                int cb = fds[i]->onRead();\n                if (cb != 0) {\n                    LogFormat("Pollable::Poll close %d", cb);\n                    fds[i]->onClose();\n                }\n            }\n        }\n    }'''
replace_once(PROTO_CPP, old_poll, new_poll)

replace_once(PROTO_CPP, '        ::close(this->fd);', '        zts_bsd_close(this->fd);')
replace_once(PROTO_CPP,
'''ssize_t TcpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {\n\tAMS_UNUSED(addr);\n    auto rc = ::recvfrom(this->fd, buf, len, 0, nullptr, 0);''',
'''ssize_t TcpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {\n    AMS_UNUSED(addr);\n    auto rc = zts_bsd_recv(this->fd, buf, len, 0);''')
replace_once(PROTO_CPP,
'''int TcpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {\n\tAMS_UNUSED(addr);\n    return ::sendto(this->fd, buf, len, 0, nullptr, 0);\n}''',
'''int TcpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {\n    AMS_UNUSED(addr);\n    return static_cast<int>(zts_bsd_send(this->fd, buf, len, 0));\n}''')
replace_once(PROTO_CPP,
'''ssize_t UdpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {\n    socklen_t addr_len = sizeof(*addr);\n    return ::recvfrom(this->fd, buf, len, 0, (struct sockaddr *)addr, &addr_len);\n}\nint UdpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {\n    return ::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr));\n}''',
'''ssize_t UdpLanSocketBase::recvfrom(void *buf, size_t len, struct sockaddr_in *addr) {\n    zts_sockaddr_in zaddr{};\n    zts_socklen_t zlen = sizeof(zaddr);\n    const auto rc = zts_bsd_recvfrom(this->fd, buf, len, 0, reinterpret_cast<zts_sockaddr*>(&zaddr), &zlen);\n    if (rc >= 0) from_zt_addr(zaddr, addr);\n    return rc;\n}\nint UdpLanSocketBase::sendto(const void *buf, size_t len, struct sockaddr_in *addr) {\n    const auto zaddr = to_zt_addr(addr);\n    return static_cast<int>(zts_bsd_sendto(this->fd, buf, len, 0, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)));\n}''')

# ldn_discovery's own socket lifecycle must create ZT descriptors, not libnx/bsd descriptors.
replace_once(DISC_CPP, '#include "lan_discovery.hpp"', '#include "lan_discovery.hpp"\n#include <ZeroTierSockets.h>')
replace_once(DISC_CPP, '    u32 ret = address | ~netmask;\n        return ret;', '    AMS_UNUSED(address);\n        AMS_UNUSED(netmask);\n        return 0xFFFFFFFF;')
replace_once(DISC_CPP, '            close(new_fd);', '            zts_bsd_close(new_fd);')
replace_once(DISC_CPP, '            close(new_fd);', '            zts_bsd_close(new_fd);')

replace_once(DISC_CPP,
'''        int b = 1;\n            rc = setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &b, sizeof(b));''',
'''        int b = 1;\n            rc = zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_BROADCAST, &b, sizeof(b));''')
replace_once(DISC_CPP,
'''            int yes = 1;\n            rc = setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));''',
'''            int yes = 1;\n            rc = zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_REUSEADDR, &yes, sizeof(yes));''')

replace_once(DISC_CPP, '        fd = ::socket(AF_INET, SOCK_STREAM, 0);', '        fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_STREAM, 0);')
replace_once(DISC_CPP, '        fd = ::socket(AF_INET, SOCK_DGRAM, 0);', '        fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_DGRAM, 0);')

# Convert the two bind/listen sites to the ZT socket ABI.
replace_once(DISC_CPP,
'''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htons(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {\n                return MAKERESULT(ModuleID, 7);\n            }\n            if (listen(fd, 10) != 0) {\n                return MAKERESULT(ModuleID, 8);\n            }''',
'''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htonl(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            const auto zaddr = to_zt_addr(&addr);\n            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {\n                return MAKERESULT(ModuleID, 7);\n            }\n            if (zts_bsd_listen(fd, 10) != 0) {\n                return MAKERESULT(ModuleID, 8);\n            }''')
replace_once(DISC_CPP,
'''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htons(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {\n                return MAKERESULT(ModuleID, 2);\n            }''',
'''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htonl(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            const auto zaddr = to_zt_addr(&addr);\n            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {\n                return MAKERESULT(ModuleID, 2);\n            }''')

# Accept is also part of the virtual socket namespace.
replace_once(DISC_CPP,
'''            struct sockaddr_in addr;\n            socklen_t addrlen = sizeof(addr);\n            int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);''',
'''            struct zts_sockaddr_in zaddr{};\n            zts_socklen_t zaddrlen = sizeof(zaddr);\n            int new_fd = zts_bsd_accept(this->getFd(), reinterpret_cast<zts_sockaddr*>(&zaddr), &zaddrlen);''')

# ZeroTier bootstrap: storage + network id file are shared with the proven NRO.
# Keep this deliberately small; the existing ldn_mitm state machine remains unchanged.
zt_hpp = ROOT / "zt_transport.hpp"
zt_cpp = ROOT / "zt_transport.cpp"
zt_hpp.write_text('''#pragma once\nint zt_ldn_initialize();\n''')
zt_cpp.write_text(r'''#include "zt_transport.hpp"
#include <stratosphere.hpp>
#include <ZeroTierSockets.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>

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
        std::printf("[LDN-ZT] network_id.txt missing/invalid\n");
        return ZTS_ERR_ARG;
    }

    int rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    if (rc != ZTS_ERR_OK) {
        std::printf("[LDN-ZT] zts_init_from_storage=%d\n", rc);
        return rc;
    }
    zts_init_set_port(9993);
    zts_init_allow_secondary_port(1);
    zts_init_allow_port_mapping(1);

    rc = zts_node_start();
    if (rc != ZTS_ERR_OK) {
        std::printf("[LDN-ZT] zts_node_start=%d\n", rc);
        return rc;
    }
    rc = zts_net_join(g_net_id);
    std::printf("[LDN-ZT] join %016llx rc=%d\n", (unsigned long long)g_net_id, rc);
    return rc;
}
''')

# Start ZeroTier after the normal Switch services exist, before ldn:u starts accepting clients.
replace_once(MAIN_CPP, '#include "ldnmitm_service.hpp"', '#include "ldnmitm_service.hpp"\n#include "zt_transport.hpp"')
replace_once(MAIN_CPP,
'''            R_ABORT_UNLESS(socketInitialize(&LibnxSocketInitConfig));\n        }''',
'''            R_ABORT_UNLESS(socketInitialize(&LibnxSocketInitConfig));\n            const int zt_rc = zt_ldn_initialize();\n            if (zt_rc != ZTS_ERR_OK) {\n                LogFormat("[LDN-ZT] initialization failed: %d", zt_rc);\n            }\n        }''')

# Link libzt into the sysmodule. This is evaluated by the inner recursive make too.
make_text = MAKEFILE.read_text()
marker = 'CXXFLAGS\t+= $(VERSION_DEFINES)\n'
if 'third_party/libzt' not in make_text:
    if marker not in make_text:
        raise SystemExit('ldn_mitm Makefile marker not found')
    make_text = make_text.replace(marker, marker + '\n# ZeroTier transport for Switch LDN integration\nINCLUDES += $(TOPDIR)/../../third_party/libzt/include\nLIBDIRS += $(TOPDIR)/../../third_party/libzt\nLIBS += zt\nCXXFLAGS += -DLIBZT_LDN_TRANSPORT\n', 1)
    MAKEFILE.write_text(make_text)

print('LDN ZeroTier transport patch applied')
'''
