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

# Run the established compatibility patch. Its remaining edits are kept in
# one place so this bootstrap only has to normalize upstream CMake layout.
runpy.run_path('scripts/patch-libzt-switch.py', run_name='__main__')

# ---------------------------------------------------------------------------
# Runtime diagnostics for the Switch lwIP startup path.
# ---------------------------------------------------------------------------
# The NRO currently reaches zts_node_start() and then disappears immediately.
# The next call in libzt is zts_lwip_driver_init(), which invokes the Unix
# lwIP port's sys_thread_new(). Instrument both sides so a failed pthread_create
# is visible instead of being hidden by the port's unconditional abort().

virtual_candidates = list(Path('libzt').rglob('VirtualTap.cpp'))
virtual_path = None
for candidate in virtual_candidates:
    try:
        text = candidate.read_text()
    except Exception:
        continue
    if 'void zts_lwip_driver_init()' in text and 'sys_thread_new(' in text:
        virtual_path = candidate
        break

if virtual_path is not None:
    text = virtual_path.read_text()
    if '[SWITCH-DIAG] zts_lwip_driver_init entered' not in text:
        if '#ifdef __SWITCH__\n#include <switch.h>\n#endif' not in text:
            marker = '#include "VirtualTap.hpp"\n'
            if marker not in text:
                raise SystemExit(f'VirtualTap include marker not found in {virtual_path}')
            text = text.replace(marker, marker + '#ifdef __SWITCH__\n#include <switch.h>\n#endif\n', 1)

        old = '''void zts_lwip_driver_init()\n{\n    if (zts_lwip_is_up()) {'''
        new = '''void zts_lwip_driver_init()\n{\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] zts_lwip_driver_init entered\\n");\n    consoleUpdate(NULL);\n#endif\n    if (zts_lwip_is_up()) {'''
        if old not in text:
            raise SystemExit(f'zts_lwip_driver_init start not found in {virtual_path}')
        text = text.replace(old, new, 1)

        old_call = '''    sys_thread_new(\n        ZTS_LWIP_THREAD_NAME,\n        zts_main_lwip_driver_loop,\n        NULL,\n        DEFAULT_THREAD_STACKSIZE,\n        DEFAULT_THREAD_PRIO);'''
        new_call = '''#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] about to call sys_thread_new()\\n");\n    consoleUpdate(NULL);\n#endif\n    sys_thread_t lwip_thread = sys_thread_new(\n        ZTS_LWIP_THREAD_NAME,\n        zts_main_lwip_driver_loop,\n        NULL,\n        DEFAULT_THREAD_STACKSIZE,\n        DEFAULT_THREAD_PRIO);\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] sys_thread_new returned: %s\\n", lwip_thread ? "non-null" : "NULL");\n    consoleUpdate(NULL);\n#endif'''
        if old_call not in text:
            raise SystemExit(f'sys_thread_new call not found in {virtual_path}')
        text = text.replace(old_call, new_call, 1)
        virtual_path.write_text(text)
        print(f'Instrumented Switch lwIP driver: {virtual_path}')
else:
    print('Switch lwIP driver source not found; skipping VirtualTap instrumentation.')

sys_candidates = list(Path('libzt').rglob('sys_arch.c'))
sys_path = None
for candidate in sys_candidates:
    try:
        text = candidate.read_text()
    except Exception:
        continue
    if 'sys_thread_new(' in text and 'pthread_create' in text:
        sys_path = candidate
        break

if sys_path is not None:
    text = sys_path.read_text()
    if '[SWITCH-DIAG] sys_thread_new: entering' not in text:
        if '#ifdef __SWITCH__\n#include <switch.h>\n#endif' not in text:
            marker = '#include <errno.h>\n'
            if marker not in text:
                raise SystemExit(f'errno include marker not found in {sys_path}')
            text = text.replace(marker, marker + '#ifdef __SWITCH__\n#include <switch.h>\n#endif\n', 1)

        old = '''sys_thread_t\nsys_thread_new(const char *name, lwip_thread_fn function, void *arg, int stacksize, int prio)\n{\n  int code;'''
        new = '''sys_thread_t\nsys_thread_new(const char *name, lwip_thread_fn function, void *arg, int stacksize, int prio)\n{\n  int code;\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: entering\\n");\n  consoleUpdate(NULL);\n#endif'''
        if old not in text:
            raise SystemExit(f'sys_thread_new function start not found in {sys_path}')
        text = text.replace(old, new, 1)

        old = '''  code = pthread_create(&tmp,\n                        NULL, \n                        thread_wrapper, \n                        thread_data);\n  \n  if (0 == code) {'''
        new = '''#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: calling pthread_create()\\n");\n  consoleUpdate(NULL);\n#endif\n  code = pthread_create(&tmp,\n                        NULL,\n                        thread_wrapper,\n                        thread_data);\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] pthread_create returned code=%d\\n", code);\n  consoleUpdate(NULL);\n#endif\n  \n  if (0 == code) {'''
        if old not in text:
            raise SystemExit(f'pthread_create block not found in {sys_path}')
        text = text.replace(old, new, 1)

        old = '''  if (NULL == st) {\n    LWIP_DEBUGF(SYS_DEBUG, ("sys_thread_new: pthread_create %d, st = 0x%lx",\n                       code, (unsigned long)st));\n    abort();\n  }\n  return st;'''
        new = '''  if (NULL == st) {\n    LWIP_DEBUGF(SYS_DEBUG, ("sys_thread_new: pthread_create %d, st = 0x%lx",\n                       code, (unsigned long)st));\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] sys_thread_new failed: code=%d; returning NULL instead of abort()\\n", code);\n    consoleUpdate(NULL);\n    return NULL;\n#else\n    abort();\n#endif\n  }\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: thread registered successfully\\n");\n  consoleUpdate(NULL);\n#endif\n  return st;'''
        if old not in text:
            raise SystemExit(f'sys_thread_new abort block not found in {sys_path}')
        text = text.replace(old, new, 1)
        sys_path.write_text(text)
        print(f'Instrumented Switch lwIP sys_arch: {sys_path}')
else:
    print('lwIP sys_arch.c not found; skipping sys_thread_new instrumentation.')
