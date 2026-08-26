from pathlib import Path
import re
import runpy

cm = Path('libzt/CMakeLists.txt')
s = cm.read_text()

# The upstream libzt CMakeLists.txt has changed whitespace/layout over time.
# Normalize the source-list section before running the main compatibility patch.
pat = re.compile(
    r'file\(GLOB ztcoreSrcGlob.*?\n\s*\$\{ZTO_SRC_DIR\}/osdep/PortMapper\.cpp\)',
    re.S,
)
replacement = '''file(GLOB ztcoreSrcGlob ${ZTO_SRC_DIR}/node/*.cpp
         ${ZTO_SRC_DIR}/osdep/OSUtils.cpp ${ZTO_SRC_DIR}/osdep/PortMapper.cpp)
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
        r'if\(UNIX\)\n\s*set\(LWIP_PORT_DIR \$\{PROJ_DIR\}/ext/lwip-contrib/ports/unix/port\)\nendif\(\)',
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

# Now run the established compatibility patch. Its old exact CMake guard will
# see the normalized form and continue through the remaining portability edits.
runpy.run_path('scripts/patch-libzt-switch.py', run_name='__main__')
