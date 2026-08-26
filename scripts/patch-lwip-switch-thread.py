from pathlib import Path
import re

# The Unix lwIP port keeps a global list of pthreads protected by a static
# pthread mutex. On Nintendo Switch, pthread_create() succeeds but the first
# registry lock can block indefinitely. The registry is only opaque bookkeeping
# for this Switch build, so do not take its Unix mutex on Switch.

candidates = list(Path('libzt').rglob('sys_arch.c'))

for path in candidates:
    text = path.read_text()
    if 'sys_thread_new(' not in text or 'pthread_create' not in text:
        continue

    # First handle the known upstream implementation directly.
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
        print(f'Patched Switch lwIP thread registry (known layout): {path}')
        raise SystemExit(0)

    # Upstream lwIP/libzt can change whitespace or the exact bookkeeping code.
    # Locate introduce_thread() by braces, then disable only mutex operations
    # inside that function on Switch. Do not touch unrelated lwIP mutexes.
    match = re.search(
        r'(?m)^\s*(?:static\s+)?struct\s+sys_thread\s*\*\s*introduce_thread\s*\([^)]*\)\s*\{',
        text,
    )
    if match:
        start = match.end() - 1
        depth = 0
        end = None
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end is None:
            raise SystemExit(f'Could not parse introduce_thread() braces in {path}')

        body = text[start:end]
        lock_pat = re.compile(r'(?m)^(\s*)pthread_mutex_lock\s*\(\s*&[A-Za-z0-9_]*threads[A-Za-z0-9_]*\s*\)\s*;\s*$')
        unlock_pat = re.compile(r'(?m)^(\s*)pthread_mutex_unlock\s*\(\s*&[A-Za-z0-9_]*threads[A-Za-z0-9_]*\s*\)\s*;\s*$')

        changed = False

        def wrap_lock(m):
            nonlocal changed
            changed = True
            indent = m.group(1)
            return indent + '#ifndef __SWITCH__\n' + indent + m.group(0).strip() + '\n' + indent + '#endif'

        def wrap_unlock(m):
            nonlocal changed
            changed = True
            indent = m.group(1)
            return indent + '#ifndef __SWITCH__\n' + indent + m.group(0).strip() + '\n' + indent + '#endif'

        body2 = lock_pat.sub(wrap_lock, body)
        body2 = unlock_pat.sub(wrap_unlock, body2)

        if changed:
            path.write_text(text[:start] + body2 + text[end:])
            print(f'Patched Switch lwIP thread registry (upstream layout): {path}')
            raise SystemExit(0)

    print(f'Found candidate sys_arch.c but no recognizable thread-registry mutex: {path}')

raise SystemExit('Could not locate lwIP sys_arch.c thread registry')
