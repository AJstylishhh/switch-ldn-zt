from pathlib import Path

# Keep all existing Switch diagnostics at 3 seconds instead of 5 seconds.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)
    print('Switch diagnostics set to 3 seconds.')

# The lwIP Unix port uses pthreads and a heap-allocated thread registry. On
# Switch, pthread_create() has already been proven to return 0, but execution
# then stalls before sys_thread_new() returns. Avoid the second malloc and the
# Unix registry entirely on Switch. libnx already owns the pthread lifecycle;
# lwIP only needs a non-null sys_thread_t here.
import re

# The lwIP Unix port uses pthreads and a heap-allocated thread registry. On
# Switch, pthread_create() has already been proven to return 0, but execution
# then stalls before sys_thread_new() returns. Avoid the second malloc and the
# Unix registry entirely on Switch. libnx already owns the pthread lifecycle;
# lwIP only needs a non-null sys_thread_t here.
#
# NOTE: an earlier version of this script matched the target function with an
# exact multi-line string literal. That failed silently against the real
# upstream source (there's a trailing space after "sys_thread *" on the
# signature line that isn't visible in an editor), so the "fix" was never
# actually applied to any build. This version locates the function by a
# whitespace-tolerant regex on its signature instead, then replaces the whole
# function body by brace-matching - robust to exact spacing/line-ending
# differences between lwIP-contrib revisions.
patched = False
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

    if '#ifdef __SWITCH__' in text and 'switch_thread_count' in text:
        print(f'Switch thread patch already present in {path}, nothing to do.')
        patched = True
        break

    sig_re = re.compile(
        r'static\s+struct\s+sys_thread\s*\*\s*\r?\n'
        r'introduce_thread\s*\(\s*pthread_t\s+id\s*\)\s*\r?\n'
        r'\s*\{'
    )
    m = sig_re.search(text)
    if not m:
        print(f'introduce_thread signature not found in {path} (regex miss).')
        continue

    brace_start = text.index('{', m.start())
    depth = 0
    fn_end = -1
    for i in range(brace_start, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                fn_end = i + 1
                break
    if fn_end < 0:
        print(f'Could not brace-match introduce_thread body in {path}.')
        continue

    new_intro = '''static struct sys_thread *
introduce_thread(pthread_t id)
{
#ifdef __SWITCH__
  /*
   * The Unix lwIP port maintains a pthread registry protected by a pthread
   * mutex and allocates a registry node after pthread_create(). On Horizon
   * this second heap/mutex operation is unnecessary: libnx already manages
   * the pthread object. More importantly, it can deadlock against startup
   * activity in the newly-created lwIP thread.
   *
   * Keep a small static pool solely to provide stable, non-null sys_thread_t
   * values. No Unix registry or heap allocation is used on Switch.
   */
  static struct sys_thread switch_threads[32];
  static volatile unsigned int switch_thread_count = 0;
  unsigned int slot = __sync_fetch_and_add(&switch_thread_count, 1);
  if (slot >= 32)
    return NULL;
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

    text = text[:m.start()] + new_intro + text[fn_end:]
    path.write_text(text)
    print(f'Applied Switch static thread-record pool (regex match): {path}')
    patched = True
    break

if not patched:
    raise SystemExit(
        'ERROR: Switch thread patch did NOT apply - introduce_thread() was not '
        'found via regex either. This means the build would have silently used '
        'the ORIGINAL malloc+mutex thread registration code, not the fix. '
        'Failing the build here on purpose so this cannot go unnoticed again.'
    )
