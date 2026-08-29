from pathlib import Path
p = Path('ldn_mitm/ldn_mitm/source/lan_discovery.cpp')
s = p.read_text()
needle = '#include <ZeroTierSockets.h>\n'
helper = '''#include <ZeroTierSockets.h>\n\nstatic struct zts_sockaddr_in ldn_to_zt_addr(const struct sockaddr_in *addr) {\n    struct zts_sockaddr_in out{};\n    out.sin_family = ZTS_AF_INET;\n    out.sin_port = addr ? addr->sin_port : 0;\n    out.sin_addr.s_addr = addr ? addr->sin_addr.s_addr : 0;\n    return out;\n}\n'''
if 'ldn_to_zt_addr' not in s:
    if needle not in s:
        raise SystemExit('ZeroTierSockets include not found')
    s = s.replace(needle, helper, 1)
s = s.replace('to_zt_addr(&addr)', 'ldn_to_zt_addr(&addr)')
p.write_text(s)
print('fixed discovery address helper')
