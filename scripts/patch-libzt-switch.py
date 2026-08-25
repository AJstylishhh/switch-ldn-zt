from pathlib import Path
import re


def replace_once(path, pattern, replacement, flags=0):
    p = Path(path)
    s = p.read_text()
    ns, count = re.subn(pattern, replacement, s, count=1, flags=flags)
    if count != 1:
        raise SystemExit(f"Expected one match in {path}, found {count}: {pattern}")
    p.write_text(ns)


# Constants: Switch uses the POSIX/UNIX-like ZeroTier code paths.
p = Path('libzt/ext/ZeroTierOne/node/Constants.hpp')
s = p.read_text()
block = '#ifdef __SWITCH__\n#ifndef __UNIX_LIKE__\n#define __UNIX_LIKE__\n#endif\n#endif\n\n'
if block not in s:
    marker = '#ifdef __APPLE__\n'
    if marker not in s:
        raise SystemExit('Constants.hpp insertion marker not found')
    s = s.replace(marker, block + marker, 1)
    p.write_text(s)


# Utils: Switch has strtok(), not POSIX strtok_r().
utils = Path('libzt/ext/ZeroTierOne/node/Utils.hpp')
s = utils.read_text()
pattern = re.compile(
    r'(?ms)^\s*static\s+inline\s+char\s*\*\s*stok\s*\(.*?\n\s*static\s+inline\s+unsigned\s+int\s+strToUInt\s*\(const\s+char\s*\*\s*s\)'
)
replacement = '''\n\tstatic inline char* stok(char* str, const char* delim, char** saveptr)\n\t{\n#ifdef __WINDOWS__\n\t\treturn strtok_s(str, delim, saveptr);\n#elif defined(__SWITCH__)\n\t\t(void)saveptr;\n\t\treturn strtok(str, delim);\n#else\n\t\treturn strtok_r(str, delim, saveptr);\n#endif\n\t}\n\n\tstatic inline unsigned int strToUInt(const char* s)'''
ns, count = pattern.subn(replacement, s, count=1)
if count != 1:
    raise SystemExit('Utils.hpp stok function not found')
utils.write_text(ns)


# Binder: Switch cannot enumerate host interfaces with Linux getifaddrs().
binder = Path('libzt/ext/ZeroTierOne/osdep/Binder.hpp')
bs = binder.read_text()

if '#ifndef __SWITCH__\n#include <ifaddrs.h>\n#endif' not in bs:
    bs2, count = re.subn(
        r'#include\s*<ifaddrs\.h>',
        '#ifndef __SWITCH__\n#include <ifaddrs.h>\n#endif',
        bs,
        count=1,
    )
    if count != 1:
        raise SystemExit('Binder.hpp ifaddrs include not found')
    bs = bs2

# The upstream fallback enumeration is not usable on Switch. Guard only its
# top-level preprocessor line; this avoids fragile multiline block matching.
replacement_start = '#if ! defined(__ANDROID__) && ! defined(__SWITCH__)\t // getifaddrs unavailable on Switch'
pattern = re.compile(r'^\s*#if\s*!\s*defined\(__ANDROID__\).*getifaddrs\(\).*$', re.MULTILINE)
bs2, count = pattern.subn(replacement_start, bs, count=1)
if count != 1:
    # If already patched, leave it alone. Otherwise fail clearly.
    if replacement_start not in bs:
        raise SystemExit('Binder.hpp getifaddrs guard line not found')
    bs2 = bs
bs = bs2

# Force the existing wildcard-address fallback on Switch.
if 'interfacesEnumerated = false;' not in bs:
    marker = 'bool interfacesEnumerated = true;'
    if marker not in bs:
        raise SystemExit('Binder.hpp interface enumeration marker not found')
    bs = bs.replace(
        marker,
        marker + '\n#ifdef __SWITCH__\n\t\tinterfacesEnumerated = false;\n#endif',
        1,
    )

binder.write_text(bs)


# Phy: the Switch runtime does not provide Unix-domain sockets. The generic Phy
# template still contains a few Unix-only helpers because __UNIX_LIKE__ is useful
# for other core code. Guard the system header and the cleanup that dereferences
# sockaddr_un so Switch builds do not require that type.
phy = Path('libzt/ext/ZeroTierOne/osdep/Phy.hpp')
ps = phy.read_text()

