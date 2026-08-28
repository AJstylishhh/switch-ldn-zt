from pathlib import Path
import re

# Keep the existing diagnostic timing without changing anything else in the app.
main_cpp = Path('source/main.cpp')
if main_cpp.exists():
    s = main_cpp.read_text()
    s = s.replace('5000000000ULL', '3000000000ULL')
    main_cpp.write_text(s)


def find_file(root, name, required=()):
    for p in Path(root).rglob(name):
        try:
            s = p.read_text()
        except Exception:
            continue
        if all(x in s for x in required):
            return p
    raise SystemExit(f'ERROR: could not find {name} containing {required}')

# ---------------------------------------------------------------------------
# lwIP Unix sys_arch: Switch must not enter the Unix thread registry mutex.
# Also instrument the exact sys_thread_new handoff so the runtime trace tells
# us whether the child or the parent is the one that stops progressing.
# ---------------------------------------------------------------------------
sys_arch = find_file('libzt', 'sys_arch.c', ('sys_thread_new', 'pthread_create'))
s = sys_arch.read_text()

sig = re.search(r'static\s+struct\s+sys_thread\s*\*\s*introduce_thread\s*\(\s*pthread_t\s+id\s*\)\s*\{', s)
if not sig:
    raise SystemExit(f'ERROR: introduce_thread() not found in {sys_arch}')

# Replace the whole helper, avoiding malloc and threads_mutex on Switch.
brace = s.find('{', sig.start())
depth = 0
end = None
for i in range(brace, len(s)):
    if s[i] == '{': depth += 1
    elif s[i] == '}':
        depth -= 1
        if depth == 0:
            end = i + 1
            break
if end is None:
    raise SystemExit('ERROR: could not parse introduce_thread()')

