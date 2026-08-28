from pathlib import Path
import re

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
    r'\s*if \(\(seq < 12 \|\| \(seq % 10\) == 0\).*?\n\s*\}\n\s*\}\n\s*return rc;',
    re.S,
)

send_repl = '\n    (void)__sync_fetch_and_add(&g_tx_seq, 1);\n    return rc;'
recv_repl = '\n        (void)__sync_fetch_and_add(&g_rx_seq, 1);\n    }\n    return rc;'

s2, n1 = send_pat.subn(send_repl, s, count=1)
s3, n2 = recv_pat.subn(recv_repl, s2, count=1)
if n1 != 1 or n2 != 1:
    raise SystemExit(f'Expected hot-path log blocks once each; send={n1}, recv={n2}')
posix.write_text(s3)

# Three BSD sessions is exactly the two endpoints of the Switch pipe shim
# plus one UDP socket. Leave headroom for ZeroTier's other bindings/sockets.
main_cpp = Path('source/main.cpp')
s = main_cpp.read_text()
old = '        .num_bsd_sessions    = 3,'
new = '        .num_bsd_sessions    = 16,'
if old in s:
    s = s.replace(old, new, 1)
elif new not in s:
    raise SystemExit('num_bsd_sessions setting not found')
main_cpp.write_text(s)

print('Applied runtime hot-path fix: no SD I/O from sendto/recvfrom and 16 BSD sessions.')
