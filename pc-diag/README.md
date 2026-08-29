# pc-diag

A stock, unpatched-libzt control node for testing the ZeroTier network this
project uses. It exists to answer questions the Switch build alone can't:

- Does an issue affect only the Switch, or any libzt client on this network?
  (Built from a fresh, un-patched `libzt` clone specifically so it carries
  none of `scripts/patch-zt-upstream-keepalive.py`'s changes.)
- Can two independent nodes actually exchange application data over the
  tunnel? (A UDP PING/PONG exchange, matched by a responder on the Switch
  side in `source/main.cpp`.)

## Build

Requires MSVC (Visual Studio 2022 Build Tools or full VS, with the C++
workload) and CMake. From a Developer Command Prompt / PowerShell with
`cl.exe` on PATH:

```
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DCMAKE_POLICY_VERSION_MINIMUM=3.5
cmake --build build --config Release --target pcdiag
```

Produces `build/Release/pcdiag.exe`. Copy `config/network_id.txt` next to
the exe before running (it reads `config/network_id.txt` relative to its own
working directory).

### Why this specific build setup

- **Generator must be `Visual Studio 17 2022`, not `NMake Makefiles`.**
  libzt's own `CMakeLists.txt` emits Windows link-library strings like
  `WS2_32=/WS2_32.Lib` meant for MSBuild's project XML. NMake's Makefile
  syntax misreads the leading `/` as a file path and fails with
  `NMAKE : fatal error U1073: don't know how to make '\WS2_32.Lib'`. This
  cost most of a build session before the fix was to stop using NMake, not to
  work around the string.
- **`add_compile_definitions(WIN32)` in CMakeLists.txt.** Some vendored code
  (`libnatpmp/getgateway.c`) guards POSIX-only includes with `#ifndef WIN32`.
  MSVC auto-defines `_WIN32` but not the bare `WIN32` this code expects.
- **The `ext/ZeroTierOne/ext` include path.** `osdep/OSUtils.hpp` does
  `#include <nlohmann/json.hpp>`, and the real header lives at
  `ext/ZeroTierOne/ext/nlohmann/json.hpp` -- but libzt's own CMakeLists.txt
  never adds `ext/ZeroTierOne/ext` to the include search path. Neither of
  these is a change to libzt's behavior, just supplying what its own build
  already assumes is available.
- **`ADD_EXPORTS` compile definition on the `pcdiag` target.**
  `ZeroTierSockets.h` decorates every `ZTS_API` declaration
  `__declspec(dllimport)` on Windows unless `ADD_EXPORTS` is defined,
  regardless of whether the library actually being linked is static or
  shared -- the header has no separate "static lib consumer" case. Without
  this, linking fails with `unresolved external symbol __imp_zts_*`.
- **`_IONBF` (unbuffered), not `_IOLBF` (line-buffered), on stdout.** MSVC's
  CRT documents that it does not support real line buffering: a stream
  requesting `_IOLBF` silently gets full buffering instead whenever the
  destination isn't an actual console (a redirected file, a pipe, a process
  launcher's captured output). Without this, a redirected/logged run prints
  nothing until the buffer fills or the process exits.

### zts_bsd_* vs plain sockets

Any code that needs to talk over the ZeroTier virtual network (the
`10.103.5.x`-style tunnel addresses) must use `zts_bsd_socket()` /
`zts_bsd_bind()` / `zts_bsd_sendto()` / `zts_bsd_recvfrom()`, not plain
`socket()`/`bind()`/etc. On the Switch side those plain calls are wrapped to
the real physical network interface (see `source/main.cpp`'s ping responder
and the comment above it) -- an easy mistake, since both APIs look identical
and both compile fine; the failure only shows up as received-but-never-
delivered traffic.

## Running

```
pcdiag.exe                          # join the network, log root/peer activity, no active ping
pcdiag.exe <peer_ip>                 # also ping <peer_ip>:9994 every 2s
pcdiag.exe <peer_ip> <instance> [target_port]
```

`<instance>` (default 0) picks a distinct identity/storage directory and
primary UDP port so two instances can run on the same machine without
fighting over the same identity files or OS socket:

```
pcdiag.exe <switch_ip>          # instance 0: storage ./zt-storage, primary port 9993, local ping port 9994
pcdiag.exe <peer_ip> 1 9994     # instance 1: storage ./zt-storage-1, primary port 9994, local ping port 9995,
                                 # targets the other instance's local ping port (9994) explicitly
```

Each instance needs its own Windows Firewall approval and its own
authorization in ZeroTier Central the first time it runs (new identity,
new node ID) -- expect a firewall prompt and a pending-member entry on the
network's member list.

Ctrl+C exits cleanly: it waits for `ZTS_EVENT_NODE_DOWN` (fired from
`Node`'s own destructor) before tearing down sockets, the same fix applied
to the Switch build's exit path in `source/main.cpp` -- `zts_node_stop()`
only sets a flag and returns immediately, with no way otherwise to know the
service thread has actually finished.