intro = r'''static struct sys_thread *
introduce_thread(pthread_t id)
{
#ifdef __SWITCH__
  static struct sys_thread switch_threads[32];
  static volatile unsigned int switch_thread_count = 0;
  unsigned int slot = __sync_fetch_and_add(&switch_thread_count, 1);
  if (slot >= 32) return NULL;
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
s = s[:sig.start()] + intro + s[end:]

# Add Switch console declarations if the file does not already have them.
if '#include <switch.h>' not in s:
    marker = '#include <pthread.h>'
    if marker in s:
        s = s.replace(marker, marker + '\n#ifdef __SWITCH__\n#include <stdio.h>\n#include <switch.h>\n#endif', 1)

# Locate the actual sys_thread_new definition and its body.
m = re.search(r'(sys_thread_t\s+sys_thread_new\s*\([^;{}]*\)\s*\{)', s)
if not m:
    raise SystemExit('ERROR: sys_thread_new() definition not found')
fn_start = m.end()

# Entry marker.
if '[SWITCH-DIAG] STN: ENTER' not in s:
    s = s[:fn_start] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] STN: ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + s[fn_start:]
    # Re-find function after insertion.
    m = re.search(r'(sys_thread_t\s+sys_thread_new\s*\([^;{}]*\)\s*\{)', s)
    fn_start = m.end()

# Find pthread_create only inside sys_thread_new, not the first occurrence in
# the entire file (the previous instrumentation made this ambiguous).
_pcm = re.search(r'pthread_create\s*\(\s*&tmp\s*,', s[fn_start:]); pos = (fn_start + _pcm.start()) if _pcm else -1
if pos < 0:
    raise SystemExit('ERROR: pthread_create() not found inside sys_thread_new()')
open_paren = s.find('(', pos)
d = 0
close_paren = None
for i in range(open_paren, len(s)):
    if s[i] == '(':
        d += 1
    elif s[i] == ')':
        d -= 1
        if d == 0:
            close_paren = i
            break
if close_paren is None:
    raise SystemExit('ERROR: unmatched pthread_create() in sys_thread_new()')
semi = s.find(';', close_paren)
if semi < 0:
    raise SystemExit('ERROR: pthread_create() has no terminator')

# Re-apply the explicit 256KB stack size fix, as one clean replacement of the
# WHOLE statement (including the "code = " assignment it sits inside - an
# earlier attempt only replaced the pthread_create(...) call itself and left
# the pre-existing "code = " dangling in front of the inserted #ifdef,
# producing invalid "code = #ifdef __SWITCH__" text). This lwIP Unix port
# ignores the caller-requested stack size (LWIP_UNUSED_ARG(stacksize)) and
# creates the pthread with a NULL attr, i.e. whatever the toolchain default
# happens to be. Verified on real hardware to be necessary: without it, the
# newly created thread stalls immediately after pthread_create() returns
# (proven by a probe at the very first line of thread_wrapper() never
# printing).
if '&switch_attr' not in s[pos:semi+1]:
    stmt_start = s.rfind('\n', 0, pos) + 1  # start of the line containing "code = pthread_create("
    original_stmt = s[stmt_start:semi+1]
    stack_fix = (
        '#ifdef __SWITCH__\n'
        '  pthread_attr_t switch_attr;\n'
        '  pthread_attr_init(&switch_attr);\n'
        '  pthread_attr_setstacksize(&switch_attr, 256 * 1024);\n'
        '  code = pthread_create(&tmp, &switch_attr, thread_wrapper, thread_data);\n'
        '  pthread_attr_destroy(&switch_attr);\n'
        '#else\n'
        + original_stmt + '\n'
        '#endif'
    )
    s = s[:stmt_start] + stack_fix + s[semi+1:]
    m = re.search(r'(sys_thread_t\s+sys_thread_new\s*\([^;{}]*\)\s*\{)', s)
    fn_start = m.end()
    _pcm = re.search(r'pthread_create\s*\(\s*&tmp\s*,', s[fn_start:])
    pos = (fn_start + _pcm.start()) if _pcm else -1
    close_paren = s.find(')', s.find('(', pos))
    semi = s.find(';', close_paren)

if '[SWITCH-DIAG] STN: AFTER_PTHREAD_CREATE' not in s:
    s = s[:semi+1] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] STN: AFTER_PTHREAD_CREATE\\n");\n  consoleUpdate(NULL);\n#endif' + s[semi+1:]

# Instrument the exact introduce_thread call/return. This is the critical
# boundary after pthread_create returns 0.
if '[SWITCH-DIAG] STN: BEFORE_INTRODUCE' not in s:
    # Find the if (0 == code) block after the pthread_create call.
    p = s.find('if (0 == code)', pos)
    if p < 0:
        raise SystemExit('ERROR: expected if (0 == code) block not found')
    call = s.find('st = introduce_thread(', p)
    if call < 0:
        raise SystemExit('ERROR: introduce_thread() call not found')
    s = s[:call] + '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] STN: BEFORE_INTRODUCE\\n");\n    consoleUpdate(NULL);\n#endif\n    ' + s[call:]
    # Re-find the call after insertion.
    call = s.find('st = introduce_thread(', p)
    close = s.find(');', call)
    if close < 0:
        raise SystemExit('ERROR: introduce_thread() call terminator not found')
    close += 2
    s = s[:close] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] STN: AFTER_INTRODUCE\\n");\n    consoleUpdate(NULL);\n#endif' + s[close:]

# Instrument the helper itself so a failure inside the Switch replacement is
# distinguishable from a failure returning to sys_thread_new.
if '[SWITCH-DIAG] INTRO: ENTER' not in s:
    marker = 'introduce_thread(pthread_t id)\n{'
    if marker not in s:
        raise SystemExit('ERROR: rewritten introduce_thread() marker not found')
    s = s.replace(marker, marker + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] INTRO: ENTER\\n");\n  consoleUpdate(NULL);\n#endif', 1)
    target = 'switch_threads[slot].pthread = id;'
    s = s.replace(target, target + '\n  printf("[SWITCH-DIAG] INTRO: SLOT_OK\\n");\n  consoleUpdate(NULL);', 1)

sys_arch.write_text(s)
print(f'Instrumented exact Switch sys_thread_new handoff: {sys_arch}')

# ---------------------------------------------------------------------------
# VirtualTap: bracket the three actual calls in the driver thread.
# ---------------------------------------------------------------------------
vtap = find_file('libzt', 'VirtualTap.cpp', ('zts_main_lwip_driver_loop',))
s = vtap.read_text()

m = re.search(r'(zts_main_lwip_driver_loop\s*\([^)]*\)\s*\{)', s)
if not m:
    raise SystemExit('ERROR: zts_main_lwip_driver_loop() definition not found')
if '[SWITCH-DIAG] DRIVER: ENTER' not in s:
    s = s[:m.end()] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] DRIVER: ENTER\\n");\n    consoleUpdate(NULL);\n#endif' + s[m.end():]


def wrap_first_call(src, fn_name, label):
    token = f'[SWITCH-DIAG] DRIVER: BEFORE_{label}'
    if token in src:
        return src
    start = src.find('zts_main_lwip_driver_loop')
    pos = src.find(fn_name, start)
    if pos < 0:
        raise SystemExit(f'ERROR: {fn_name} not found in driver')
    op = src.find('(', pos)
    depth = 0
    cp = None
    for i in range(op, len(src)):
        if src[i] == '(':
            depth += 1
        elif src[i] == ')':
            depth -= 1
            if depth == 0:
                cp = i
                break
    if cp is None:
        raise SystemExit(f'ERROR: unmatched {fn_name}()')
    semi = src.find(';', cp)
    if semi < 0:
        raise SystemExit(f'ERROR: no terminator after {fn_name}()')
    ls = src.rfind('\n', 0, pos) + 1
    indent = re.match(r'[ \t]*', src[ls:pos]).group(0)
    stmt = src[ls:semi+1]
    repl = ('#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] DRIVER: BEFORE_{label}\\n");\n' +
            indent + 'consoleUpdate(NULL);\n#endif\n' + stmt + '\n' +
            '#ifdef __SWITCH__\n' + indent + f'printf("[SWITCH-DIAG] DRIVER: AFTER_{label}\\n");\n' +
            indent + 'consoleUpdate(NULL);\n#endif')
    return src[:ls] + repl + src[semi+1:]

s = wrap_first_call(s, 'sys_sem_new', 'SEM_NEW')
s = wrap_first_call(s, 'tcpip_init', 'TCPIP_INIT')
s = wrap_first_call(s, 'sys_sem_wait', 'SEM_WAIT')
vtap.write_text(s)
print(f'Instrumented driver startup boundaries: {vtap}')

# ---------------------------------------------------------------------------
# tcpip.c: trace the worker itself and the init callback.
# ---------------------------------------------------------------------------
tcpip = find_file('libzt', 'tcpip.c', ('tcpip_thread', 'tcpip_init', 'sys_thread_new'))
s = tcpip.read_text()

if '#include <switch.h>' not in s:
    # Put Switch declarations after the normal includes. The source already
    # includes lwip headers, so this is safe for the Switch-only diagnostics.
    first = '#include "lwip/opt.h"'
    if first in s:
        s = s.replace(first, first + '\n#ifdef __SWITCH__\n#include <stdio.h>\n#include <switch.h>\n#endif', 1)

m = re.search(r'((?:static\s+)?void\s+tcpip_thread\s*\([^;{}]*\)\s*\{)', s)
if not m:
    raise SystemExit(f'ERROR: tcpip_thread() definition not found in {tcpip}')
if '[SWITCH-DIAG] TCPIP: THREAD_ENTER' not in s:
    s = s[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] TCPIP: THREAD_ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + s[m.end():]

m = re.search(r'((?:static\s+)?void\s+tcpip_init\s*\([^;{}]*\)\s*\{)', s)
if not m:
    raise SystemExit(f'ERROR: tcpip_init() definition not found in {tcpip}')
if '[SWITCH-DIAG] TCPIP: INIT_ENTER' not in s:
    s = s[:m.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] TCPIP: INIT_ENTER\\n");\n  consoleUpdate(NULL);\n#endif' + s[m.end():]

if '[SWITCH-DIAG] TCPIP: BEFORE_DONE' not in s:
    start = s.find('tcpip_thread(')
    p = s.find('if (tcpip_init_done != NULL)', start)
    if p < 0:
        raise SystemExit('ERROR: tcpip_init_done block not found')
    s = s[:p] + '#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] TCPIP: BEFORE_DONE\\n");\n    consoleUpdate(NULL);\n#endif\n    ' + s[p:]

if '[SWITCH-DIAG] TCPIP: AFTER_DONE' not in s:
    start = s.find('tcpip_thread(')
    p = s.find('tcpip_init_done(', start)
    if p < 0:
        raise SystemExit('ERROR: tcpip_init_done call not found')
    semi = s.find(';', p)
    if semi < 0:
        raise SystemExit('ERROR: tcpip_init_done call has no terminator')
    s = s[:semi+1] + '\n#ifdef __SWITCH__\n    printf("[SWITCH-DIAG] TCPIP: AFTER_DONE\\n");\n    consoleUpdate(NULL);\n#endif' + s[semi+1:]

tcpip.write_text(s)
print(f'Instrumented tcpip worker/init handshake: {tcpip}')
# Re-apply the thread_wrapper entry probe. This was the probe that most
# recently proved the child thread genuinely starts executing (its first
# printf succeeded) before the freeze moved deeper into tcpip_init/tcpip_thread.
# Keep it - it's still useful confirmation alongside the new deeper markers.
if '[SWITCH-DIAG] thread_wrapper: child thread alive' not in sys_arch.read_text():
    s2 = sys_arch.read_text()
    wm = re.search(r'(thread_wrapper\s*\(\s*void\s*\*\s*arg\s*\)\s*\{)', s2)
    if not wm:
        raise SystemExit('ERROR: could not locate thread_wrapper() for child-thread probe')
    s2 = s2[:wm.end()] + '\n#ifdef __SWITCH__\n  printf("[SWITCH-DIAG] thread_wrapper: child thread alive\\n");\n  consoleUpdate(NULL);\n#endif' + s2[wm.end():]
    sys_arch.write_text(s2)
    print(f'Re-added thread_wrapper child-thread-alive probe: {sys_arch}')

# ---------------------------------------------------------------------------
# Fix OSUtils::now() to use a monotonic clock on Switch.
#
# ZeroTier's entire internal scheduler (when to send the next keepalive to
# root servers, connection timeouts, etc.) is driven by OSUtils::now(), which
# on every non-Windows platform (including our Switch build) just calls
# gettimeofday() - real wall-clock time. The Switch, like any always-online
# device, does a background time sync shortly after getting network
# connectivity; if that sync corrects the clock at all while the app is
# running, every scheduled deadline computed as "now() + X" becomes wrong in
# one direction or the other. This is a strong candidate for why the node
# reliably goes offline ~30-something seconds in on completely different
# networks - the failure timing tracks "time since connectivity", not
# anything network-specific.
#
# Fix: capture a wall-clock baseline once, then advance purely from the
# hardware monotonic tick counter (cntpct_el0 via armGetSystemTick(), which
# cannot be adjusted by any background time-sync) for everything after that.
# ---------------------------------------------------------------------------
for path in Path('libzt').rglob('OSUtils.hpp'):
    try:
        text = path.read_text()
    except Exception:
        continue
    if 'switch_monotonic_now' in text:
        print('OSUtils::now() Switch monotonic patch already present, nothing to do.')
        break

    now_re = re.compile(
        r'static inline int64_t now\(\)\s*\{.*?\};',
        re.DOTALL,
    )
    m = now_re.search(text)
    if not m:
        raise SystemExit(
            'ERROR: could not locate OSUtils::now() to add the Switch monotonic-clock fix.'
        )

    new_now = '''static inline int64_t now()
