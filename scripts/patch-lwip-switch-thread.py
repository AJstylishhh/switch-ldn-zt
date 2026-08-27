from pathlib import Path
import re

main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)

lwip_patched = False
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

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
    else:
        print(f'Switch thread registry workaround already present: {path}')
    lwip_patched = True
    break

if not lwip_patched:
    raise SystemExit('ERROR: no usable lwIP Unix sys_arch.c was found under libzt')

# Instrument the actual libzt driver thread. The child pthread has already been
# proven to start on hardware; the next useful boundary is the first instruction
# of zts_main_lwip_driver_loop(), then tcpip_init(), then its initialization
# semaphore wait.
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
if '[SWITCH-DIAG] zts_main_lwip_driver_loop: entered' not in text:
    fn_re = re.compile(
        r'(static\s+void\s+zts_main_lwip_driver_loop\s*\(\s*void\s*\*\s*arg\s*\)\s*\{)'
    )
    m = fn_re.search(text)
    if not m:
        raise SystemExit(f'ERROR: zts_main_lwip_driver_loop() signature not found in {vtap}')
    text = text[:m.start()] + (
        m.group(1) + '\n'
        '#ifdef __SWITCH__\n'
        '    printf("[SWITCH-DIAG] zts_main_lwip_driver_loop: entered\\n");\n'
        '    consoleUpdate(NULL);\n'
        '#endif'
    ) + text[m.end():]

for old, new in [
    (
        '    tcpip_init(zts_tcpip_init_done, &sem);',
        '#ifdef __SWITCH__\n'
        '    printf("[SWITCH-DIAG] driver: before tcpip_init\\n");\n'
        '    consoleUpdate(NULL);\n'
        '#endif\n'
        '    tcpip_init(zts_tcpip_init_done, &sem);\n'
        '#ifdef __SWITCH__\n'
        '    printf("[SWITCH-DIAG] driver: after tcpip_init\\n");\n'
        '    consoleUpdate(NULL);\n'
        '#endif'
    ),
    (
        '    sys_sem_wait(&sem);',
        '#ifdef __SWITCH__\n'
        '    printf("[SWITCH-DIAG] driver: before sys_sem_wait\\n");\n'
        '    consoleUpdate(NULL);\n'
        '#endif\n'
        '    sys_sem_wait(&sem);\n'
        '#ifdef __SWITCH__\n'
        '    printf("[SWITCH-DIAG] driver: after sys_sem_wait\\n");\n'
        '    consoleUpdate(NULL);\n'
        '#endif'
    )
]:
    if old not in text:
        raise SystemExit(f'ERROR: expected driver statement not found in {vtap}: {old.strip()}')
    text = text.replace(old, new, 1)

vtap.write_text(text)
print(f'Instrumented Switch lwIP driver boundaries: {vtap}')
