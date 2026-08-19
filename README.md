# switch-ldn-zt

Experimental fork of [ldn_mitm](https://github.com/spacemeowx2/ldn_mitm) that routes LDN (local wireless)
traffic over a ZeroTier virtual network using [libzt](https://github.com/zerotier/libzt), instead of
requiring a PC-based bridge (switch-lan-play / lan-play-server) or router-level VPN.

## Goal
Every participating Switch joins the same ZeroTier network ID *from inside the sysmodule itself*.
No PC, no router config, no bridge device needed on either side once it's flashed. Just boot the
game with this sysmodule active and normal WiFi/hotspot internet access.

## Why this might actually work
`ldn_mitm`'s networking is cleanly abstracted behind virtual `recvfrom`/`sendto` in `LanSocket`
(see upstream `source/lan_protocol.hpp`). We don't need to touch the LDN protocol logic at all —
just swap what the packets ride on.

## Status: architecture stub / proof-of-concept — NOT WORKING YET
This is a starting point for iterating, not a working build. Expect it to fail to link or crash on
first hardware boot. See ROADMAP.md.

## Requirements to build
- [devkitPro](https://devkitpro.org/wiki/Getting_Started) with devkitA64 + libnx
- [libstratosphere](https://github.com/Atmosphere-NX/Atmosphere/tree/master/libraries/libstratosphere) (ldn_mitm's existing dependency)
- libzt cross-compiled for aarch64-none-elf (not done yet — see ROADMAP.md step 1)

## Credits
- spacemeowx2 / the ldn_mitm project (base sysmodule + LDN reverse engineering)
- ZeroTier / libzt (embeddable virtual network SDK)
