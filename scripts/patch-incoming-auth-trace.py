from pathlib import Path
import re

# Diagnostic-only trace of the real UDP -> ZeroTier receive/auth boundary.
# Do not change protocol, timing, or socket behavior.

incoming = None
peer_cpp = None
for path in Path("libzt").rglob("IncomingPacket.cpp"):
    incoming = path
    break
for path in Path("libzt").rglob("Peer.cpp"):
    peer_cpp = path
    break

if incoming is None:
    raise SystemExit("ERROR: active libzt IncomingPacket.cpp not found")
if peer_cpp is None:
    raise SystemExit("ERROR: active libzt Peer.cpp not found")


def add_stdio(s, marker, path):
    if "#include <stdio.h>" in s:
        return s
    if marker not in s:
        raise SystemExit(f"ERROR: include anchor not found in {path}")
    return s.replace(marker, marker + "#include <stdio.h>\n", 1)

s = incoming.read_text()
s = add_stdio(s, '#include "Trace.hpp"\n', incoming)
if "[SWITCH-AUTH] REJECT invalid-MAC" not in s:
    pat = re.compile(
        r'if\s*\(\s*!\s*dearmor\(peer->key\(\),\s*peer->aesKeys\(\)\)\s*\)\s*\{'
        r'.*?RR->t->incomingPacketMessageAuthenticationFailure\(tPtr,_path,packetId\(\),sourceAddress,hops\(\),"invalid MAC"\);'
        r'.*?peer->recordIncomingInvalidPacket\(_path\);.*?return true;\s*\}', re.S)
    m = pat.search(s)
    if not m:
        raise SystemExit("ERROR: current invalid-MAC/dearmor block not found")
    block = m.group(0)
    marker = 'RR->t->incomingPacketMessageAuthenticationFailure'
    inject = '''#ifdef __SWITCH__
\t\t\t\t\tstatic unsigned int switch_auth_bad = 0;
\t\t\t\t\tconst unsigned int bad_n = __sync_fetch_and_add(&switch_auth_bad, 1);
\t\t\t\t\tif (bad_n < 100) {
\t\t\t\t\t\tfprintf(stderr, "[SWITCH-AUTH] REJECT invalid-MAC src=%llx verb=%u packet=%llx\\n",
\t\t\t\t\t\t        (unsigned long long)sourceAddress.toInt(),
\t\t\t\t\t\t        (unsigned int)verb(),
\t\t\t\t\t\t        (unsigned long long)packetId());
\t\t\t\t\t}
#endif
\t\t\t\t\t'''
    s = s[:m.start()] + block.replace(marker, inject + marker, 1) + s[m.end():]
incoming.write_text(s)

s = peer_cpp.read_text()
s = add_stdio(s, '#include "Metrics.hpp"\n', peer_cpp)
if "[SWITCH-AUTH] PEER-RECEIVED" not in s:
    anchor = '''const int64_t now = RR->node->now();\n\n\t_lastReceive = now;'''
    if anchor not in s:
        raise SystemExit("ERROR: Peer::received() lastReceive anchor not found")
    repl = '''const int64_t now = RR->node->now();

#ifdef __SWITCH__
\tstatic unsigned int switch_peer_received = 0;
\tconst unsigned int rx_n = __sync_fetch_and_add(&switch_peer_received, 1);
\tif (rx_n < 150) {
\t\tfprintf(stderr, "[SWITCH-AUTH] PEER-RECEIVED peer=%llx verb=%u packet=%llx upstream=%d hops=%u now=%lld\\n",
\t\t        (unsigned long long)_id.address().toInt(),
\t\t        (unsigned int)verb,
\t\t        (unsigned long long)packetId,
\t\t        RR->topology->isUpstream(_id) ? 1 : 0,
\t\t        hops,
\t\t        (long long)now);
\t}
#endif

\t_lastReceive = now;'''
    s = s.replace(anchor, repl, 1)
peer_cpp.write_text(s)
print(f"IncomingPacket trace applied: {incoming}")
print(f"Peer receive trace applied: {peer_cpp}")
