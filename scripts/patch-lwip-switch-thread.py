from pathlib import Path
import re

# Keep all Switch diagnostics at 3 seconds.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    main_text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(main_text)

# Instrument the exact post-pthread_create path in the libzt/lwIP source.
# Do not assume introduce_thread() is the first operation after pthread_create:
# the current NRO proves pthread_create() returns 0 but the next checkpoint is
# never reached.
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

    original = text

    # Preserve the existing Switch workaround when this exact registry exists.
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

    # Add a checkpoint immediately after the actual pthread_create call.
    # Match the common libzt/lwIP call by its final argument, not a guessed
    # source line number.
    if '[SWITCH-DIAG] POST_CREATE' not in text:
        call = re.search(r'pthread_create\s*\([^;]*?\);', text, re.S)
        if call:
            end = call.end()
            text = (text[:end] +
                    '\n#ifdef __SWITCH__\n'
                    '  printf("[SWITCH-DIAG] POST_CREATE_A code=%d\\n", code);\n'
                    '  fflush(stdout);\n'
                    '  printf("[SWITCH-DIAG] POST_CREATE_B about to inspect code\\n");\n'
                    '  fflush(stdout);\n'
                    '#endif' + text[end:])

    # Replace the successful-code block wherever it occurs, adding checkpoints
    # immediately before and after introduce_thread().
    if '[SWITCH-DIAG] BEFORE_INTRODUCE' not in text:
        pat = re.compile(r'(?m)^(\s*)if\s*\(\s*0\s*==\s*code\s*\)\s*\{\s*\n\s*st\s*=\s*introduce_thread\s*\(\s*tmp\s*\)\s*;\s*\n\s*\}')
        m = pat.search(text)
        if m:
            indent = m.group(1)
            repl = (indent + 'if (0 == code) {\n'
                    + indent + '#ifdef __SWITCH__\n'
                    + indent + '  printf("[SWITCH-DIAG] BEFORE_INTRODUCE\\n"); fflush(stdout);\n'
                    + indent + '#endif\n'
                    + indent + '  st = introduce_thread(tmp);\n'
                    + indent + '#ifdef __SWITCH__\n'
                    + indent + '  printf("[SWITCH-DIAG] AFTER_INTRODUCE st=%s\\n", st ? "non-null" : "NULL"); fflush(stdout);\n'
                    + indent + '#endif\n'
                    + indent + '}')
            text = text[:m.start()] + repl + text[m.end():]
        else:
            print(f'WARNING: successful-code/introduce_thread pattern not found in {path}')

    # Put a final checkpoint immediately before the function's st NULL test.
    if '[SWITCH-DIAG] BEFORE_ST_CHECK' not in text:
        marker = re.search(r'(?m)^\s*if\s*\(\s*NULL\s*==\s*st\s*\)\s*\{', text)
        if marker:
            indent = re.match(r'\s*', marker.group(0)).group(0)
            text = (text[:marker.start()] +
                    indent + '#ifdef __SWITCH__\n'
                    + indent + 'printf("[SWITCH-DIAG] BEFORE_ST_CHECK\\n"); fflush(stdout);\n'
                    + indent + '#endif\n' + text[marker.start():])

    if text != original:
        path.write_text(text)
        print(f'Instrumented exact sys_thread_new post-create path: {path}')

print('Switch diagnostics remain 3 seconds; post-create instrumentation complete.')
