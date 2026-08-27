from pathlib import Path
import re

main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)

lwip_path = None
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception:
        continue
    if 'sys_thread_new' in text and 'pthread_create' in text:
        lwip_path = path
        break
if lwip_path is None:
    raise SystemExit('ERROR: no usable lwIP Unix sys_arch.c was found under libzt')

text = lwip_path.read_text()
if 'switch_thread_count' not in text:
    sig = re.search(r'static\s+struct\s+sys_thread\s*\*\s*introduce_thread\s*\(\s*pthread_t\s+id\s*\)\s*\{', text)
    if not sig:
        raise SystemExit(f'ERROR: introduce_thread() not found in {lwip_path}')
    brace = text.find('{', sig.start())
    depth = 0
    end = None
    for i in range(brace, len(text)):
        if text[i] == '{': depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise SystemExit(f'ERROR: could not parse introduce_thread() in {lwip_path}')
    new_intro = '''static struct sys_thread *
introduce_thread(pthread_t id)
{
#ifdef __SWITCH__
  static struct sys_thread switch_threads[32];
  static volatile unsigned int switch_thread_count = 0;
  unsigned int slot = __sync_fetch_and_add(&switch_thread_count, 1);
  if (slot >= 32) return NULL;
  switch_threads[slot].next = NULL;
  switch_threads[slot].pthread = id;
  return &switch_threads[slot];
#else
  struct sys_thread *thread;
  thread = (struct sys_thread *)malloc(sizeof(struct sys_thread));
  if (thread != NULL) {
    pthread_mutex_lock(&threads_mutex);
    thread->next = threads;
    thread->pthread = id;
    threads = thread;
    pthread_mutex_unlock(&threads_mutex);
  }
  return thread;
#endif
}'''
    text = text[:sig.start()] + new_intro + text[end:]

