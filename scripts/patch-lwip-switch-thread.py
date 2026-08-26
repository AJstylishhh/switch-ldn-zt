from pathlib import Path

# The Unix lwIP port keeps a global list of pthreads protected by a static
# pthread mutex. On Nintendo Switch, the first lock can block immediately
# after pthread_create() succeeds. The registry is only opaque bookkeeping
# for this build, so keep the thread object without taking that mutex.

candidates = list(Path('libzt').rglob('sys_arch.c'))
for path in candidates:
    text = path.read_text()
    if 'sys_thread_new(' not in text or 'pthread_create' not in text:
        continue

    old = '''static struct sys_thread *
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

    new = '''static struct sys_thread *
introduce_thread(pthread_t id)
{
  struct sys_thread *thread;

  thread = (struct sys_thread *)malloc(sizeof(struct sys_thread));

  if (thread != NULL) {
#ifdef __SWITCH__
    // Switch: avoid the Unix lwIP thread registry mutex. The thread object is
    // only opaque bookkeeping for this port in our Switch build.
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

    if old in text:
        path.write_text(text.replace(old, new, 1))
        print(f'Patched Switch lwIP thread registry: {path}')
        raise SystemExit(0)

    if '#ifdef __SWITCH__\n    // Switch: avoid the Unix lwIP thread registry mutex.' in text:
        print(f'Switch lwIP thread registry already patched: {path}')
        raise SystemExit(0)

raise SystemExit('Could not locate lwIP sys_arch.c thread registry')
