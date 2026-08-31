#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LDN = ROOT / "ldn_mitm" / "ldn_mitm"
SRC = LDN / "source"
STUBS_ONLY = True
EXPECTED_LDN = "2fe07817eeea06b712009395f8bbcb2a02d30979"


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
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f"patch function has unbalanced braces: {path}: {signature!r}")
    path.write_text(text[:start] + signature + " " + new_body + text[end:])


def main():
    if not STUBS_ONLY:
        raise SystemExit("This build mode is stubs-only; real libzt is intentionally disabled")

    subprocess.run(["python3", str(ROOT / "scripts" / "anchor_check_defender.py")], check=True)
    actual = subprocess.check_output(["git", "-C", str(ROOT / "ldn_mitm"), "rev-parse", "HEAD"], text=True).strip()
    if actual != EXPECTED_LDN:
        raise SystemExit(f"wrong ldn_mitm commit: {actual} != {EXPECTED_LDN}")

    shutil.copy2(ROOT / "scripts" / "zt_bridge.hpp", SRC / "zt_bridge.hpp")
    shutil.copy2(ROOT / "scripts" / "zt_stubs.cpp", SRC / "zt_stubs.cpp")

    main_cpp = SRC / "ldnmitm_main.cpp"
    replace(main_cpp, '        R_ABORT_UNLESS(log::Initialize());\n        LogFormat("main");', '        R_ABORT_UNLESS(log::Initialize());\n        LogFormat("LDN-ZT: Main entered");')
    replace(main_cpp, '        R_ABORT_UNLESS((mitm::g_server_manager.RegisterMitmServer<mitm::ldn::LdnMitMService>(0, MitmServiceName)));\n        LogFormat("registered");', '        R_ABORT_UNLESS((mitm::g_server_manager.RegisterMitmServer<mitm::ldn::LdnMitMService>(0, MitmServiceName)));\n        LogFormat("LDN-ZT: mitm registered");')

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
    # Defender v1.21.2 exact getNodeInfo/getFakeMac blocks use `rc =`, not `Result rc =`.
    replace(ld, '''        rc = nifmGetCurrentIpAddress(&ipAddress);
        if (R_FAILED(rc))
        {
            return rc;
        }
        ipAddress = ntohl(ipAddress);''', '''        rc = ztbridge::local_ip_host_order(&ipAddress);
        if (R_FAILED(rc))
        {
            return rc;
        }''')
    replace(ld, '''        rc = nifmGetCurrentIpAddress(&ip);
        if (R_SUCCEEDED(rc)) {
            ip = ntohl(ip);
            memcpy(mac->raw + 2, &ip, sizeof(ip));
        }
        return rc;''', '''        rc = ztbridge::local_ip_host_order(&ip);
        if (R_SUCCEEDED(rc)) {
            memcpy(mac->raw + 2, &ip, sizeof(ip));
        }
        return rc;''')

    li = SRC / "ldn_icommunication.cpp"
    replace(li, '#include <arpa/inet.h>\n', '#include <arpa/inet.h>\n#include "zt_bridge.hpp"\n')
    replace(li, '        R_TRY(lanDiscovery.initialize([&](){', '''        if (ztbridge::init() != 0) {
            return MAKERESULT(0xFD, 0x50);
        }

        R_TRY(lanDiscovery.initialize([&](){''')
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
    if '-lzt' in text:
        text = text.replace('LIBS += -lzt -lnx', 'LIBS += -lnx').replace('LIBS += -lzt', 'LIBS += -lnx')
    if 'zt_stubs.cpp' not in text:
        text = text.replace('source/zt_bridge.cpp', 'source/zt_stubs.cpp')
        if 'zt_stubs.cpp' not in text:
            text = text.replace('$(SOURCES)', '$(SOURCES) source/zt_stubs.cpp')
    mk.write_text(text)
    print("LDN-ZT stubs-first patch applied; no libzt.a / no -lzt")

if __name__ == '__main__':
    main()
