from pathlib import Path

# NodeService.cpp's peer-event dispatch does:
#     pr = new zts_peer_info_t();
#     ZT_Peer* peer = (ZT_Peer*)obj;
#     memcpy(pr, peer, sizeof(zts_peer_info_t));
#     for (unsigned int j = 0; j < peer->pathCount; j++) {
#         native_ss_to_zts_ss(&(pr->paths[j].address), &(peer->paths[j].address));
#     }
#
# This assumes ZT_Peer and zts_peer_info_t share an identical field layout.
# They do not, past latency. Comparing the two headers field-by-field
# (offsets in bytes, x86_64):
#
#   ZT_Peer (ZeroTierOne.h)         zts_peer_info_t (ZeroTierSockets.h)
#   address           0   u64       peer_id            0   u64   (matches)
#   versionMajor      8   int       ver_major          8   int   (matches)
#   versionMinor     12   int       ver_minor         12   int   (matches)
#   versionRev       16   int       ver_rev           16   int   (matches)
#   latency          20   int       latency           20   int   (matches)
#   role             24   enum      role              24   enum  (matches)
#   isBonded         28   bool      path_count        28   uint  <- reads isBonded, not pathCount
#   bondingPolicy    32   int       unused_0          32   int   <- reads bondingPolicy
#   numAliveLinks    36   int       paths[]           36   ...   <- reads numAliveLinks as the
#   numTotalLinks    40   int                                       start of a differently-typed,
#   customBondName   44   char[32]                                  differently-sized array
#   pathCount        76   uint                        (never reached by the copy)
#   paths[]          80   ZT_PeerPhysicalPath[64]
#
# So the path_count every caller sees is actually ZT_Peer::isBonded reinterpreted
# as a uint32 (almost always 0), never the real path count 48 bytes further in --
# this is exactly why every [ZT] PEER event on the Switch build printed
# "paths=0" regardless of how many real paths a peer had, confirmed on hardware
# alongside a PEER_PATH_DISCOVERED event (which is gated on the real
# ZT_Peer::pathCount before this copy runs, so the event itself is trustworthy;
# only the value printed from the copied struct was not).
#
# It is also worse than wrong data: zts_peer_info_t (with its 64-element
# zts_path_t[] holding a raw char* per entry) is a different size than ZT_Peer,
# so memcpy(pr, peer, sizeof(zts_peer_info_t)) copies however many bytes
# zts_peer_info_t occupies starting from a ZT_Peer*, which reads past the real
# ZT_Peer object into whatever memory follows it once zts_peer_info_t is
# larger than ZT_Peer -- an out-of-bounds heap read, not just misattributed
# fields.
#
# Fix: copy each top-level field by name instead of by raw byte range, and
# populate each path's fields the same way, bounded by the smaller of the two
# array capacities (both are 64 today, but this stops being invariant-fragile
# if either header ever changes independently). ifname is deliberately left
# untouched (stays null-initialized): ZT_PeerPhysicalPath::ifname is a fixed
# char[] living inside a ZT_Peer that NodeService.cpp frees via
# freeQueryResult() shortly after this dispatch runs, so storing a pointer
# into it on zts_path_t (a bare char*, not an owned copy) would trade a wrong
# value for a dangling one.

n = Path('libzt/src/NodeService.cpp')

old = """            pr = new zts_peer_info_t();
            ZT_Peer* peer = (ZT_Peer*)obj;
            memcpy(pr, peer, sizeof(zts_peer_info_t));
            for (unsigned int j = 0; j < peer->pathCount; j++) {
                native_ss_to_zts_ss(&(pr->paths[j].address), &(peer->paths[j].address));
            }
            objptr = (void*)pr;"""

new = """            pr = new zts_peer_info_t();
            ZT_Peer* peer = (ZT_Peer*)obj;
            // See scripts/patch-zt-peer-info-struct.py for why this cannot be
            // a memcpy: ZT_Peer and zts_peer_info_t do not share a layout
            // past latency, and a raw memcpy(pr, peer, sizeof(zts_peer_info_t))
            // reads past the end of the real ZT_Peer object.
            pr->peer_id = peer->address;
            pr->ver_major = peer->versionMajor;
            pr->ver_minor = peer->versionMinor;
            pr->ver_rev = peer->versionRev;
            pr->latency = peer->latency;
            pr->role = (zts_peer_role_t)peer->role;
            pr->path_count = peer->pathCount;
            pr->unused_0 = 0;
            const unsigned int path_limit = (peer->pathCount < ZTS_MAX_PEER_NETWORK_PATHS)
                ? peer->pathCount : ZTS_MAX_PEER_NETWORK_PATHS;
            for (unsigned int j = 0; j < path_limit; j++) {
                native_ss_to_zts_ss(&(pr->paths[j].address), &(peer->paths[j].address));
                pr->paths[j].last_tx = peer->paths[j].lastSend;
                pr->paths[j].last_rx = peer->paths[j].lastReceive;
                pr->paths[j].trusted_path_id = peer->paths[j].trustedPathId;
                pr->paths[j].latency = peer->paths[j].latencyMean;
                pr->paths[j].expired = peer->paths[j].expired;
                pr->paths[j].preferred = peer->paths[j].preferred;
            }
            objptr = (void*)pr;"""

found = False
for path in Path('libzt').rglob('NodeService.cpp'):
    try:
        s = path.read_text()
    except Exception:
        continue
    if new.strip() in s:
        print(f"Peer-info struct copy already patched: {path}")
        found = True
        break
    if old in s:
        if s.count(old) != 1:
            raise SystemExit(f"ERROR: expected one peer-info memcpy block in {path}, found {s.count(old)}")
        path.write_text(s.replace(old, new, 1), newline='')
        print(f"Fixed ZT_Peer -> zts_peer_info_t field-by-field copy (was a mismatched-layout memcpy): {path}")
        found = True
        break

if not found:
    raise SystemExit("ERROR: could not find the peer-info memcpy block in any NodeService.cpp")
