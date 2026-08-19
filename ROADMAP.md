# Roadmap

Ordered by risk — do these in order, because step 1 is the thing that could kill the whole
project, and there's no point writing Switch-specific glue code before knowing libzt even
compiles for the target.

## 1. Cross-compile libzt for aarch64-none-elf (libnx target) — HIGHEST RISK
libzt has never been built for the Switch homebrew toolchain. It normally targets full OSes
(Linux/macOS/Windows/Android/iOS) with a real libc. libnx uses a stripped-down newlib.

Tasks:
- [ ] Clone `zerotier/libzt`, inspect `CMakeLists.txt` and `cmake/` toolchain files
- [ ] Write a devkitA64 CMake toolchain file (see devkitPro's `Switch.cmake` examples in other
      libnx CMake-based projects for reference)
- [ ] Try building `libztcore` first (no socket API, just the ZT virtual network engine) before
      the full `libzt` (which adds lwIP userspace TCP/IP stack — much bigger surface area to port)
- [ ] Expect missing syscalls/symbols (threading primitives, clock functions, RNG) — libnx has
      its own APIs (`svc*`, `threadCreate`, etc.) that may need shim implementations
- [ ] If libztcore builds: try adding the lwIP socket layer (`libzt` proper) next

If this step is a dead end, fall back to a lighter approach: use `libztcore` directly (no BSD
socket emulation) and hand-write the packet send/receive glue instead of relying on lwIP.

## 2. Memory / stack budget audit
- [ ] Check ldn_mitm's current sysmodule memory budget in its `.npdm`/module linker config
- [ ] Estimate libzt's runtime footprint (ZT crypto, lwIP buffers, its own worker thread)
- [ ] Increase heap/stack sizes as needed — this is a config change, low risk, but must happen
      before step 3 or you'll get silent stack-overflow crashes that look like unrelated bugs

## 3. Write ZtLanSocket classes
- [ ] `ZtUdpLanSocketBase : public UdpLanSocketBase` — override `recvfrom`/`sendto` to call
      `zts_bsd_recvfrom` / `zts_bsd_sendto`
- [ ] `ZtTcpLanSocketBase : public TcpLanSocketBase` — same idea for TCP
- [ ] Swap these in for the real ones in `LANDiscovery::initTcp` / `initUdp`
- [ ] Bake in `zts_node_start()` + `zts_net_join(NETWORK_ID)` at sysmodule init

## 4. First hardware boot
- [ ] Flash to a test Switch, watch logs (ldn_mitm already has a debug log macro — use it)
- [ ] Expect crashes here. This is normal. Iterate.

## 5. Two-console test
- [ ] Once one console boots without crashing and gets a ZeroTier IP, repeat on a second console
- [ ] Confirm they can see each other in the local wireless scan inside a real LDN-supporting game

## Known unknowns going in
- Whether lwIP's userspace stack plays nicely with libnx's own `bsd` sysmodule sockets underneath
  (libzt still needs *some* real UDP socket to talk to ZeroTier's roots/peers over the internet)
- Whether ZeroTier's peer-to-peer NAT traversal works reliably on mobile hotspot NAT (carrier-grade
  NAT / double NAT is common on phone hotspots and is the one thing ZeroTier sometimes struggles with)
- Realistic timeline: this is a multi-week-to-months hobby project, not a weekend one
