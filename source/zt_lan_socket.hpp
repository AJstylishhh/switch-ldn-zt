#pragma once
// Drop-in replacement socket backends for ldn_mitm's LanSocket, routing traffic
// through a libzt-managed ZeroTier virtual network instead of the console's
// real local network / internet stack directly.
//
// STATUS: stub / not yet building. See ../ROADMAP.md step 1 before touching this file —
// libzt isn't cross-compiled for the Switch yet, so ZeroTierSockets.h below doesn't exist
// in this toolchain. This file documents the intended shape of the integration.

#include "lan_protocol.hpp"   // upstream ldn_mitm's LanSocket / TcpLanSocketBase / UdpLanSocketBase
// #include <ZeroTierSockets.h>  // uncomment once libzt is actually built for aarch64-none-elf

namespace ams::mitm::ldn::zt {

    // Call once at sysmodule init, before any Zt*LanSocket is constructed.
    // networkId = your ZeroTier network's 16-hex-digit ID (from my.zerotier.com or self-hosted controller)
    // Result initZeroTier(const char *networkId, const char *storagePath);

    class ZtTcpLanSocketBase /* : public TcpLanSocketBase */ {
        // TODO once libzt is linked:
        //   virtual ssize_t recvfrom(void *buf, size_t len, struct sockaddr_in *addr) override {
        //       return zts_bsd_recvfrom(this->fd, buf, len, 0, (struct sockaddr*)addr, sizeof(*addr));
        //   }
        //   virtual int sendto(const void *buf, size_t len, struct sockaddr_in *addr) override {
        //       return zts_bsd_sendto(this->fd, buf, len, 0, (struct sockaddr*)addr, sizeof(*addr));
        //   }
        // fd itself also needs to come from zts_bsd_socket(...) instead of ::socket(...)
        // in LANDiscovery::initTcp — that's a change on the LANDiscovery side, not just here.
    };

    class ZtUdpLanSocketBase /* : public UdpLanSocketBase */ {
        // Same idea as above, plus getBroadcast() needs rethinking:
        // ZeroTier networks are usually /24 or custom-routed, not necessarily using the
        // console's real broadcast semantics. May need ZT network's configured broadcast
        // address instead of deriving it from the real interface like upstream does.
    };

} // namespace ams::mitm::ldn::zt
