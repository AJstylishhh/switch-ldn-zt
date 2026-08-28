from pathlib import Path

# The Switch build uses libzt's NodeService + ZeroTierOne Phy as the real
# physical UDP transport. Keep SO_NO_CHECK disabled on Switch, and add a small
# receive-path trace so we can distinguish:
#   select -> recvfrom -> NodeService::phyOnDatagram
# without adding any artificial delay or changing ZeroTier's scheduler.

patched = False

for path in Path("libzt").rglob("NodeService.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue

    needle = "_phy(this, false, true)"
    if needle in s:
        if s.count(needle) != 1:
            raise SystemExit(f"ERROR: expected one {needle} in {path}, found {s.count(needle)}")
        s = s.replace(needle, "_phy(this, false, false)", 1)
        patched = True

    # Instrument the actual handoff from Phy::recvfrom() into ZeroTier core.
    if "[SWITCH-PHY] NodeService RX" not in s:
        include_marker = '#include <stdlib.h>\n'
        if include_marker in s and '#ifdef __SWITCH__\n#include <stdio.h>\n#endif' not in s:
            s = s.replace(
                include_marker,
                include_marker + '#ifdef __SWITCH__\n#include <stdio.h>\n#endif\n',
                1,
            )

        marker = "void NodeService::phyOnDatagram(\n"
        p = s.find(marker)
        if p < 0:
            raise SystemExit(f"ERROR: phyOnDatagram() not found in {path}")
        body = s.find("{", p)
        if body < 0:
            raise SystemExit(f"ERROR: phyOnDatagram() body not found in {path}")

        trace = r'''{
#ifdef __SWITCH__
    static unsigned int switch_phy_rx_trace = 0;
    const unsigned int trace_n = __sync_fetch_and_add(&switch_phy_rx_trace, 1);
    if (trace_n < 20 || (trace_n % 100) == 0) {
        const struct sockaddr_in* la = (localAddr && localAddr->sa_family == AF_INET)
            ? reinterpret_cast<const struct sockaddr_in*>(localAddr) : NULL;
        const struct sockaddr_in* ra = (from && from->sa_family == AF_INET)
            ? reinterpret_cast<const struct sockaddr_in*>(from) : NULL;
        fprintf(stderr,
                "[SWITCH-PHY] NodeService RX #%u len=%lu local=%u remote=%u\n",
                trace_n + 1,
                len,
                la ? (unsigned)ntohs(la->sin_port) : 0u,
                ra ? (unsigned)ntohs(ra->sin_port) : 0u);
    }
#endif
'''
        s = s[:body] + trace + s[body + 1:]

    path.write_text(s)
    print(f"Switch PHY patch applied to active NodeService: {path}")
    patched = True
    break

if not patched:
    raise SystemExit("ERROR: could not find active libzt NodeService.cpp")

# Instrument the actual UDP select/recvfrom boundary in the active Phy.hpp.
# Current ZeroTierOne keeps this header under ext/ZeroTierOne/osdep/Phy.hpp.
# Do not depend on one exact function signature because upstream has changed
# the UDP poll implementation over time (including a Linux-only recvmmsg path).
phy_found = False
for path in Path("libzt").rglob("Phy.hpp"):
    try:
        s = path.read_text()
    except Exception:
        continue

    # Identify the ZeroTier PHY header by the actual UDP implementation rather
    # than an exact whitespace/signature match that can break on upstream
    # changes.
    if "udpBind(" not in s or "recvfrom(" not in s or "phyOnDatagram" not in s:
        continue

    phy_found = True

    if "[SWITCH-PHY] UDP recv" in s:
        print(f"Switch PHY receive trace already present: {path}")
        break

    if '#ifdef __SWITCH__\n#include <stdio.h>\n#endif' not in s:
        marker = '#include <string.h>\n'
        if marker not in s:
            raise SystemExit(f"ERROR: include marker not found in {path}")
        s = s.replace(
            marker,
            marker + '#ifdef __SWITCH__\n#include <stdio.h>\n#endif\n',
            1,
        )

    # The current upstream non-Linux UDP path uses this recvfrom statement.
    target = "long n = (long)::recvfrom(s->sock, buf, sizeof(buf), 0, (struct sockaddr*)&ss, &slen);\n"
    if target not in s:
        raise SystemExit(f"ERROR: active recvfrom() statement not found in {path}")

    replacement = target + r'''#ifdef __SWITCH__
							static unsigned int switch_phy_recv_trace = 0;
							const unsigned int recv_trace_n = __sync_fetch_and_add(&switch_phy_recv_trace, 1);
							if (recv_trace_n < 20 || (n < 0 && recv_trace_n < 40)) {
								fprintf(stderr, "[SWITCH-PHY] UDP recv fd=%d n=%ld errno=%d\n",
								        (int)s->sock, n, (n < 0) ? errno : 0);
							}
#endif
'''
    s = s.replace(target, replacement, 1)

    # Add a single trace on select wakeups for the first few UDP events. This
    # tells us whether the lwIP select layer is seeing the incoming socket at
    # all. It is deliberately capped; it does not alter select/recvfrom.
    udp_marker = "case ZT_PHY_SOCKET_UDP:\n\t\t\t\t\tif (FD_ISSET(s->sock, &rfds)) {\n"
    if udp_marker not in s:
        raise SystemExit(f"ERROR: UDP poll case marker not found in {path}")
    udp_replacement = udp_marker + r'''#ifdef __SWITCH__
						static unsigned int switch_phy_ready_trace = 0;
						const unsigned int ready_trace_n = __sync_fetch_and_add(&switch_phy_ready_trace, 1);
						if (ready_trace_n < 20) {
							fprintf(stderr, "[SWITCH-PHY] UDP select-readable fd=%d\n", (int)s->sock);
						}
#endif
'''
    s = s.replace(udp_marker, udp_replacement, 1)

    path.write_text(s)
    print(f"Switch PHY select/recv trace applied: {path}")
    break

if not phy_found:
    raise SystemExit("ERROR: active libzt Phy.hpp not found")