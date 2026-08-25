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
# Match the function by its name and stop at strToUInt instead of depending on
# exact whitespace used by a particular upstream libzt revision.
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

# Binder: no Linux getifaddrs on Switch; use wildcard sockets.
replace_once(
    'libzt/ext/ZeroTierOne/osdep/Binder.hpp',
    r'#include <ifaddrs\.h>',
    '#ifndef __SWITCH__\n#include <ifaddrs.h>\n#endif',
)
p = Path('libzt/ext/ZeroTierOne/osdep/Binder.hpp')
s = p.read_text()
if 'interfacesEnumerated = false;' not in s:
    marker = 'bool interfacesEnumerated = true;'
    if marker not in s:
        raise SystemExit('Binder.hpp interface enumeration marker not found')
    s = s.replace(
        marker,
        marker + '\n#ifdef __SWITCH__\n\t\tinterfacesEnumerated = false;\n#endif',
        1,
    )
    p.write_text(s)

# Phy: Unix-domain sockets are not part of Switch libnx's socket API.
replace_once(
    'libzt/ext/ZeroTierOne/osdep/Phy.hpp',
    r'#include <sys/un\.h>',
    '#ifndef __SWITCH__\n#include <sys/un.h>\n#endif',
)

# CMake: don't build desktop port mapper or NAT helpers for Switch.
p = Path('libzt/CMakeLists.txt')
s = p.read_text()
s = s.replace('${ZTO_SRC_DIR}/osdep/PortMapper.cpp', '', 1)
s = s.replace('$<TARGET_OBJECTS:natpmp_pic> $<TARGET_OBJECTS:miniupnpc_pic>', '', 1)
s = s.replace(
    'set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")',
    'if(NOT SWITCH)\n    set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")\nendif()',
    1,
)
p.write_text(s)

print('Switch libzt source patching completed successfully.')
