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
    lwip_path.write_text(text)

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

# Find a complete call statement by matching parentheses, without assuming
# one-line formatting or exact whitespace. Missing optional calls are warnings,
# not CI failures; the driver-entry marker is still valuable.
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
