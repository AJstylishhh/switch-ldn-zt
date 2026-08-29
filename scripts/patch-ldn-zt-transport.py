#!/usr/bin/env python3
from pathlib import Path

ROOT = Path("ldn_mitm/ldn_mitm/source")
PROTO_CPP = ROOT / "lan_protocol.cpp"
DISC_CPP = ROOT / "lan_discovery.cpp"
MAIN_CPP = ROOT / "ldnmitm_main.cpp"
MAKEFILE = Path("ldn_mitm/ldn_mitm/Makefile")


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"expected text not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1))

# Keep the upstream ldn:u state machine intact. Only the LAN socket backend is
# redirected to the already-built libzt socket API.
replace_once(
    PROTO_CPP,
    '#include "debug.hpp"\n#include <poll.h>',
    '''#include "debug.hpp"\n#include <poll.h>\n#include <ZeroTierSockets.h>''',
)

replace_once(
    PROTO_CPP,
    '''#define POLL_UNKNOWN (~(POLLIN | POLLPRI | POLLOUT))''',
    '''#define POLL_UNKNOWN (~(POLLIN | POLLPRI | POLLOUT))\n\nstatic zts_sockaddr_in to_zt_addr(const sockaddr_in *addr) {\n    zts_sockaddr_in out{};\n    out.sin_len = sizeof(out);\n    out.sin_family = ZTS_AF_INET;\n    if (addr) {\n        out.sin_port = addr->sin_port;\n        out.sin_addr.s_addr = addr->sin_addr.s_addr;\n    }\n    return out;\n}\n\nstatic void from_zt_addr(const zts_sockaddr_in &in, sockaddr_in *addr) {\n    if (!addr) return;\n    std::memset(addr, 0, sizeof(*addr));\n    addr->sin_family = AF_INET;\n    addr->sin_port = in.sin_port;\n    addr->sin_addr.s_addr = in.sin_addr.s_addr;\n}''',
)

old_poll = '''    struct pollfd pfds[nfds];\n    for (size_t i = 0; i < nfds; i++) {\n        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;\n        pfds[i].events = POLLIN;\n        pfds[i].revents = 0;\n    }\n    int rc = poll(pfds, nfds, timeout);'''
new_poll = '''    struct zts_pollfd pfds[nfds];\n    for (size_t i = 0; i < nfds; i++) {\n        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;\n        pfds[i].events = ZTS_POLLIN;\n        pfds[i].revents = 0;\n    }\n    int rc = zts_bsd_poll(pfds, static_cast<zts_nfds_t>(nfds), timeout);'''
replace_once(PROTO_CPP, old_poll, new_poll)
replace_once(PROTO_CPP, 'const struct pollfd &pfd = pfds[i];', 'const struct zts_pollfd &pfd = pfds[i];')
replace_once(PROTO_CPP, 'pfd.revents & POLL_UNKNOWN', 'pfd.revents & (POLL_UNKNOWN)')
replace_once(PROTO_CPP, 'pfd.revents & (POLLERR | POLLHUP)', 'pfd.revents & (ZTS_POLLERR | ZTS_POLLHUP | ZTS_POLLNVAL)')
replace_once(PROTO_CPP, 'pfd.revents & (POLLIN | POLLPRI)', 'pfd.revents & ZTS_POLLIN')
replace_once(PROTO_CPP, '::close(this->fd);', 'zts_bsd_close(this->fd);')

replace_once(
    PROTO_CPP,
    '''    auto rc = ::recvfrom(this->fd, buf, len, 0, nullptr, 0);''',
    '''    auto rc = zts_bsd_recv(this->fd, buf, len, 0);''',
)
replace_once(
    PROTO_CPP,
    '''    return ::sendto(this->fd, buf, len, 0, nullptr, 0);''',
    '''    return static_cast<int>(zts_bsd_send(this->fd, buf, len, 0));''',
)
replace_once(
    PROTO_CPP,
    '''    socklen_t addr_len = sizeof(*addr);\n    return ::recvfrom(this->fd, buf, len, 0, (struct sockaddr *)addr, &addr_len);''',
    '''    zts_sockaddr_in zaddr{};\n    zts_socklen_t zlen = sizeof(zaddr);\n    const auto rc = zts_bsd_recvfrom(this->fd, buf, len, 0, reinterpret_cast<zts_sockaddr*>(&zaddr), &zlen);\n    if (rc >= 0) from_zt_addr(zaddr, addr);\n    return rc;''',
)
replace_once(
    PROTO_CPP,
    '''    return ::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr));''',
    '''    const auto zaddr = to_zt_addr(addr);\n    return static_cast<int>(zts_bsd_sendto(this->fd, buf, len, 0, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)));''',
)

