#!/usr/bin/env python3
"""Fail-fast source compatibility check for Defender ldn_mitm v1.21.2."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ldn_mitm" / "ldn_mitm" / "source"

ANCHORS = {
    "lan_protocol.cpp": [
        "int Pollable::Poll(Pollable *fds[], size_t nfds, int timeout)",
        "struct pollfd pfds[nfds];",
        "int rc = poll(pfds, nfds, timeout);",
        "void LanSocket::close()",
        "::close(this->fd);",
        "::recvfrom(this->fd, buf, len, 0, nullptr, 0)",
        "::sendto(this->fd, buf, len, 0, nullptr, 0)",
        "socklen_t addr_len = sizeof(*addr);",
        "::sendto(this->fd, buf, len, 0, (struct sockaddr *)addr, sizeof(*addr))",
    ],
    "lan_discovery.cpp": [
        "int LDTcpSocket::onRead()",
        "int new_fd = accept(this->getFd(), (struct sockaddr *)&addr, &addrlen);",
        "u32 LDUdpSocket::getBroadcast()",
        "Result LANDiscovery::setSocketOpts(int fd)",
        "fd = ::socket(AF_INET, SOCK_STREAM, 0);",
        "if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {",
        "if (listen(fd, 10) != 0) {",
        "fd = ::socket(AF_INET, SOCK_DGRAM, 0);",
        "int ret = ::connect(this->tcp->getFd(), (struct sockaddr *)&addr, sizeof(addr));",
        "rc = nifmGetCurrentIpAddress(&ipAddress);",
        "rc = nifmGetCurrentIpAddress(&ip);",
        "u32 address, netmask, gateway, primary_dns, secondary_dns;",
        "Result rc = nifmGetCurrentIpConfigInfo(&address, &netmask, &gateway, &primary_dns, &secondary_dns);",
    ],
    "ldn_icommunication.cpp": [
        "Result ICommunicationService::Initialize(const sf::ClientProcessId &client_process_id)",
        "R_TRY(lanDiscovery.initialize([&](){",
        "Result ICommunicationService::GetIpv4Address(sf::Out<u32> address, sf::Out<u32> netmask)",
        "nifmGetCurrentIpConfigInfo(address.GetPointer(), netmask.GetPointer(), &gateway, &primary_dns, &secondary_dns);",
    ],
    "ldnmitm_main.cpp": [
        "R_ABORT_UNLESS(log::Initialize());",
        "LogFormat(\"main\");",
        "R_ABORT_UNLESS((mitm::g_server_manager.RegisterMitmServer<mitm::ldn::LdnMitMService>(0, MitmServiceName)));",
        "LogFormat(\"registered\");",
    ],
}

for name, needles in ANCHORS.items():
    path = SRC / name
    if not path.is_file():
        raise SystemExit(f"missing Defender source: {path}")
    text = path.read_text()
    for needle in needles:
        count = text.count(needle)
        if count == 0:
            raise SystemExit(f"Defender anchor missing: {name}: {needle!r}")
        if name == "lan_discovery.cpp" and needle == "if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) {" and count != 2:
            raise SystemExit(f"Defender anchor count changed: {name}: bind expected 2, found {count}")

print("Defender v1.21.2 source anchors verified")
