from pathlib import Path

# Keep all existing Switch diagnostics at 3 seconds instead of 5 seconds.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    text = main_cpp.read_text().replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(text)
    print('Switch diagnostics set to 3 seconds.')

# Patch only the known lwIP Unix thread registry. Do NOT inject diagnostics
# around pthread_create(): the upstream call spans multiple source lines and
# inserting a statement after a matching line can corrupt its argument list.
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
        path.write_text(text.replace(old_intro, new_intro, 1))
        print(f'Patched Switch lwIP thread registry: {path}')
        patched = True
        break

    if '#ifdef __SWITCH__' in text and 'thread->next = NULL;' in text and 'threads_mutex' in text:
        print(f'Switch lwIP thread registry workaround already present: {path}')
        patched = True
        break

if not patched:
    print('No matching lwIP sys_arch.c thread-registry implementation found; no thread patch applied.')
