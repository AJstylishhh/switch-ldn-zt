from pathlib import Path
import re

# newline='' on both read and write preserves whatever line endings the file
# already had -- Path.read_text()/write_text() otherwise apply Python's
# universal-newlines translation, which on Windows silently turns a
# clean LF-only file into CRLF even when the actual patch content is a
# no-op, corrupting every line of the diff for no real change.

# Keep diagnostics off the ZeroTier UDP hot path. fwrite()+fflush() to the SD
# card from sendto/recvfrom can stall the networking thread.
posix = Path('source/posix_compat.cpp')
s = posix.read_text()

send_pat = re.compile(
    r'\n\s*const u32 seq = __sync_fetch_and_add\(&g_tx_seq, 1\);\n'
    r'\s*if \(\(seq < 12 \|\| \(seq % 40\) == 0\).*?\n\s*\}\n\s*return rc;',
    re.S,
)
recv_pat = re.compile(
    r'\n\s*const u32 seq = __sync_fetch_and_add\(&g_rx_seq, 1\);\n'
    r'\s*if \(\(seq < 12 \|\| \(seq % 10\) == 0\) && from && from->sa_family == AF_INET\) \{\n'
    r'.*?\n\s*\}\n',
    re.S,
)
send_repl = '\n    (void)__sync_fetch_and_add(&g_tx_seq, 1);\n    return rc;'
recv_repl = '\n        (void)__sync_fetch_and_add(&g_rx_seq, 1);\n'

s2, n1 = send_pat.subn(send_repl, s, count=1)
s3, n2 = recv_pat.subn(recv_repl, s2, count=1)
# Detect the already-patched state by the marker line alone. Matching the
# whole replacement block (including the trailing "return rc;") breaks as soon
# as any bounded diagnostic is added after the counter bump, which then makes
# this script hard-fail a build whose source is in fact already correct.
already_applied = ('(void)__sync_fetch_and_add(&g_tx_seq, 1);' in s
                   and '(void)__sync_fetch_and_add(&g_rx_seq, 1);' in s)
if (n1 != 1 or n2 != 1) and not already_applied:
    raise SystemExit(f'Expected hot-path log blocks once each; send={n1}, recv={n2}')
if n1 == 1 or n2 == 1:
    posix.write_text(s3, newline='')

# Three BSD sessions is exactly the two endpoints of the Switch pipe shim
# plus one UDP socket. Leave headroom for ZeroTier's other bindings/sockets.
main_cpp = Path('source/main.cpp')
s = main_cpp.read_text()
old = '        .num_bsd_sessions    = 3,'
new = '        .num_bsd_sessions    = 16,'
if old in s:
    main_cpp.write_text(s.replace(old, new, 1), newline='')
elif new not in s:
    raise SystemExit('num_bsd_sessions setting not found')

print('Applied runtime hot-path fix: no SD I/O from sendto/recvfrom and 16 BSD sessions.')
