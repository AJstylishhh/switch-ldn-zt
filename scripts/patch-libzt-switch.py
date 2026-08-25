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

# Keep the header conditional for non-Switch builds.
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

# On Switch, skip the entire generic getifaddrs() fallback with a single
# preprocessor-condition edit. This avoids depending on fragile multiline markers.
start = '#if ! defined(__ANDROID__)\t // getifaddrs() freeifaddrs() not available on Android'
replacement_start = '#if ! defined(__ANDROID__) && ! defined(__SWITCH__)\t // getifaddrs() unavailable on Switch'
if start in bs:
    bs = bs.replace(start, replacement_start, 1)
else:
    # Tolerate whitespace differences in the upstream source.
    pattern = re.compile(r'^\s*#if\s*!\s*defined\(__ANDROID__\).*getifaddrs\(\).*$', re.MULTILINE)
    bs2, count = pattern.subn(replacement_start, bs, count=1)
    if count != 1:
        raise SystemExit('Binder.hpp getifaddrs guard line not found')
    bs = bs2

# Because Switch skips the block above, force the existing wildcard-address
# fallback path to be selected.
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

# Phy: hide the Unix-domain socket system header on Switch.
replace_once(
    'libzt/ext/ZeroTierOne/osdep/Phy.hpp',
    r'#include\s*<sys/un\.h>',
    '#ifndef __SWITCH__\n#include <sys/un.h>\n#endif',
)

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

# Switch does not ship Unix-domain-socket headers. Supply the small struct needed
# by generic source that names sockaddr_un.
sys_un = Path('libzt/ext/sys/un.h')
sys_un.parent.mkdir(parents=True, exist_ok=True)
sys_un.write_text(
    '#pragma once\n'
    '#include <sys/types.h>\n'
    '#include <sys/socket.h>\n'
    '#ifndef AF_UNIX\n'
    '#define AF_UNIX 1\n'
    '#endif\n'
    'struct sockaddr_un {\n'
    '    sa_family_t sun_family;\n'
    '    char sun_path[108];\n'
    '};\n'
)

print('Switch libzt source patching completed successfully.')
