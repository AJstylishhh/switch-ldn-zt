from pathlib import Path
import re

# The lwIP Unix port has changed its thread bookkeeping across versions.
# Some versions keep a pthread registry protected by threads_mutex; newer
# versions do not have that registry at all. The Switch build must patch the
# registry only when it actually exists — absence of it is NOT a build error.

candidates = list(Path('libzt').rglob('sys_arch.c'))
if not candidates:
    print('No lwIP sys_arch.c found; leaving thread registry unchanged.')
    raise SystemExit(0)

for path in candidates:
    try:
        text = path.read_text()
    except Exception as exc:
        print(f'Could not read {path}: {exc}')
        continue

    # Skip sys_arch.c implementations that do not use the Unix pthread thread
    # registry. They do not need this compatibility patch.
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

    # Other upstream versions may format introduce_thread() differently.
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

        def wrap(m):
            nonlocal changed
            changed = True
            indent = m.group(1)
            statement = m.group(0).strip()
            return indent + '#ifndef __SWITCH__\n' + indent + statement + '\n' + indent + '#endif'

        body2 = lock_pat.sub(wrap, body)
        body2 = unlock_pat.sub(wrap, body2)

        if changed:
            path.write_text(text[:start] + body2 + text[end:])
            print(f'Patched Switch lwIP thread registry (alternate layout): {path}')
            raise SystemExit(0)

    # This is a pthread-backed sys_arch.c but it has no introduce_thread()
    # registry. That is valid and requires no registry compatibility patch.
    print(f'No Switch thread-registry mutex found in {path}; no patch needed.')

print('lwIP thread-registry compatibility check: OK')
raise SystemExit(0)