\t{
#ifdef __SWITCH__
\t\tstatic int64_t switch_wallclock_baseline_ms = 0;
\t\tstatic u64 switch_tick_baseline = 0;
\t\tif (switch_tick_baseline == 0) {
\t\t\tstruct timeval tv0;
\t\t\tgettimeofday(&tv0,(struct timezone *)0);
\t\t\tswitch_wallclock_baseline_ms = (1000LL * (int64_t)tv0.tv_sec) + (int64_t)(tv0.tv_usec / 1000);
\t\t\tswitch_tick_baseline = armGetSystemTick();
\t\t}
\t\tconst u64 switch_monotonic_now = armGetSystemTick();
\t\tconst int64_t switch_elapsed_ms = (int64_t)(armTicksToNs(switch_monotonic_now - switch_tick_baseline) / 1000000ULL);
\t\treturn switch_wallclock_baseline_ms + switch_elapsed_ms;
#elif defined(__WINDOWS__)
\t\tFILETIME ft;
\t\tSYSTEMTIME st;
\t\tULARGE_INTEGER tmp;
\t\tGetSystemTime(&st);
\t\tSystemTimeToFileTime(&st,&ft);
\t\ttmp.LowPart = ft.dwLowDateTime;
\t\ttmp.HighPart = ft.dwHighDateTime;
\t\treturn (int64_t)( ((tmp.QuadPart - 116444736000000000LL) / 10000L) + st.wMilliseconds );
#else
\t\tstruct timeval tv;
\t\tgettimeofday(&tv,(struct timezone *)0);
\t\treturn ( (1000LL * (int64_t)tv.tv_sec) + (int64_t)(tv.tv_usec / 1000) );
#endif
\t};'''

    text = text[:m.start()] + new_now + text[m.end():]

    if '#ifdef __SWITCH__\n#include <switch.h>' not in text:
        include_anchor = text.find('#include')
        text = text[:include_anchor] + '#ifdef __SWITCH__\n#include <switch.h>\n#endif\n' + text[include_anchor:]

    path.write_text(text)
    print(f'Applied Switch monotonic-clock fix to OSUtils::now(): {path}')
    break

# ---------------------------------------------------------------------------
# Fix __BYTE_ORDER never being defined at all for __SWITCH__ builds.
#
# Constants.hpp only defines __BYTE_ORDER/__LITTLE_ENDIAN/__BIG_ENDIAN inside
# branches gated on __linux__, __APPLE__, __FreeBSD__/__OpenBSD__/__NetBSD__,
# or _WIN32/_WIN64 - none of which are defined for a Switch build. The one
# generic fallback that would have caught this (#ifndef __BYTE_ORDER /
# #include <endian.h>) was itself commented out by the very first Switch
# patch applied to this codebase (a blanket sed replacement that matched
# every occurrence of that include, not just the one it was aimed at).
#
# Net effect: __BYTE_ORDER is undefined throughout this entire build. In
# preprocessor #if checks an undefined macro evaluates to 0, so any
# "#if __BYTE_ORDER == __BIG_ENDIAN" check silently evaluates true (0 == 0) -
# meaning ZeroTier's protocol code believes it's running on a big-endian
# machine, when aarch64/Switch is little-endian. This would corrupt
# multi-byte field parsing in incoming packets without any visible error,
# which fits the observed symptom exactly: tx keeps climbing (sending
# doesn't depend on this), while genuinely-arriving replies
# (confirmed reaching NodeService) get silently rejected after that.
for path in Path('libzt').rglob('Constants.hpp'):
    try:
        text = path.read_text()
    except Exception:
        continue
    if '__SWITCH__ byte order fix' in text:
        print('Constants.hpp byte-order fix already present, nothing to do.')
        break
    if 'ZT_INLINE' not in text:
        continue  # not the right Constants.hpp

    anchor = '#ifndef ZT_INLINE\n#define ZT_INLINE inline\n#endif\n'
    if anchor not in text:
        raise SystemExit('ERROR: could not locate anchor point in Constants.hpp for byte-order fix')

    byte_order_fix = (
        anchor +
        '\n// __SWITCH__ byte order fix: none of the platform branches below match a\n'
        '// Switch build, and the generic <endian.h> fallback further down was\n'
        '// disabled by an earlier patch. Define it explicitly instead of letting it\n'
        '// silently stay undefined (which would evaluate as big-endian in #if checks).\n'
        '// aarch64 on Switch always runs little-endian.\n'
        '#ifdef __SWITCH__\n'
        '#ifndef __BYTE_ORDER\n'
        '#define __BIG_ENDIAN 4321\n'
        '#define __LITTLE_ENDIAN 1234\n'
        '#define __BYTE_ORDER __LITTLE_ENDIAN\n'
        '#endif\n'
        '#endif\n'
    )
    text = text.replace(anchor, byte_order_fix, 1)
    path.write_text(text)
    print(f'Applied explicit __SWITCH__ byte-order definition: {path}')
    break
