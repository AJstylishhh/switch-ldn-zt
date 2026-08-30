#!/usr/bin/env python3
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
LDN = ROOT / "ldn_mitm" / "ldn_mitm"
SRC = LDN / "source"
ZT_INC = ROOT / "third_party" / "libzt" / "include"
ZT_LIB = ROOT / "third_party" / "libzt" / "lib"


def replace(path, old, new):
    text = path.read_text()
    if old not in text:
        raise SystemExit(f"patch anchor missing: {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1))


def replace_all(path, old, new, minimum=1):
    text = path.read_text()
    count = text.count(old)
    if count < minimum:
        raise SystemExit(f"patch anchor missing: {path}: expected at least {minimum}, found {count}: {old[:80]!r}")
    path.write_text(text.replace(old, new))


def replace_function(path, signature, new_body):
    text = path.read_text()
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"patch function missing: {path}: {signature!r}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"patch function has no opening brace: {path}: {signature!r}")

    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f"patch function has unbalanced braces: {path}: {signature!r}")

    replacement = signature + " " + new_body
    path.write_text(text[:start] + replacement + text[end:])


def main():
    if not (ZT_INC / "ZeroTierSockets.h").is_file():
        raise SystemExit("libzt headers missing")
    if not (ZT_LIB / "libzt.a").is_file():
        raise SystemExit("libzt.a missing")

    shutil.copy2(ROOT / "scripts" / "zt_bridge.hpp", SRC / "zt_bridge.hpp")
    shutil.copy2(ROOT / "scripts" / "zt_bridge.cpp", SRC / "zt_bridge.cpp")
    shutil.copy2(ROOT / "scripts" / "errno_compat.c", SRC / "errno_compat.c")

    lp = SRC / "lan_protocol.cpp"
    replace(lp, '#include <stratosphere.hpp>\n', '#include <stratosphere.hpp>\n#include "zt_bridge.hpp"\n')
    old_poll = '''    struct pollfd pfds[nfds];
    for (size_t i = 0; i < nfds; i++) {
        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;
        pfds[i].events = POLLIN;
        pfds[i].revents = 0;
    }
    int rc = poll(pfds, nfds, timeout);'''
    new_poll = '''    ztbridge::PollFd pfds[nfds];
    for (size_t i = 0; i < nfds; i++) {
        pfds[i].fd = fds[i] ? fds[i]->getFd() : -1;
        pfds[i].events = ZT_POLLIN;
        pfds[i].revents = 0;
    }
    int rc = ztbridge::poll(pfds, nfds, timeout);'''
    replace(lp, old_poll, new_poll)
    replace(lp, '        const struct pollfd &pfd = pfds[i];', '        const ztbridge::PollFd &pfd = pfds[i];')
    replace(lp, 'if (pfd.revents & (POLLERR | POLLHUP))', 'if (pfd.revents & (ZT_POLLERR | ZT_POLLHUP | ZT_POLLNVAL))')
    replace(lp, 'else if (pfd.revents & (POLLIN | POLLPRI))', 'else if (pfd.revents & (ZT_POLLIN | ZT_POLLPRI))')
    replace(lp, '        ::close(this->fd);', '        ztbridge::close(this->fd);')
    replace(lp, '    auto rc = ::recvfrom(this->fd, buf, len, 0, nullptr, 0);', '    auto rc = ztbridge::recv(this->fd, buf, len);')
    replace(lp, '    return ::sendto(this->fd, buf, len, 0, nullptr, 0);', '    return ztbridge::send(this->fd, buf, len);')
    replace(lp, '    socklen_t addr_len = sizeof(*addr);\n    return ::recvfrom(this->fd, buf, len, 0, (struct sockaddr *)addr, &addr_len);', '    AMS_UNUSED(addr);\n    return ztbridge::recv(this->fd, buf, len);')
    replace(lp, '    return ::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr));', '    return ztbridge::sendto(this->fd, buf, len, addr);')

    ld = SRC / "lan_discovery.cpp"
    replace(ld, '#include "ipinfo.hpp"\n', '#include "ipinfo.hpp"\n#include "zt_bridge.hpp"\n')
    replace(ld, '''            struct sockaddr_in addr;
            socklen_t addrlen = sizeof(addr);
            int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);''', '''            int new_fd = ztbridge::accept(this->getFd());''')
    replace(ld, '            close(new_fd);', '            ztbridge::close(new_fd);')
    replace_function(ld, '    u32 LDUdpSocket::getBroadcast()', '''{
        return ztbridge::peer_ip_host_order();
    }''')
    replace_function(ld, '    Result LANDiscovery::setSocketOpts(int fd)', '''{
        AMS_UNUSED(fd);
        return 0;
    }''')
    replace(ld, '        fd = ::socket(AF_INET, SOCK_STREAM, 0);', '        fd = ztbridge::socket(AF_INET, SOCK_STREAM, 0);')
    replace_all(ld, '            if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {', '            if (ztbridge::bind(fd, &addr) != 0) {', minimum=2)
    replace(ld, '            if (listen(fd, 10) != 0) {', '            if (ztbridge::listen(fd, 10) != 0) {')
    replace(ld, '        fd = ::socket(AF_INET, SOCK_DGRAM, 0);', '        fd = ztbridge::socket(AF_INET, SOCK_DGRAM, 0);')
    replace(ld, '        int ret = ::connect(this->tcp->getFd(), (struct sockaddr *)&addr, sizeof(addr));', '        int ret = ztbridge::connect(this->tcp->getFd(), &addr);')
    replace(ld, '        Result rc = nifmGetCurrentIpAddress(&ipAddress);\n        if (R_FAILED(rc))\n        {\n            return rc;\n        }\n        ipAddress = ntohl(ipAddress);', '        Result rc = ztbridge::local_ip_host_order(&ipAddress);\n        if (R_FAILED(rc)) {\n            return rc;\n        }')
    replace(ld, '        Result rc = nifmGetCurrentIpAddress(&ip);\n        if (R_SUCCEEDED(rc)) {\n            ip = ntohl(ip);\n            memcpy(mac->raw + 2, &ip, sizeof(ip));\n        }\n\n        return rc;', '        Result rc = ztbridge::local_ip_host_order(&ip);\n        if (R_SUCCEEDED(rc)) {\n            memcpy(mac->raw + 2, &ip, sizeof(ip));\n        }\n        return rc;')

    li = SRC / "ldn_icommunication.cpp"
    replace(li, '#include <arpa/inet.h>\n', '#include <arpa/inet.h>\n#include "zt_bridge.hpp"\n')
    replace(li, '        R_TRY(lanDiscovery.initialize([&](){', '        R_TRY(ztbridge::init());\n\n        R_TRY(lanDiscovery.initialize([&](){')
    replace_function(li, '    Result ICommunicationService::GetIpv4Address(sf::Out<u32> address, sf::Out<u32> netmask)', '''{
        u32 ztAddress = 0;
        Result rc = ztbridge::local_ip_host_order(&ztAddress);
        if (R_FAILED(rc)) {
            return rc;
        }

        address.SetValue(ztAddress);
        netmask.SetValue(0xFFFFFFFF);
        LogFormat("get_ipv4_address %x %x", address.GetValue(), netmask.GetValue());
        return rc;
    }''')

    mk = LDN / "Makefile"
    text = mk.read_text()
    libzt_dir = (ROOT / "third_party" / "libzt").resolve().as_posix()
    if "LIBDIRS += " not in text or "third_party/libzt" not in text:
        text = text.replace(
            'CXXFLAGS\t+= $(VERSION_DEFINES)\n',
            'CXXFLAGS\t+= $(VERSION_DEFINES)\n'
            f'LIBDIRS += {libzt_dir}\n'
            'LIBS += -lzt -lnx\n'
        )
        mk.write_text(text)
    elif "LIBS += -lzt -lnx" not in text:
        text = text.replace('LIBS += -lzt\n', 'LIBS += -lzt -lnx\n')
        mk.write_text(text)

    print("LDN ZeroTier patch applied")
    print(f"libzt Makefile directory: {libzt_dir}")
    print("libnx linked for Switch POSIX errno/socket compatibility")

if __name__ == '__main__':
    main()
