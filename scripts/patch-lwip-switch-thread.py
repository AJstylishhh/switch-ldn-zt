from pathlib import Path
import re

main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)

# Keep the Switch thread-registry workaround. Do not infer the failure from
# pthread_create(): the child thread is demonstrably starting.
lwip_path = None
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue
    lwip_path = path
    if 'switch_thread_count' not in text:
        sig_re = re.compile(
            r'static\s+struct\s+sys_thread\s*\*\s*\r?\n'
            r'introduce_thread\s*\(\s*pthread_t\s+id\s*\)\s*\r?\n\s*\{'
        )
        m = sig_re.search(text)
        if not m:
            raise SystemExit(f'ERROR: introduce_thread() not found in {path}')
        brace = text.index('{', m.start())
        depth = 0
        end = -1
        for i in range(brace, len(text)):
            if text[i] == '{': depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end < 0:
            raise SystemExit(f'ERROR: could not parse introduce_thread() in {path}')
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
        text = text[:m.start()] + new_intro + text[end:]
        path.write_text(text)
        print(f'Applied Switch thread registry workaround: {path}')
    break

if lwip_path is None:
    raise SystemExit('ERROR: no usable lwIP Unix sys_arch.c was found under libzt')

# Reliable sys_thread_new lifecycle markers. Insert after the complete
# pthread_create statement so multiline calls remain valid C.
path = lwip_path
text = path.read_text()
if '[SWITCH-DIAG] sys_thread_new: ENTER' not in text:
    fn_re = re.compile(r'(sys_thread_new\s*\([^)]*\)\s*\{)')
    m = fn_re.search(text)
    if not m:
        raise SystemExit(f'ERROR: sys_thread_new() signature not found in {path}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + text[m.end():]

if 'sys_thread_new: AFTER_PTHREAD_CREATE' not in text:
    start = text.find('pthread_create(')
    if start < 0:
        raise SystemExit(f'ERROR: pthread_create() not found in {path}')
    semi = text.find(';', start)
    if semi < 0:
        raise SystemExit(f'ERROR: pthread_create statement has no terminating semicolon in {path}')
    insertion = '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: AFTER_PTHREAD_CREATE\\n");\n  consoleUpdate(NULL);\n#endif'
    text = text[:semi + 1] + insertion + text[semi + 1:]

if 'sys_thread_new: BEFORE_INTRODUCE' not in text:
    marker_re = re.compile(r'([ \t]*)st\s*=\s*introduce_thread\s*\(\s*tmp\s*\)\s*;')
    m = marker_re.search(text)
    if m:
        indent = m.group(1)
        replacement = (
            '#ifdef __SWITCH__\n' + indent + 'printf("[SWITCH-DIAG] sys_thread_new: BEFORE_INTRODUCE\\n");\n' +
            indent + 'consoleUpdate(NULL);\n' + '#endif\n' +
            m.group(0) + '\n' +
            '#ifdef __SWITCH__\n' + indent + 'printf("[SWITCH-DIAG] sys_thread_new: AFTER_INTRODUCE\\n");\n' +
            indent + 'consoleUpdate(NULL);\n' + '#endif'
        )
        text = text[:m.start()] + replacement + text[m.end():]

if 'sys_thread_new: RETURN' not in text:
    marker_re = re.compile(r'([ \t]*)return\s+st\s*;')
    m = marker_re.search(text)
    if m:
        indent = m.group(1)
        replacement = (
            '#ifdef __SWITCH__\n' + indent + 'printf("[SWITCH-DIAG] sys_thread_new: RETURN\\n");\n' +
            indent + 'consoleUpdate(NULL);\n' + '#endif\n' + m.group(0)
        )
        text = text[:m.start()] + replacement + text[m.end():]
path.write_text(text)

# Instrument the actual libzt driver thread. Match whitespace/indentation
# robustly because upstream formatting can change between libzt revisions.
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
    fn_re = re.compile(r'(zts_main_lwip_driver_loop\s*\([^)]*\)\s*\{)')
    m = fn_re.search(text)
    if not m:
        raise SystemExit(f'ERROR: zts_main_lwip_driver_loop() signature not found in {vtap}')
    text = text[:m.end()] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: ENTER\\n");\n    consoleUpdate(NULL);\n#endif' + text[m.end():]

# Use regexes instead of exact strings. This handles tabs, spaces and line
# wrapping while preserving the original statement itself.
def instrument_statement(text, pattern, label):
    if f'[SWITCH-DIAG] driver: {label}' in text:
        return text
    m = re.search(pattern, text)
    if not m:
        raise SystemExit(f'ERROR: expected driver statement not found in {vtap}: {label}')
    indent = re.match(r'[ \t]*', m.group(0)).group(0)
    statement = m.group(0)
    marker = (
        '#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] driver: BEFORE_{label}\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif\n' +
        statement + '\n' +
        '#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] driver: AFTER_{label}\\n");\n' +
        indent + 'consoleUpdate(NULL);\n' + '#endif'
    )
    return text[:m.start()] + marker + text[m.end():]

text = instrument_statement(text, r'(?m)^[ \t]*sys_sem_new\s*\(\s*&\s*sem\s*,\s*0\s*\)\s*;', 'SEM_NEW')
text = instrument_statement(text, r'(?m)^[ \t]*tcpip_init\s*\(\s*zts_tcpip_init_done\s*,\s*&\s*sem\s*\)\s*;', 'TCPIP_INIT')
text = instrument_statement(text, r'(?m)^[ \t]*sys_sem_wait\s*\(\s*&\s*sem\s*\)\s*;', 'SEM_WAIT')

vtap.write_text(text)
print(f'Instrumented deep lwIP startup boundaries: {vtap}')