ps2, count = re.subn(
    r'#include\s*<sys/un\.h>',
    '#ifndef __SWITCH__\n#include <sys/un.h>\n#endif',
    ps,
    count=1,
)
if count != 1:
    # Already patched is fine.
    if '#ifndef __SWITCH__\n#include <sys/un.h>\n#endif' not in ps:
        raise SystemExit('Phy.hpp sys/un.h include not found')
    ps2 = ps
ps = ps2

# In close(), never touch sockaddr_un on Switch because Switch does not expose
# AF_UNIX/Unix-domain sockets. Keep the upstream behavior on normal Unix builds.
cleanup_pattern = re.compile(
    r'(?ms)^\s*#ifdef __UNIX_LIKE__\s*\n\s*if \(sws\.type == ZT_PHY_SOCKET_UNIX_LISTEN\)\s*\n\s*::unlink\(\(\(struct sockaddr_un \*\)\(\&\(sws\.saddr\)\)\)->sun_path\);\s*\n\s*#endif\s*// __UNIX_LIKE__'
)
cleanup_replacement = '''\n#ifdef __UNIX_LIKE__\n#if !defined(__SWITCH__)\n\t\tif (sws.type == ZT_PHY_SOCKET_UNIX_LISTEN)\n\t\t\t::unlink(((struct sockaddr_un*)(&(sws.saddr)))->sun_path);\n#endif\t // !__SWITCH__\n#endif\t // __UNIX_LIKE__'''
ps2, count = cleanup_pattern.subn(cleanup_replacement, ps, count=1)
if count != 1:
    if 'if (!defined(__SWITCH__))' in ps or 'if (sws.type == ZT_PHY_SOCKET_UNIX_LISTEN)' not in ps:
        raise SystemExit('Phy.hpp Unix-socket cleanup block not found')
ps = ps2
phy.write_text(ps)


# Utils.cpp: sys/uio.h is a desktop/Unix header and is not needed by the Switch
# build. Keep it for normal Unix builds.
utils_cpp = Path('libzt/ext/ZeroTierOne/node/Utils.cpp')
us = utils_cpp.read_text()
u2, count = re.subn(
    r'#include\s*<sys/uio\.h>',
    '#ifndef __SWITCH__\n#include <sys/uio.h>\n#endif',
    us,
    count=1,
)
if count != 1:
    if '#ifndef __SWITCH__\n#include <sys/uio.h>\n#endif' not in us:
        raise SystemExit('Utils.cpp sys/uio.h include not found')
    u2 = us
utils_cpp.write_text(u2)


# CMake: do not link desktop port mapper or NAT helper objects for Switch.
cm = Path('libzt/CMakeLists.txt')
cs = cm.read_text()
cs = cs.replace('${ZTO_SRC_DIR}/osdep/PortMapper.cpp', '', 1)
cs = cs.replace('$<TARGET_OBJECTS:natpmp_pic> $<TARGET_OBJECTS:miniupnpc_pic>', '', 1)
cs = cs.replace(
    'set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")',
    'if(NOT SWITCH)\n    set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")\nendif()',
    1,
)
cm.write_text(cs)


# lwIP's generic arch.h defines ssize_t as int when SSIZE_MAX is absent. devkitA64
# already provides ssize_t as long, so advertise SSIZE_MAX first.
cc = Path('libzt/ext/lwip-contrib/ports/unix/port/include/arch/cc.h')
ccs = cc.read_text()
compat = '#include <limits.h>\n#ifndef SSIZE_MAX\n#define SSIZE_MAX LONG_MAX\n#endif\n'
if compat not in ccs:
    marker = '#include <sys/time.h>'
    if marker in ccs:
        ccs = ccs.replace(marker, compat + marker, 1)
    else:
        ccs = compat + ccs
    cc.write_text(ccs)


# Prometheus-lite headers used by ZeroTier Metrics.cpp rely on transitive includes
# on desktop compilers; devkitA64 is stricter.
for rel in (
    'libzt/ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/core/include/prometheus/family.h',
    'libzt/ext/ZeroTierOne/ext/prometheus-cpp-lite-1.0/core/include/prometheus/registry.h',
):
    hp = Path(rel)
    hs = hp.read_text()
    if '#include <stdexcept>' not in hs:
        if hs.startswith('#pragma once\n'):
            hs = '#pragma once\n#include <stdexcept>\n' + hs[len('#pragma once\n'):]
        else:
            hs = '#include <stdexcept>\n' + hs
        hp.write_text(hs)


print('Switch libzt source patching completed successfully.')
