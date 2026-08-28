from pathlib import Path

# Trace the point where UDP packets become authenticated ZeroTier packets.
# This is intentionally diagnostic-only: no timing, socket, or protocol behavior
# is changed.

for path in Path("libzt").rglob("IncomingPacket.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue

    if "[SWITCH-AUTH]" in s:
        print(f"IncomingPacket auth trace already present: {path}")
        break

    if "#include <stdio.h>" not in s:
        marker = '#include "Trace.hpp"\n'
        if marker not in s:
            raise SystemExit(f"ERROR: include anchor not found in {path}")
        s = s.replace(marker, marker + '\n#include <stdio.h>\n', 1)

    # Log invalid MACs. This is the strongest indication that UDP packets arrive
    # but cannot be authenticated with the peer's current key.
    old = '''RR->t->incomingPacketMessageAuthenticationFailure(tPtr, _path, packetId(), sourceAddress, hops(), "invalid MAC");
					peer->recordIncomingInvalidPacket(_path);'''
    new = '''RR->t->incomingPacketMessageAuthenticationFailure(tPtr, _path, packetId(), sourceAddress, hops(), "invalid MAC");
#ifdef __SWITCH__
					static unsigned int switch_auth_bad = 0;
					const unsigned int bad_n = __sync_fetch_and_add(&switch_auth_bad, 1);
					if (bad_n < 50) {
						fprintf(stderr, "[SWITCH-AUTH] REJECT invalid-MAC src=%llx verb=%u packet=%llx\\n",
						        (unsigned long long)sourceAddress.toInt(),
						        (unsigned int)verb(),
						        (unsigned long long)packetId());
					}
#endif
					peer->recordIncomingInvalidPacket(_path);'''
    if old not in s:
        raise SystemExit(f"ERROR: invalid-MAC block not found in {path}")
    s = s.replace(old, new, 1)

    # Capture lastReceive before packet processing. If authentication succeeds,
    # the final trace compares it with the value after Peer::received().
    anchor = '''const SharedPtr<Peer> peer(RR->topology->getPeer(tPtr, sourceAddress));
		if (peer) {'''
    repl = '''const SharedPtr<Peer> peer(RR->topology->getPeer(tPtr, sourceAddress));
		if (peer) {
#ifdef __SWITCH__
			const int64_t switch_peer_last_receive_before = peer->lastReceive();
#endif'''
    if anchor not in s:
        raise SystemExit(f"ERROR: peer lookup anchor not found in {path}")
    s = s.replace(anchor, repl, 1)

    # Log successful authenticated packets after their verb handler. This tells
    # us whether the packet was accepted by ZeroTier and whether Peer::received()
    # advanced lastReceive. It also identifies whether the source is an upstream.
    anchor = '''if (r) {
				RR->node->statsLogVerb((unsigned int)v, (unsigned int)size());'''
    repl = '''if (r) {
#ifdef __SWITCH__
				static unsigned int switch_auth_ok = 0;
				const unsigned int ok_n = __sync_fetch_and_add(&switch_auth_ok, 1);
				if (ok_n < 100) {
					fprintf(stderr, "[SWITCH-AUTH] ACCEPT src=%llx verb=%u packet=%llx upstream=%d lastRx=%lld->%lld\\n",
					        (unsigned long long)sourceAddress.toInt(),
					        (unsigned int)v,
					        (unsigned long long)packetId(),
					        RR->topology->isUpstream(peer->identity()) ? 1 : 0,
					        (long long)switch_peer_last_receive_before,
					        (long long)peer->lastReceive());
				}
#endif
				RR->node->statsLogVerb((unsigned int)v, (unsigned int)size());'''
    if anchor not in s:
        raise SystemExit(f"ERROR: successful decode anchor not found in {path}")
    s = s.replace(anchor, repl, 1)

    # Log clear HELLOs too, since these bypass the encrypted peer path.
    anchor = '''return _doHELLO(RR, tPtr, false);'''
    repl = '''#ifdef __SWITCH__
				const bool switch_hello_result = _doHELLO(RR, tPtr, false);
				fprintf(stderr, "[SWITCH-AUTH] CLEAR-HELLO src=%llx result=%d\\n",
				        (unsigned long long)sourceAddress.toInt(), switch_hello_result ? 1 : 0);
				return switch_hello_result;
#else
				return _doHELLO(RR, tPtr, false);
#endif'''
    if anchor not in s:
        raise SystemExit(f"ERROR: clear HELLO return anchor not found in {path}")
    s = s.replace(anchor, repl, 1)

    path.write_text(s)
    print(f"IncomingPacket authentication trace applied: {path}")
    break
else:
    raise SystemExit("ERROR: active libzt IncomingPacket.cpp not found")
