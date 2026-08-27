from pathlib import Path
import re

main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)

# Keep the Switch thread-registry workaround, but do not try to infer the
# failure from pthread_create(). Hardware already proves that pthread_create
# succeeds. The useful boundary is what happens inside the driver/tcpip init.
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
    lwip_patched = True
    break

if not lwip_patched:
    raise SystemExit('ERROR: no usable lwIP Unix sys_arch.c was found under libzt')

# Instrument the exact sys_thread_new() lifecycle. Each pthread_create marker
# is deliberately inside sys_thread_new(), so a message from the tcpip thread
# can be distinguished from the driver thread's own creation.
for path in [lwip_patched and next(Path('libzt').rglob('sys_arch.c'))]:
    text = path.read_text()
    if 'SWITCH-DIAG] sys_thread_new: ENTER' not in text:
        # Find the function body without assuming its exact formatting.
        fn_re = re.compile(r'(sys_thread_new\s*\([^)]*\)\s*\{)')
        m = fn_re.search(text)
        if not m:
            raise SystemExit(f'ERROR: sys_thread_new() signature not found in {path}')
        text = text[:m.start()] + m.group(1) + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + text[m.end():]

    # Mark the complete pthread_create statement only after its terminating
    # semicolon. This avoids corrupting multi-line calls.
    if 'sys_thread_new: AFTER_PTHREAD_CREATE' not in text:
        start = text.find('pthread_create(')
        if start >= 0:
            semi = text.find(';', start)
            if semi < 0:
                raise SystemExit(f'ERROR: pthread_create statement has no terminating semicolon in {path}')
            insertion = '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: AFTER_PTHREAD_CREATE\\n");\n  consoleUpdate(NULL);\n#endif'
            text = text[:semi+1] + insertion + text[semi+1:]

    if 'sys_thread_new: BEFORE_INTRODUCE' not in text and 'introduce_thread(tmp)' in text:
        text = text.replace(
            'st = introduce_thread(tmp);',
            '#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: BEFORE_INTRODUCE\\n");\n  consoleUpdate(NULL);\n#endif\n  st = introduce_thread(tmp);\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: AFTER_INTRODUCE\\n");\n  consoleUpdate(NULL);\n#endif',
            1)

    if 'sys_thread_new: RETURN' not in text and 'return st;' in text:
        text = text.replace(
            'return st;',
            '#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] sys_thread_new: RETURN\\n");\n  consoleUpdate(NULL);\n#endif\n  return st;',
            1)
    path.write_text(text)

# Instrument the actual libzt driver thread. The critical discovery is that
# "driver loop entered" can be followed by a pthread_create message emitted
# by tcpip_init's child thread, so distinguish each stage explicitly.
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
    text = text[:m.start()] + m.group(1) + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: ENTER\\n");\n    consoleUpdate(NULL);\n#endif' + text[m.end():]

replacements = [
    ('sys_sem_new(&sem, 0);',
     '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: BEFORE_SEM_NEW\\n");\n    consoleUpdate(NULL);\n#endif\n    sys_sem_new(&sem, 0);\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: AFTER_SEM_NEW\\n");\n    consoleUpdate(NULL);\n#endif'),
    ('tcpip_init(zts_tcpip_init_done, &sem);',
     '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: BEFORE_TCPIP_INIT\\n");\n    consoleUpdate(NULL);\n#endif\n    tcpip_init(zts_tcpip_init_done, &sem);\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: AFTER_TCPIP_INIT\\n");\n    consoleUpdate(NULL);\n#endif'),
    ('sys_sem_wait(&sem);',
     '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: BEFORE_SEM_WAIT\\n");\n    consoleUpdate(NULL);\n#endif\n    sys_sem_wait(&sem);\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] driver: AFTER_SEM_WAIT\\n");\n    consoleUpdate(NULL);\n#endif')
]
for old, new in replacements:
    if old not in text:
        raise SystemExit(f'ERROR: expected driver statement not found in {vtap}: {old}')
    if new.split('\\n')[0] not in text:
        text = text.replace(old, new, 1)

vtap.write_text(text)
print(f'Instrumented deep lwIP startup boundaries: {vtap}')