text = lwip_path.read_text()
if '[SWITCH-DIAG] sys_thread_new: ENTER' not in text:
    m = re.search(r'(sys_thread_new\s*\([^)]*\)\s*\{)', text)
    if not m:
        raise SystemExit(f'ERROR: sys_thread_new() signature not found in {lwip_path}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + text[m.end():]

if 'sys_thread_new: AFTER_PTHREAD_CREATE' not in text:
    start = text.find('pthread_create(')
    if start < 0:
        raise SystemExit(f'ERROR: pthread_create() not found in {lwip_path}')
    depth = 0
    semi = None
    for i in range(start, len(text)):
        ch = text[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ';' and depth == 0:
            semi = i
            break
    if semi is None:
        raise SystemExit(f'ERROR: pthread_create statement has no terminator in {lwip_path}')
    text = text[:semi+1] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: AFTER_PTHREAD_CREATE\\n");\n  consoleUpdate(NULL);\n#endif' + text[semi+1:]

lwip_path.write_text(text)

vtap = None
for candidate in Path('libzt').rglob('VirtualTap.cpp'):
    try:
        candidate_text = candidate.read_text()
    except Exception:
        continue
    if 'zts_main_lwip_driver_loop' in candidate_text:
        vtap = candidate
        break
if vtap is None:
    raise SystemExit('ERROR: VirtualTap.cpp with zts_main_lwip_driver_loop() was not found')

text = vtap.read_text()
if '[SWITCH-DIAG] driver: ENTER' not in text:
    m = re.search(r'(zts_main_lwip_driver_loop\s*\([^)]*\)\s*\{)', text)
    if not m:
        raise SystemExit(f'ERROR: zts_main_lwip_driver_loop() signature not found in {vtap}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: ENTER\\n");\n    consoleUpdate(NULL);\n#endif' + text[m.end():]

def wrap_call(text, function_name, label):
    if f'[SWITCH-DIAG] driver: BEFORE_{label}' in text:
        return text
    fn = text.find('zts_main_lwip_driver_loop')
    pos = text.find(function_name, fn)
    if pos < 0:
        print(f'WARNING: {function_name} not found in driver; skipping {label}')
        return text
    open_paren = text.find('(', pos)
    if open_paren < 0:
        print(f'WARNING: malformed {function_name}; skipping {label}')
        return text
    depth = 0
    close_paren = None
    for i in range(open_paren, len(text)):
        ch = text[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                close_paren = i
                break
    if close_paren is None:
        print(f'WARNING: unmatched {function_name}; skipping {label}')
        return text
    semi = text.find(';', close_paren)
    if semi < 0:
        print(f'WARNING: no terminator after {function_name}; skipping {label}')
        return text
    line_start = text.rfind('\n', 0, pos) + 1
    indent = re.match(r'[ \t]*', text[line_start:pos]).group(0)
    statement = text[line_start:semi+1]
    marker = (
        '#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] driver: BEFORE_{label}\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif\n' +
        statement + '\n' +
        '#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] driver: AFTER_{label}\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif'
    )
    return text[:line_start] + marker + text[semi+1:]

text = wrap_call(text, 'sys_sem_new', 'SEM_NEW')
text = wrap_call(text, 'tcpip_init', 'TCPIP_INIT')
text = wrap_call(text, 'sys_sem_wait', 'SEM_WAIT')
vtap.write_text(text)
print(f'Instrumented deep lwIP startup boundaries: {vtap}')

# Trace the actual lwIP TCP/IP worker and its initialization handshake.
tcpip_path = None
for candidate in Path('libzt').rglob('tcpip.c'):
    try:
        candidate_text = candidate.read_text()
    except Exception:
        continue
    if 'tcpip_thread' in candidate_text and 'tcpip_init' in candidate_text and 'sys_thread_new' in candidate_text:
        tcpip_path = candidate
        break
if tcpip_path is None:
    raise SystemExit('ERROR: lwIP tcpip.c with tcpip_thread/tcpip_init/sys_thread_new was not found')

text = tcpip_path.read_text()
if '[SWITCH-DIAG] tcpip_thread: ENTER' not in text:
    m = re.search(r'((?:static\s+)?(?:void)\s+tcpip_thread\s*\([^;{}]*\)\s*\{)', text)
    if not m:
        raise SystemExit(f'ERROR: tcpip_thread() definition not found in {tcpip_path}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] tcpip_thread: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + text[m.end():]

if '[SWITCH-DIAG] tcpip_init: ENTER' not in text:
    m = re.search(r'((?:static\s+)?(?:void)\s+tcpip_init\s*\([^;{}]*\)\s*\{)', text)
    if not m:
        raise SystemExit(f'ERROR: tcpip_init() definition not found in {tcpip_path}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] tcpip_init: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + text[m.end():]

# tcpip_thread() calls the init-done callback immediately after locking the core.
if '[SWITCH-DIAG] tcpip_thread: BEFORE_INIT_DONE' not in text:
    thread_start = text.find('tcpip_thread(')
    pos = text.find('if (tcpip_init_done != NULL)', thread_start)
    if pos < 0:
        raise SystemExit('ERROR: tcpip_init_done block not found in tcpip_thread()')
    injection = '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] tcpip_thread: BEFORE_INIT_DONE\\n");\n    consoleUpdate(NULL);\n#endif\n    '
    text = text[:pos] + injection + text[pos:]

if '[SWITCH-DIAG] tcpip_thread: AFTER_INIT_DONE' not in text:
    thread_start = text.find('tcpip_thread(')
    pos = text.find('tcpip_init_done(', thread_start)
    if pos < 0:
        raise SystemExit('ERROR: tcpip_init_done() call not found in tcpip_thread()')
    semi = text.find(';', pos)
    if semi < 0:
        raise SystemExit('ERROR: tcpip_init_done() call has no terminator')
    replacement = text[pos:semi+1] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] tcpip_thread: AFTER_INIT_DONE\\n");\n    consoleUpdate(NULL);\n#endif'
    text = text[:pos] + replacement + text[semi+1:]

# Find sys_thread_new() inside the tcpip_init() function by locating the
# function body first, then matching the complete call.
if '[SWITCH-DIAG] tcpip_init: BEFORE_THREAD_CREATE' not in text:
    init_sig = re.search(r'((?:static\s+)?(?:void)\s+tcpip_init\s*\([^;{}]*\)\s*\{)', text)
    if not init_sig:
        raise SystemExit(f'ERROR: tcpip_init() definition not found in {tcpip_path}')
    body_start = init_sig.end()
    pos = text.find('sys_thread_new(', body_start)
    if pos < 0:
        raise SystemExit('ERROR: sys_thread_new() call not found inside tcpip_init()')
    open_paren = text.find('(', pos)
    depth = 0
    close_paren = None
    for i in range(open_paren, len(text)):
        if text[i] == '(':
            depth += 1
        elif text[i] == ')':
            depth -= 1
            if depth == 0:
                close_paren = i
                break
    if close_paren is None:
        raise SystemExit('ERROR: unmatched sys_thread_new() call in tcpip_init()')
    semi = text.find(';', close_paren)
    if semi < 0:
        raise SystemExit('ERROR: sys_thread_new() call has no terminator in tcpip_init()')
    line_start = text.rfind('\n', body_start, pos) + 1
    indent = re.match(r'[ \t]*', text[line_start:pos]).group(0)
    statement = text[line_start:semi+1]
    replacement = (
        '#ifdef __SWITCH__\n' + indent + 'printf("[SWITCH-DIAG] tcpip_init: BEFORE_THREAD_CREATE\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif\n' + statement + '\n' +
        '#ifdef __SWITCH__\n' + indent + 'printf("[SWITCH-DIAG] tcpip_init: AFTER_THREAD_CREATE\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif'
    )
    text = text[:line_start] + replacement + text[semi+1:]

if '#include <stdio.h>' not in text:
    text = text.replace('#include "lwip/opt.h"', '#include "lwip/opt.h"\n#ifdef __SWITCH__\n#include <stdio.h>\n#include <switch.h>\n#endif', 1)

tcpip_path.write_text(text)
print(f'Instrumented lwIP tcpip thread/init handshake: {tcpip_path}')
