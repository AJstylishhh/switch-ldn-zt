# LDN game traffic

This document tracks the next development phase after the working ZeroTier runtime baseline.

## Goal
Route Nintendo Switch LDN/game networking traffic over the ZeroTier-backed transport without disturbing the existing ZeroTier node/runtime diagnostics.

## Baseline
- Keep the existing ZeroTier initialization and diagnostics intact.
- Preserve the current ~5 second heartbeat/diagnostic behavior.
- Do not claim game traffic works until an actual LDN/game-socket test demonstrates it.

## Next steps
1. Identify the libnx/LDN socket/interface path used by the target game.
2. Determine where LDN peer discovery and game traffic enter the Switch networking stack.
3. Add instrumentation around the relevant socket/interface calls.
4. Verify whether traffic reaches the ZeroTier interface and whether return traffic is routed back correctly.
5. Implement the smallest routing/bridge layer needed for the target LDN traffic.
6. Test with two Switches and record packet direction, ports, peer addresses, and failures.

## Important constraint
ZeroTier node connectivity is not by itself proof of LDN game-socket routing. The game traffic path must be demonstrated separately.
