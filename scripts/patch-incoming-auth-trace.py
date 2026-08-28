from pathlib import Path

# Diagnostic-only trace of the UDP -> ZeroTier authentication boundary.
# Do not change protocol, timing, or socket behavior.

for path in Path("libzt").rglob("IncomingPacket.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue

    if "[SWITCH-AUTH]" in s:
        print(f"IncomingPacket auth trace already present: {path}")
        break

    if '#include <stdio.h>' not in s:
        marker = '#include "Trace.hpp"\n'
        if marker in s:
            s = s.replace(marker, marker + '#include <stdio.h>\n', 1)
        else:
            marker = '#include <string.h>\n'
            if marker not in s:
                raise SystemExit(f"ERROR: include anchor not found in {path}")
            s = s.replace(marker, marker + '#include <stdio.h>\n', 1)

    # Current upstream ZeroTier has the invalid-MAC handling immediately after
    # dearmor(). Match the stable API calls rather than an exact indentation or
    # whitespace block.
    old = '''if (! dearmor(peer->key(), peer->aesKeys(), RR->identity)) {
\t\t\t\t\tRR->t->incomingPacketMessageAuthenticationFailure(tPtr, _path, packetId(), sourceAddress, hops(), "invalid MAC");
\t\t\t\t\tpeer->recordIncomingInvalidPacket(_path);
\t\t\t\t\treturn true;
\t\t\t\t}'''
    new = '''if (! dearmor(peer->key(), peer->aesKeys(), RR->identity)) {
#ifdef __SWITCH__
\t\t\t\t\tstatic unsigned int switch_auth_bad = 0;
\t\t\t\t\tconst unsigned int bad_n = __sync_fetch_and_add(&switch_auth_bad, 1);
\t\t\t\t\tif (bad_n < 50) {
\t\t\t\t\t\tfprintf(stderr, "[SWITCH-AUTH] REJECT invalid-MAC src=%llx verb=%u packet=%llx\\n",
\t\t\t\t\t\t        (unsigned long long)sourceAddress.toInt(),
\t\t\t\t\t\t        (unsigned int)verb(),
\t\t\t\t\t\t        (unsigned long long)packetId());
\t\t\t\t\t}
#endif
\t\t\t\t\tRR->t->incomingPacketMessageAuthenticationFailure(tPtr, _path, packetId(), sourceAddress, hops(), "invalid MAC");
\t\t\t\t\tpeer->recordIncomingInvalidPacket(_path);
\t\t\t\t\treturn true;
\t\t\t\t}'''
    if old not in s:
        # Be resilient to tabs/spaces and upstream formatting changes.
        import re
        pat = re.compile(
            r'if\s*\(\s*!\s*dearmor\(peer->key\(\),\s*peer->aesKeys\(\),\s*RR->identity\)\s*\)\s*\{'
            r'.*?'
            r'RR->t->incomingPacketMessageAuthenticationFailure\(tPtr,\s*_path,\s*packetId\(\),\s*sourceAddress,\s*hops\(\),\s*"invalid MAC"\);'
            r'.*?'
            r'peer->recordIncomingInvalidPacket\(_path\);'
            r'.*?return true;\s*\}', re.S)
        m = pat.search(s)
        if not m:
            raise SystemExit(f"ERROR: current invalid-MAC/dearmor block not found in {path}")
        block = m.group(0)
        marker = 'RR->t->incomingPacketMessageAuthenticationFailure'
        inject = '''#ifdef __SWITCH__
\t\t\t\t\tstatic unsigned int switch_auth_bad = 0;
\t\t\t\t\tconst unsigned int bad_n = __sync_fetch_and_add(&switch_auth_bad, 1);
\t\t\t\t\tif (bad_n < 50) {
\t\t\t\t\t\tfprintf(stderr, "[SWITCH-AUTH] REJECT invalid-MAC src=%llx verb=%u packet=%llx\\n",
\t\t\t\t\t\t        (unsigned long long)sourceAddress.toInt(),
\t\t\t\t\t\t        (unsigned int)verb(),
\t\t\t\t\t\t        (unsigned long long)packetId());
\t\t\t\t\t}
#endif
\t\t\t\t\t'''
        block = block.replace(marker, inject + marker, 1)
        s = s[:m.start()] + block + s[m.end():]
    else:
        s = s.replace(old, new, 1)

    # Capture the Peer lastReceive value before packet processing.
    anchor = '''const SharedPtr<Peer> peer(RR->topology->getPeer(tPtr, sourceAddress));
\t\tif (peer) {'''
    if anchor in s:
        repl = '''const SharedPtr<Peer> peer(RR->topology->getPeer(tPtr, sourceAddress));
\t\tif (peer) {
#ifdef __SWITCH__
\t\t\tconst int64_t switch_peer_last_receive_before = peer->lastReceive();
#endif'''
        s = s.replace(anchor, repl, 1)
    else:
        raise SystemExit(f"ERROR: peer lookup anchor not found in {path}")

    # Trace after a successfully authenticated packet reaches the verb handler.
    anchor = '''if (r) {
\t\t\t\tRR->node->statsLogVerb((unsigned int)v, (unsigned int)size());'''
    if anchor not in s:
        raise SystemExit(f"ERROR: successful decode anchor not found in {path}")
    repl = '''if (r) {
#ifdef __SWITCH__
\t\t\t\tstatic unsigned int switch_auth_ok = 0;
\t\t\t\tconst unsigned int ok_n = __sync_fetch_and_add(&switch_auth_ok, 1);
\t\t\t\tif (ok_n < 100) {
\t\t\t\t\tfprintf(stderr, "[SWITCH-AUTH] ACCEPT src=%llx verb=%u packet=%llx upstream=%d lastRx=%lld->%lld\\n",
\t\t\t\t\t        (unsigned long long)sourceAddress.toInt(),
\t\t\t\t\t        (unsigned int)v,
\t\t\t\t\t        (unsigned long long)packetId(),
\t\t\t\t\t        RR->topology->isUpstream(peer->identity()) ? 1 : 0,
\t\t\t\t\t        (long long)switch_peer_last_receive_before,
\t\t\t\t\t        (long long)peer->lastReceive());
\t\t\t\t}
#endif
\t\t\t\tRR->node->statsLogVerb((unsigned int)v, (unsigned int)size());'''
    s = s.replace(anchor, repl, 1)

    # Clear HELLOs don't use the encrypted peer path; trace their result.
    anchor = '''return _doHELLO(RR, tPtr, false);'''
    if anchor in s:
        repl = '''#ifdef __SWITCH__
\t\t\tconst bool switch_hello_result = _doHELLO(RR, tPtr, false);
\t\t\tfprintf(stderr, "[SWITCH-AUTH] CLEAR-HELLO src=%llx result=%d\\n",
\t\t\t        (unsigned long long)sourceAddress.toInt(), switch_hello_result ? 1 : 0);
\t\t\treturn switch_hello_result;
#else
\t\t\treturn _doHELLO(RR, tPtr, false);
#endif'''
        s = s.replace(anchor, repl, 1)

    path.write_text(s)
    print(f"IncomingPacket authentication trace applied: {path}")
    break
else:
    raise SystemExit("ERROR: active libzt IncomingPacket.cpp not found")