# Discovery has its own socket creation/lifecycle, so it must use the same ZT
# descriptor namespace as Pollable. The existing discovery state machine remains.
replace_once(
    DISC_CPP,
    '#include "lan_discovery.hpp"',
    '''#include "lan_discovery.hpp"\n#include <ZeroTierSockets.h>\n#include <cstring>\n\nstatic zts_sockaddr_in to_zt_addr(const sockaddr_in *addr) {\n    zts_sockaddr_in out{};\n    out.sin_len = sizeof(out);\n    out.sin_family = ZTS_AF_INET;\n    if (addr) {\n        out.sin_port = addr->sin_port;\n        out.sin_addr.s_addr = addr->sin_addr.s_addr;\n    }\n    return out;\n}''',
)
replace_once(DISC_CPP, 'close(new_fd);', 'zts_bsd_close(new_fd);')
replace_once(DISC_CPP, 'close(new_fd);', 'zts_bsd_close(new_fd);')
replace_once(DISC_CPP, 'setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &b, sizeof(b))', 'zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_BROADCAST, &b, sizeof(b))')
replace_once(DISC_CPP, 'setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes))', 'zts_bsd_setsockopt(fd, ZTS_SOL_SOCKET, ZTS_SO_REUSEADDR, &yes, sizeof(yes))')
replace_once(DISC_CPP, 'fd = ::socket(AF_INET, SOCK_STREAM, 0);', 'fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_STREAM, 0);')
replace_once(DISC_CPP, 'fd = ::socket(AF_INET, SOCK_DGRAM, 0);', 'fd = zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_DGRAM, 0);')

# Bind using a ZeroTier sockaddr. The existing code has two listen paths.
replace_once(
    DISC_CPP,
    '''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htons(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {\n                return MAKERESULT(ModuleID, 7);\n            }\n            if (listen(fd, 10) != 0) {''',
    '''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htonl(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            const auto zaddr = to_zt_addr(&addr);\n            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {\n                return MAKERESULT(ModuleID, 7);\n            }\n            if (zts_bsd_listen(fd, 10) != 0) {''',
)
replace_once(
    DISC_CPP,
    '''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htons(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {\n                return MAKERESULT(ModuleID, 2);\n            }''',
    '''            addr.sin_family = AF_INET;\n            addr.sin_addr.s_addr = htonl(INADDR_ANY);\n            addr.sin_port = htons(listenPort);\n            const auto zaddr = to_zt_addr(&addr);\n            if (zts_bsd_bind(fd, reinterpret_cast<const zts_sockaddr*>(&zaddr), sizeof(zaddr)) != 0) {\n                return MAKERESULT(ModuleID, 2);\n            }''',
)
replace_once(
    DISC_CPP,
    '''            struct sockaddr_in addr;\n            socklen_t addrlen = sizeof(addr);\n            int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);''',
    '''            zts_sockaddr_in zaddr{};\n            zts_socklen_t zaddrlen = sizeof(zaddr);\n            int new_fd = zts_bsd_accept(this->getFd(), reinterpret_cast<zts_sockaddr*>(&zaddr), &zaddrlen);''',
)

# The libzt API owns the LAN transport sockets. Link the staged static library.
make_text = MAKEFILE.read_text()
if 'LIBZT_LDN_TRANSPORT' not in make_text:
    marker = 'CXXFLAGS\t+= $(VERSION_DEFINES)\n'
    if marker not in make_text:
        raise SystemExit('ldn_mitm Makefile marker not found')
    make_text = make_text.replace(
        marker,
        marker + '''\n# ZeroTier transport\nINCLUDES += $(TOPDIR)/../../third_party/libzt/include\nLIBDIRS += $(TOPDIR)/../../third_party/libzt\nLIBS += zt\nCXXFLAGS += -DLIBZT_LDN_TRANSPORT\n''',
        1,
    )
    MAKEFILE.write_text(make_text)

print("LDN ZeroTier transport patch applied")
