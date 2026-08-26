from pathlib import Path
import re

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

    # Instrument every pthread_create statement, without assuming the name of
    # its return-code variable or the exact upstream formatting.
    counter = [0]
    def mark_create(match):
        counter[0] += 1
        return (match.group(0) +
                '\n#ifdef __SWITCH__\n'
                f'  printf("[SWITCH-DIAG] POST_PTHREAD_CREATE_{counter[0]}\\n");\n'
                '  fflush(stdout);\n'
                '#endif')
    text = re.sub(r'pthread_create\s*\([^;]*?\);', mark_create, text, flags=re.S)

    # Instrument direct introduce_thread assignments if present.
    def mark_intro(match):
        args = match.group(1)
        return ('#ifdef __SWITCH__\n'
                '  printf("[SWITCH-DIAG] BEFORE_INTRODUCE\\n");\n'
                '  fflush(stdout);\n'
                '#endif\n'
                f'  st = introduce_thread({args});\n'
                '#ifdef __SWITCH__\n'
                '  printf("[SWITCH-DIAG] AFTER_INTRODUCE\\n");\n'
                '  fflush(stdout);\n'
                '#endif')
    text, intro_count = re.subn(
        r'(?m)^\s*st\s*=\s*introduce_thread\s*\(([^;]*?)\)\s*;',
        mark_intro,
        text,
    )

    if '[SWITCH-DIAG] SYS_THREAD_NEW_RETURN' not in text:
        text = re.sub(
            r'(?m)^\s*return\s+st\s*;',
            '  #ifdef __SWITCH__\n  printf("[SWITCH-DIAG] SYS_THREAD_NEW_RETURN\\n"); fflush(stdout);\n  #endif\n  return st;',
            text,
            count=1,
        )

    if text != original:
        path.write_text(text)
        print(f'Instrumented {counter[0]} pthread_create site(s), {intro_count} introduce_thread call(s): {path}')

print('Switch diagnostics remain 3 seconds; broad post-pthread instrumentation complete.')
