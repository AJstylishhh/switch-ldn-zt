from pathlib import Path
import re

# Keep the Switch app's diagnostics short enough to be practical while still
# preserving a visible pause at every checkpoint. This runs before the
# thread-registry patch so it is not skipped by early compatibility exits.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    main_text = main_cpp.read_text()
    main_text = main_text.replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(main_text)
    print('Switch diagnostics reduced to 3 seconds.')


def add_thread_runtime_diagnostics(text, path):
    """Instrument the exact gap after pthread_create() and introduce_thread()."""
    if '[SWITCH-DIAG] after pthread_create' in text:
        return text

    # The bootstrap already adds <switch.h> and the existing diagnostics.
    # Add two markers around the suspected blocking operation so the next NRO
    # tells us whether the hang is inside introduce_thread(), after it, or in
    # some later sys_thread_new bookkeeping.
    create_pat = re.compile(
        r'(code\s*=\s*pthread_create\s*\(.*?\);)',
        re.S,
    )
    match = create_pat.search(text)
    if match:
        insertion = (
            match.group(1)
            + '\n#ifdef __SWITCH__\n'
            + '  printf("[SWITCH-DIAG] after pthread_create; entering st/registry path\\n");\n'
            + '  consoleUpdate(NULL);\n'
            + '#endif'
        )
        text = text[:match.start()] + insertion + text[match.end():]

    # Instrument the common introduce_thread(tmp) assignment. Keep this
    # independent of whitespace so it survives upstream lwIP formatting.
    intro_pat = re.compile(r'(?m)^(\s*)(st\s*=\s*introduce_thread\s*\(\s*tmp\s*\)\s*;)\s*$')
    m = intro_pat.search(text)
    if m:
        indent = m.group(1)
        statement = m.group(2)
        replacement = (
            indent + '#ifdef __SWITCH__\n'
            + indent + 'printf("[SWITCH-DIAG] before introduce_thread(tmp)\\n");\n'
            + indent + 'consoleUpdate(NULL);\n'
            + indent + '#endif\n'
            + indent + statement + '\n'
            + indent + '#ifdef __SWITCH__\n'
            + indent + 'printf("[SWITCH-DIAG] after introduce_thread(tmp): %s\\n", st ? "non-null" : "NULL");\n'
            + indent + 'consoleUpdate(NULL);\n'
            + indent + '#endif'
        )
        text = text[:m.start()] + replacement + text[m.end():]

    return text


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
        text = text.replace(old, new, 1)
        text = add_thread_runtime_diagnostics(text, path)
        path.write_text(text)
        print(f'Patched Switch lwIP thread registry and runtime diagnostics: {path}')
        raise SystemExit(0)

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

        def wrap(m):
            indent = m.group(1)
            statement = m.group(0).strip()
            return indent + '#ifndef __SWITCH__\n' + indent + statement + '\n' + indent + '#endif'

        body2 = lock_pat.sub(wrap, body)
        body2 = unlock_pat.sub(wrap, body2)

        if body2 != body:
            text = text[:start] + body2 + text[end:]
            text = add_thread_runtime_diagnostics(text, path)
            path.write_text(text)
            print(f'Patched Switch lwIP thread registry and runtime diagnostics: {path}')
            raise SystemExit(0)

    print(f'No Switch thread-registry mutex found in {path}; no patch needed.')

raise SystemExit(0)
