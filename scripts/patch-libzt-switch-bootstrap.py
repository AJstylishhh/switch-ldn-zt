from pathlib import Path
import re
import runpy

cm = Path('libzt/CMakeLists.txt')
s = cm.read_text()

# Upstream libzt has changed the formatting and exact contents of the ztcore
# source glob several times. Match the whole file(GLOB ztcoreSrcGlob ...)
# command instead of depending on a particular whitespace/newline layout.
pat = re.compile(
    r'file\s*\(\s*GLOB\s+ztcoreSrcGlob\b.*?\)',
    re.S,
)
replacement = '''file(GLOB ztcoreSrcGlob
    ${ZTO_SRC_DIR}/node/*.cpp
    ${ZTO_SRC_DIR}/osdep/OSUtils.cpp
    ${ZTO_SRC_DIR}/osdep/PortMapper.cpp)
if(SWITCH OR CMAKE_SYSTEM_NAME STREQUAL "Switch")
    list(REMOVE_ITEM ztcoreSrcGlob
        ${ZTO_SRC_DIR}/node/VirtualTap.cpp
        ${ZTO_SRC_DIR}/node/NodeService.cpp
        ${ZTO_SRC_DIR}/osdep/PortMapper.cpp)
endif()'''
s, n = pat.subn(replacement, s, count=1)
if n != 1 and 'list(REMOVE_ITEM ztcoreSrcGlob' not in s:
    raise SystemExit('Could not locate upstream ztcore source glob')

# Normalize the Unix lwIP port condition too, so the original patch script can
# safely skip its old exact-text replacement if it has already been applied.
if 'set(LWIP_PORT_DIR ${PROJ_DIR}/ext/lwip-contrib/ports/unix/port)' in s:
    s = re.sub(
        r'if\s*\(\s*UNIX\s*\)\s*\n\s*set\(LWIP_PORT_DIR\s+\$\{PROJ_DIR\}/ext/lwip-contrib/ports/unix/port\)\s*\n\s*endif\s*\(\s*\)',
        'if(UNIX OR SWITCH OR CMAKE_SYSTEM_NAME STREQUAL "Switch")\n    set(LWIP_PORT_DIR ${PROJ_DIR}/ext/lwip-contrib/ports/unix/port)\nendif()',
        s,
        count=1,
    )

# MiniUPnP is host-side NAT discovery and is not part of this Switch build.
s = s.replace(
    'set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")',
    'if(NOT SWITCH AND NOT CMAKE_SYSTEM_NAME STREQUAL "Switch")\n    set(ZT_FLAGS "${ZT_FLAGS} -DZT_USE_MINIUPNPC=1")\nendif()',
    1,
)
cm.write_text(s)

# Now run the established compatibility patch. Its remaining edits are kept
# in one place so this bootstrap only has to normalize upstream CMake layout.
runpy.run_path('scripts/patch-libzt-switch.py', run_name='__main__')
