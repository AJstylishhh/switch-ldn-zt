from pathlib import Path

main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)

for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

    original = text
    old_intro = '''static struct sys_thread *
introduce_thread(pthread_t id)
{
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
}'''
    new_intro = '''static struct sys_thread *
introduce_thread(pthread_t id)
{
  struct sys_thread *thread;

  thread = (struct sys_thread *)malloc(sizeof(struct sys_thread));

  if (thread != NULL) {
#ifdef __SWITCH__
    thread->next = NULL;
    thread->pthread = id;
#else
    pthread_mutex_lock(&threads_mutex);
    thread->next = threads;
    thread->pthread = id;
    threads = thread;
    pthread_mutex_unlock(&threads_mutex);
#endif
  }

  return thread;
}'''
    if old_intro in text:
        text = text.replace(old_intro, new_intro, 1)

    lines = text.splitlines()
    out = []
    create_count = 0
    for line in lines:
        out.append(line)
        if 'pthread_create(' in line and not line.lstrip().startswith('//'):
            create_count += 1
            out.extend([
                '#ifdef __SWITCH__',
                f'  printf("[SWITCH-DIAG] POST_PTHREAD_CREATE_{create_count}\\n");',
                '  fflush(stdout);',
                '#endif',
            ])
    text = '\n'.join(out) + ('\n' if text.endswith('\n') else '')

    if 'BEFORE_INTRODUCE' not in text and 'st = introduce_thread(tmp);' in text:
        text = text.replace(
            'st = introduce_thread(tmp);',
            '#ifdef __SWITCH__\n'
            '  printf("[SWITCH-DIAG] BEFORE_INTRODUCE\\n");\n'
            '  fflush(stdout);\n'
            '#endif\n'
            '  st = introduce_thread(tmp);\n'
            '#ifdef __SWITCH__\n'
            '  printf("[SWITCH-DIAG] AFTER_INTRODUCE\\n");\n'
            '  fflush(stdout);\n'
            '#endif',
            1,
        )

    if 'SYS_THREAD_NEW_RETURN' not in text and 'return st;' in text:
        text = text.replace(
            'return st;',
            '#ifdef __SWITCH__\n'
            '  printf("[SWITCH-DIAG] SYS_THREAD_NEW_RETURN\\n");\n'
            '  fflush(stdout);\n'
            '#endif\n'
            '  return st;',
            1,
        )

    if text != original:
        path.write_text(text)
        print(f'Patched {path}: {create_count} pthread_create marker(s).')

print('Switch diagnostics remain 3 seconds.')
