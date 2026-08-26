from pathlib import Path
import re

# Runtime diagnostics are kept short enough to be practical on hardware.
# main.cpp is checked out from this repository, so update it directly here.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    main_text = main_cpp.read_text()
    main_text = main_text.replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(main_text)
    print('Switch diagnostics: 3 seconds')

# The Unix lwIP port used by libzt has this general flow:
#   pthread_create() -> introduce_thread() -> return sys_thread_t
# The previous diagnostic only proved pthread_create() returned 0. Instrument
# every transition around the remaining path so the next Switch run identifies
# the exact statement that blocks.

for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue

    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

    original = text

    # Keep the existing Switch registry workaround, but only for the actual
    # upstream introduce_thread implementation that contains threads_mutex.
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
        print(f'Applied Switch thread-registry workaround: {path}')

    # Add exact checkpoints to sys_thread_new(). This deliberately uses the
    # known upstream structure instead of guessing line numbers.
    if '[SWITCH-DIAG] sys_thread_new: after pthread_create' not in text:
        pthread_marker = '''  if (0 == code) {
    st = introduce_thread(tmp);
  }'''
        pthread_replacement = '''  if (0 == code) {
#ifdef __SWITCH__
    printf("[SWITCH-DIAG] sys_thread_new: before introduce_thread\\n");
    fflush(stdout);
#endif
    st = introduce_thread(tmp);
#ifdef __SWITCH__
    printf("[SWITCH-DIAG] sys_thread_new: after introduce_thread st=%s\\n", st ? "non-null" : "NULL");
    fflush(stdout);
#endif
  }'''
        if pthread_marker in text:
            text = text.replace(pthread_marker, pthread_replacement, 1)
        else:
            print(f'WARNING: expected introduce_thread call pattern not found: {path}')

    if '[SWITCH-DIAG] sys_thread_new: checking st' not in text:
        check_marker = '''  if (NULL == st) {
'''
        check_replacement = '''#ifdef __SWITCH__
  printf("[SWITCH-DIAG] sys_thread_new: checking st after registry\\n");
  fflush(stdout);
#endif
  if (NULL == st) {
'''
        if check_marker in text:
            text = text.replace(check_marker, check_replacement, 1)

    # Put a checkpoint immediately after pthread_create's call. This is the
    # boundary that the previous NRO reached successfully.
    if '[SWITCH-DIAG] sys_thread_new: pthread_create completed' not in text:
        # The upstream call is multiline; anchor on its closing line followed
        # by the if block, preserving whichever callback form is in this port.
        pattern = re.compile(r'(\n\s*thread_data\);\n)(\s*\n\s*if \(0 == code\) \{)')
        match = pattern.search(text)
        if match:
            replacement = (
                match.group(1)
                + '#ifdef __SWITCH__\n'
                + '  printf("[SWITCH-DIAG] sys_thread_new: pthread_create completed code=%d\\n", code);\n'
                + '  fflush(stdout);\n'
                + '#endif\n'
                + match.group(2)
            )
            text = text[:match.start()] + replacement + text[match.end():]
        else:
            # Fallback: inject before the first successful-code block.
            fallback = re.search(r'(?m)^\s*if \(0 == code\) \{', text)
            if fallback:
                indent = re.match(r'\s*', fallback.group(0)).group(0)
                replacement = (
                    '#ifdef __SWITCH__\n'
                    + indent + 'printf("[SWITCH-DIAG] sys_thread_new: pthread_create completed code=%d\\n", code);\n'
                    + indent + 'fflush(stdout);\n'
                    + '#endif\n'
                    + fallback.group(0)
                )
                text = text[:fallback.start()] + replacement + text[fallback.end():]

    if text != original:
        path.write_text(text)
        print(f'Instrumented sys_thread_new runtime path: {path}')

print('LWIP Switch patch/diagnostic pass complete.')
