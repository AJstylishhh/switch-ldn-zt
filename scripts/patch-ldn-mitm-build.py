#!/usr/bin/env python3
"""Finalize build/link changes for the ldn_mitm ZeroTier transport prototype."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LDN = ROOT / "ldn_mitm"
SRC = LDN / "ldn_mitm" / "source"

# The upstream ldn_mitm Makefile gets libstratosphere from its template. Add
# our already-built Switch libzt beside it without changing the upstream repo.
makefile = LDN / "ldn_mitm" / "Makefile"
s = makefile.read_text()
marker = 'CFLAGS\t\t+= $(VERSION_DEFINES)\nCXXFLAGS\t+= $(VERSION_DEFINES)'
replacement = '''CFLAGS\t\t+= $(VERSION_DEFINES)\nCXXFLAGS\t+= $(VERSION_DEFINES)\n\n# ZeroTier Switch transport supplied by the parent project.\nCXXFLAGS\t+= -I$(TOPDIR)/../../third_party/libzt/include\nLIBPATHS\t+= $(TOPDIR)/../../third_party/libzt/lib\nLIBS\t\t+= -lzt'''
if 'third_party/libzt/include' not in s:
    if marker not in s:
        raise SystemExit('ldn_mitm Makefile link anchor not found')
    s = s.replace(marker, replacement, 1)
    makefile.write_text(s)

# The first patch deliberately keeps the bridge API as plain int so it can be
# reused outside Stratosphere. Convert the libzt error to a Horizon Result at
# the service boundary instead of feeding a negative errno into R_TRY.
p = SRC / "ldn_icommunication.cpp"
s = p.read_text()
old = '        R_TRY(zt_bridge::start());'
new = '''        const int zt_start_rc = zt_bridge::start();\n        if (zt_start_rc != ZTS_ERR_OK) {\n            LogFormat("ZeroTier start failed: %d", zt_start_rc);\n            return MAKERESULT(0x10, 34);\n        }'''
if old in s:
    s = s.replace(old, new, 1)

old = '''        const Result zt_rc = zt_bridge::stop();\n        if (R_SUCCEEDED(rc) && R_FAILED(zt_rc)) rc = zt_rc;'''
new = '''        const int zt_rc = zt_bridge::stop();\n        if (R_SUCCEEDED(rc) && zt_rc != ZTS_ERR_OK) {\n            LogFormat("ZeroTier stop failed: %d", zt_rc);\n        }'''
if old in s:
    s = s.replace(old, new, 1)
p.write_text(s)

# Sanity checks: this build must really contain the ZT transport substitutions.
required = [
    SRC / "zt_bridge.cpp",
    SRC / "zt_bridge.hpp",
    SRC / "lan_protocol.cpp",
    SRC / "lan_discovery.cpp",
    SRC / "ldn_icommunication.cpp",
]
for path in required:
    if not path.exists():
        raise SystemExit(f'missing patched source: {path}')

for path, marker in [
    (SRC / "lan_protocol.cpp", "zts_bsd_poll"),
    (SRC / "lan_discovery.cpp", "zts_bsd_socket"),
    (SRC / "ldn_icommunication.cpp", "zt_bridge::ipv4_address"),
    (makefile, "third_party/libzt/include"),
]:
    if marker not in path.read_text():
        raise SystemExit(f'expected ZeroTier marker missing from {path}: {marker}')

print('ldn_mitm ZeroTier build/link patch verified')
