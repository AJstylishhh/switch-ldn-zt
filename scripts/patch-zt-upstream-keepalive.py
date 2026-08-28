from pathlib import Path

# ZeroTier keeps a node "online" only while it has heard from an upstream (root)
# within ZT_PEER_ACTIVITY_TIMEOUT, which is 30s. Between full HELLOs that contact is
# meant to be refreshed by small encrypted VERB_ECHO keepalives, sent from
# Peer::attemptToContactAt.
#
# On this console the roots reliably answer HELLO -- the handshake succeeds against
# all four every time, with real measured latencies -- but never answer the encrypted
# ECHO keepalives. Captured on hardware: every root goes silent the moment the
# handshake completes, while the network controller keeps exchanging encrypted
# traffic with us normally. So this is specific to root ECHO handling, and not to our
# crypto or our socket, both of which are demonstrably fine in each direction.
#
# With ECHO unanswered, contact only ever refreshes on the full-HELLO cycle, and two
# separate gates control that cycle. BOTH have to move.
#
# The outer gate is in Node.cpp's _PingPeersThatNeedPing, which deliberately contacts
# upstreams "as infrequently as possible" on a role-based scale of 16, i.e. every
# ZT_PATH_HEARTBEAT_PERIOD * 16 == 224 seconds. While that gate holds it returns
# before doPingAndKeepalive is ever called, so ZT_PEER_PING_PERIOD is never even
# consulted for a root. Changing that constant alone measurably did nothing on
# hardware: still only the 8 startup HELLOs, still offline at 34s.
#
# Scale 1 puts upstream contact on a 14s cadence, comfortably inside the 30s activity
# timeout. ZT_PEER_PING_PERIOD then has to sit below that cadence so the contact that
# actually happens is a full HELLO rather than an ECHO the roots ignore.
#
# The two derived path constants are pinned to their original absolute values, so
# this changes contact cadence only and does not also shorten path expiration as a
# side effect.
#
# Verified on hardware: root_rx climbs +4 every 15s (one per root) instead of
# freezing, and the node holds ONLINE past 115s with no offline event.
#
# Note: write_text(newline='') is load-bearing on Windows. Without it Python's
# universal-newline translation rewrites the whole file LF->CRLF, which corrupts
# every line of the diff for what should be a two-line change.

SCALE_OLD = "int roleBasedTimerScale = (role == ZT_PEER_ROLE_LEAF) ? 2 : 16;"
SCALE_NEW = "int roleBasedTimerScale = (role == ZT_PEER_ROLE_LEAF) ? 2 : 1;"

patched_scale = False

for path in Path("libzt").rglob("Node.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue
    if SCALE_NEW in s:
        print(f"Upstream ping scale already patched: {path}")
        patched_scale = True
        break
    if SCALE_OLD in s:
        if s.count(SCALE_OLD) != 1:
            raise SystemExit(
                f"ERROR: expected one upstream ping scale in {path}, found {s.count(SCALE_OLD)}"
            )
        path.write_text(s.replace(SCALE_OLD, SCALE_NEW, 1), newline="")
        print(f"Upstream ping scale 16 -> 1 (224s -> 14s cadence): {path}")
        patched_scale = True
        break

if not patched_scale:
    raise SystemExit("ERROR: could not find _PingPeersThatNeedPing role-based timer scale in any Node.cpp")

# Keep the derived constants at the absolute values they had when
# ZT_PEER_PING_PERIOD was 60000, so only the HELLO cadence changes.
CONST_SUBS = [
    ("#define ZT_PEER_PING_PERIOD 60000", "#define ZT_PEER_PING_PERIOD 10000"),
    ("#define ZT_PEER_PATH_EXPIRATION ((ZT_PEER_PING_PERIOD * 4) + 3000)",
     "#define ZT_PEER_PATH_EXPIRATION (243000)"),
    ("#define ZT_PEER_EXPIRED_PATH_TRIAL_PERIOD (ZT_PEER_PING_PERIOD * 10)",
     "#define ZT_PEER_EXPIRED_PATH_TRIAL_PERIOD (600000)"),
]
PING_DONE = "#define ZT_PEER_PING_PERIOD 10000"

patched_consts = False

for path in Path("libzt").rglob("Constants.hpp"):
    try:
        s = path.read_text()
    except Exception:
        continue
    if "ZT_PEER_PING_PERIOD" not in s:
        continue

    applied = 0
    for old, new in CONST_SUBS:
        if old in s:
            if s.count(old) != 1:
                raise SystemExit(f"ERROR: expected one '{old}' in {path}, found {s.count(old)}")
            s = s.replace(old, new, 1)
            applied += 1

    if PING_DONE not in s:
        raise SystemExit(f"ERROR: ZT_PEER_PING_PERIOD in {path} is neither 60000 nor already 10000")

    if applied:
        path.write_text(s, newline="")
        print(f"ZT_PEER_PING_PERIOD -> 10000, derived path constants pinned ({applied} changed): {path}")
    else:
        print(f"Keepalive constants already patched: {path}")
    patched_consts = True
    break

if not patched_consts:
    raise SystemExit("ERROR: could not find a Constants.hpp defining ZT_PEER_PING_PERIOD")

print("Applied upstream keepalive fix: roots now get a full HELLO every ~14s, inside the 30s activity timeout.")
