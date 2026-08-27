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
patched = False
for path in Path('libzt').rglob('sys_arch.c'):
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue
    if 'sys_thread_new' not in text or 'pthread_create' not in text:
        continue

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

    if old_intro in text:
        path.write_text(text.replace(old_intro, new_intro, 1))
        print(f'Applied Switch static thread-record pool: {path}')
        patched = True
        break

    if '#ifdef __SWITCH__' in text and 'thread->next = NULL;' in text and 'threads_mutex' in text:
        fn_start = text.rfind('static struct sys_thread *', 0, text.find('#ifdef __SWITCH__', text.find('introduce_thread')))
        if fn_start >= 0:
            brace = text.find('{', fn_start)
            depth = 0
            fn_end = -1
            for i in range(brace, len(text)):
                if text[i] == '{': depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        fn_end = i + 1
                        break
            if fn_end > 0:
                text = text[:fn_start] + new_intro + text[fn_end:]
                path.write_text(text)
                print(f'Replaced Switch thread registry with static pool: {path}')
                patched = True
                break

if not patched:
    raise SystemExit(
        'ERROR: Switch thread patch did NOT apply - the expected sys_arch.c code '
        'pattern was not found. This means the build would have silently used the '
        'ORIGINAL malloc+mutex thread registration code, not the fix. Failing the '
        'build here on purpose so this cannot go unnoticed again.'
    )
