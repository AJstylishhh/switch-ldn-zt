#include <switch.h>

#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>
#include <string.h>
#include <reent.h>
#include <stdio.h>
#include <sys/stat.h>
#include <pthread.h>

// ZeroTier's lwIP/Unix compatibility layer expects a POSIX errno object.
// libnx/newlib normally exposes errno through __errno(), while the lwIP Unix
// port used by libzt declares a plain external errno. Keep a dedicated errno
// object for that compatibility boundary.
#ifdef errno
#undef errno
#endif
extern "C" int errno = 0;

#define DIAG_BUF_SIZE 8192

static void log_write(const char* buf, size_t len);

static Mutex g_diag_mutex;
static char  g_diag_buf[DIAG_BUF_SIZE];
static size_t g_diag_len = 0;
static bool  g_diag_dropped = false;

extern "C" _ssize_t __real__write_r(struct _reent* r, int fd, const void* buf, size_t len);
extern "C" void __real_consoleUpdate(PrintConsole* console);

static inline bool on_main_thread()
{
    return threadGetCurHandle() == envGetMainThreadHandle();
}

extern "C" _ssize_t __wrap__write_r(struct _reent* r, int fd, const void* buf, size_t len)
{
    if (fd != STDOUT_FILENO && fd != STDERR_FILENO) {
        return __real__write_r(r, fd, buf, len);
    }

    log_write(static_cast<const char*>(buf), len);

    if (!on_main_thread()) {
        const char* p = static_cast<const char*>(buf);
        if (len >= 14 && memcmp(p, "[SWITCH-DIAG]", 13) == 0) {
            return static_cast<_ssize_t>(len);
        }
        mutexLock(&g_diag_mutex);
        for (size_t i = 0; i < len; i++) {
            if (g_diag_len < DIAG_BUF_SIZE) {
                g_diag_buf[g_diag_len++] = p[i];
            } else {
                g_diag_dropped = true;
                break;
            }
        }
        mutexUnlock(&g_diag_mutex);
        return static_cast<_ssize_t>(len);
    }
    return __real__write_r(r, fd, buf, len);
}

extern "C" void __wrap_consoleUpdate(PrintConsole* console)
{
    if (!on_main_thread()) return;

    static char drain[DIAG_BUF_SIZE];
    mutexLock(&g_diag_mutex);
    const size_t n = g_diag_len;
    const bool dropped = g_diag_dropped;
    if (n) memcpy(drain, g_diag_buf, n);
    g_diag_len = 0;
    g_diag_dropped = false;
    mutexUnlock(&g_diag_mutex);

    if (n) __real__write_r(_REENT, STDOUT_FILENO, drain, n);
    if (dropped) {
        static const char msg[] = "[diag buffer full - output dropped]\n";
        __real__write_r(_REENT, STDOUT_FILENO, msg, sizeof(msg) - 1);
    }

    __real_consoleUpdate(console);
}

static Mutex g_log_mutex;
static FILE* g_log = nullptr;

extern "C" FILE* __real_fopen(const char* path, const char* mode);

static void log_write(const char* buf, size_t len)
{
    mutexLock(&g_log_mutex);
    if (!g_log) g_log = __real_fopen("sdmc:/switch/zerotier-switch.log", "w");
    if (g_log) {
        fwrite(buf, 1, len, g_log);
        fflush(g_log);
    }
    mutexUnlock(&g_log_mutex);
}

extern "C" int __real_pthread_create(pthread_t* thread, const pthread_attr_t* attr,
                                     void* (*start)(void*), void* arg);

extern "C" int __wrap_pthread_create(pthread_t* thread, const pthread_attr_t* attr,
                                     void* (*start)(void*), void* arg)
{
    if (attr) return __real_pthread_create(thread, attr, start, arg);

    pthread_attr_t big;
    pthread_attr_init(&big);
    size_t original = 0;
    pthread_attr_getstacksize(&big, &original);
    pthread_attr_setstacksize(&big, 512 * 1024);
    const int rc = __real_pthread_create(thread, &big, start, arg);
    pthread_attr_destroy(&big);

    char line[128];
    const int n = snprintf(line, sizeof(line),
                           "[THREAD] default stack %u -> 524288, rc=%d\n",
                           (unsigned)original, rc);
    if (n > 0) log_write(line, static_cast<size_t>(n));
    return rc;
}

static volatile bool g_exiting = false;

extern "C" void zt_log(const char* msg)
{
    if (msg) log_write(msg, strlen(msg));
}

extern "C" void zt_begin_exit(void)
{
    g_exiting = true;
}

alignas(16) u8 __nx_exception_stack[0x2000];
u64 __nx_exception_stack_size = sizeof(__nx_exception_stack);

extern "C" void __libnx_exception_handler(ThreadExceptionDump* ctx)
{
    char line[256];
    int n = snprintf(line, sizeof(line),
                     "\n[FAULT] desc=0x%x esr=0x%08x pc=%016llx lr=%016llx sp=%016llx far=%016llx\n",
                     ctx->error_desc, ctx->esr,
                     (unsigned long long)ctx->pc.x,
                     (unsigned long long)ctx->lr.x,
                     (unsigned long long)ctx->sp.x,
                     (unsigned long long)ctx->far.x);
    if (n > 0) log_write(line, static_cast<size_t>(n));

    for (int i = 0; i < 29; i += 4) {
        n = snprintf(line, sizeof(line),
                     "[FAULT] x%-2d=%016llx x%-2d=%016llx x%-2d=%016llx x%-2d=%016llx\n",
                     i, (unsigned long long)ctx->cpu_gprs[i].x,
                     i + 1, (unsigned long long)(i + 1 < 29 ? ctx->cpu_gprs[i + 1].x : 0),
                     i + 2, (unsigned long long)(i + 2 < 29 ? ctx->cpu_gprs[i + 2].x : 0),
                     i + 3, (unsigned long long)(i + 3 < 29 ? ctx->cpu_gprs[i + 3].x : 0));
        if (n > 0) log_write(line, static_cast<size_t>(n));
    }

    if (g_exiting) svcExitProcess();
    for (;;) svcSleepThread(1000000000ULL);
}

extern "C" FILE* __wrap_fopen(const char* path, const char* mode)
{
    FILE* f = __real_fopen(path, mode);
    char line[224];
    const int n = snprintf(line, sizeof(line), "[FILE] fopen(%s, %s) -> %s\n",
                           path ? path : "(null)", mode ? mode : "?", f ? "ok" : "FAIL");
    if (n > 0) log_write(line, static_cast<size_t>(n));
    return f;
}

extern "C" int* __errno(void);

static volatile u32 g_sock_n = 0, g_sock_fail = 0;
static volatile u32 g_bind_n = 0, g_bind_fail = 0;
static volatile u32 g_tx_ok = 0, g_tx_fail = 0, g_tx_seq = 0;
static volatile u32 g_rx_ok = 0, g_rx_seq = 0;
static volatile u32 g_tx_root = 0, g_rx_root = 0;

extern "C" int __real_socket(int domain, int type, int protocol);
extern "C" int __real_bind(int fd, const struct sockaddr* addr, socklen_t len);
extern "C" ssize_t __real_sendto(int fd, const void* buf, size_t len, int flags,
                                 const struct sockaddr* to, socklen_t tolen);
extern "C" ssize_t __real_recvfrom(int fd, void* buf, size_t len, int flags,
                                   struct sockaddr* from, socklen_t* fromlen);

extern "C" int __wrap_socket(int domain, int type, int protocol)
{
    const int fd = __real_socket(domain, type, protocol);
    __sync_fetch_and_add(&g_sock_n, 1);
    char line[128];
    int n;
    if (fd < 0) {
        __sync_fetch_and_add(&g_sock_fail, 1);
        n = snprintf(line, sizeof(line), "[SOCK] socket(%d,%d,%d) FAILED errno=%d\n",
                     domain, type, protocol, *__errno());
    } else {
        n = snprintf(line, sizeof(line), "[SOCK] socket(%d,%d,%d) -> fd %d\n",
                     domain, type, protocol, fd);
    }
    if (n > 0) log_write(line, static_cast<size_t>(n));
    return fd;
}

extern "C" int __wrap_bind(int fd, const struct sockaddr* addr, socklen_t len)
{
    const int rc = __real_bind(fd, addr, len);
    __sync_fetch_and_add(&g_bind_n, 1);
    if (rc != 0) __sync_fetch_and_add(&g_bind_fail, 1);
    unsigned port = 0;
    char ip[INET6_ADDRSTRLEN];
    ip[0] = '\0';
    if (addr && addr->sa_family == AF_INET) {
        const struct sockaddr_in* s = reinterpret_cast<const struct sockaddr_in*>(addr);
        port = ntohs(s->sin_port);
        inet_ntop(AF_INET, &s->sin_addr, ip, sizeof(ip));
    } else if (addr && addr->sa_family == AF_INET6) {
        const struct sockaddr_in6* s = reinterpret_cast<const struct sockaddr_in6*>(addr);
        port = ntohs(s->sin6_port);
        inet_ntop(AF_INET6, &s->sin6_addr, ip, sizeof(ip));
    }
    char line[192];
    const int n = snprintf(line, sizeof(line), "[SOCK] bind(fd=%d fam=%d %s:%u) -> %d errno=%d\n",
                           fd, addr ? addr->sa_family : -1, ip, port, rc, rc ? *__errno() : 0);
    if (n > 0) log_write(line, static_cast<size_t>(n));
    return rc;
}

extern "C" ssize_t __wrap_sendto(int fd, const void* buf, size_t len, int flags,
                                 const struct sockaddr* to, socklen_t tolen)
{
    const ssize_t rc = __real_sendto(fd, buf, len, flags, to, tolen);
    const int saved = *__errno();
    if (rc < 0) __sync_fetch_and_add(&g_tx_fail, 1);
    else __sync_fetch_and_add(&g_tx_ok, 1);
    if (rc >= 0 && to && to->sa_family == AF_INET
        && ntohs(reinterpret_cast<const struct sockaddr_in*>(to)->sin_port) == 9993) {
        __sync_fetch_and_add(&g_tx_root, 1);
    }

    const u32 seq = __sync_fetch_and_add(&g_tx_seq, 1);
    if ((seq < 12 || (seq % 40) == 0) && to && to->sa_family == AF_INET) {
        const struct sockaddr_in* s = reinterpret_cast<const struct sockaddr_in*>(to);
        char ip[INET_ADDRSTRLEN];
        ip[0] = '\0';
        inet_ntop(AF_INET, &s->sin_addr, ip, sizeof(ip));
        char line[176];
        const int n = snprintf(line, sizeof(line), "[SOCK] sendto %s:%u len=%u -> %ld errno=%d\n",
                               ip, (unsigned)ntohs(s->sin_port), (unsigned)len,
                               (long)rc, rc < 0 ? saved : 0);
        if (n > 0) log_write(line, static_cast<size_t>(n));
    }
    return rc;
}

extern "C" ssize_t __wrap_recvfrom(int fd, void* buf, size_t len, int flags,
                                   struct sockaddr* from, socklen_t* fromlen)
{
    const ssize_t rc = __real_recvfrom(fd, buf, len, flags, from, fromlen);
    if (rc > 0) {
        __sync_fetch_and_add(&g_rx_ok, 1);
        if (from && from->sa_family == AF_INET
            && ntohs(reinterpret_cast<struct sockaddr_in*>(from)->sin_port) == 9993) {
            __sync_fetch_and_add(&g_rx_root, 1);
        }
        const u32 seq = __sync_fetch_and_add(&g_rx_seq, 1);
        if ((seq < 12 || (seq % 10) == 0) && from && from->sa_family == AF_INET) {
            const struct sockaddr_in* s = reinterpret_cast<const struct sockaddr_in*>(from);
            char ip[INET_ADDRSTRLEN];
            ip[0] = '\0';
            inet_ntop(AF_INET, &s->sin_addr, ip, sizeof(ip));
            char line[176];
            const int n = snprintf(line, sizeof(line), "[SOCK] recvfrom %s:%u -> %ld bytes\n",
                                   ip, (unsigned)ntohs(s->sin_port), (long)rc);
            if (n > 0) log_write(line, static_cast<size_t>(n));
        }
    }
    return rc;
}

static volatile u32 g_close_seq = 0;
static volatile u32 g_sockopt_fail = 0;

extern "C" int __real_close(int fd);

extern "C" int __wrap_close(int fd)
{
    const u32 seq = __sync_fetch_and_add(&g_close_seq, 1);
    if (seq < 24) {
        char line[96];
        const int n = snprintf(line, sizeof(line), "[SOCK] close(fd=%d)\n", fd);
        if (n > 0) log_write(line, static_cast<size_t>(n));
    }
    return __real_close(fd);
}

extern "C" int __real_setsockopt(int fd, int level, int name, const void* val, socklen_t len);

extern "C" int __wrap_setsockopt(int fd, int level, int name, const void* val, socklen_t len)
{
    const int rc = __real_setsockopt(fd, level, name, val, len);
    if (rc != 0) {
        const u32 seq = __sync_fetch_and_add(&g_sockopt_fail, 1);
        if (seq < 6) {
            char line[128];
            const int n = snprintf(line, sizeof(line),
                                   "[SOCK] setsockopt(fd=%d lvl=%d opt=%d) FAILED errno=%d\n",
                                   fd, level, name, *__errno());
            if (n > 0) log_write(line, static_cast<size_t>(n));
        }
    }
    return rc;
}

extern "C" void zt_report_state_files(void)
{
    static const char* names[] = { "identity.secret", "identity.public", "roots", "planet" };
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
        char path[160];
        snprintf(path, sizeof(path), "sdmc:/config/zerotier-switch/zt/%s", names[i]);
        struct stat st;
        char line[224];
        int n;
        if (stat(path, &st) == 0) {
            n = snprintf(line, sizeof(line), "[STATE] %s = %ld bytes\n", names[i], (long)st.st_size);
        } else {
            n = snprintf(line, sizeof(line), "[STATE] %s MISSING\n", names[i]);
        }
        if (n > 0) log_write(line, static_cast<size_t>(n));
    }
}

extern "C" void zt_net_stats(char* out, size_t n)
{
    snprintf(out, n, "tx=%u(-%u) rx=%u root_tx=%u root_rx=%u sock=%u(-%u)",
             g_tx_ok, g_tx_fail, g_rx_ok, g_tx_root, g_rx_root, g_sock_n, g_sock_fail);
}

extern "C" int __real_mkdir(const char* path, mode_t mode);

extern "C" int __wrap_mkdir(const char* path, mode_t mode)
{
    if (!path || !*path) return 0;

    const size_t n = strlen(path);
    if (path[n - 1] == ':') {
        printf("[MKDIR] %s -> 0 (device root)\n", path);
        return 0;
    }

    int rc = __real_mkdir(path, mode);
    if (rc != 0) {
        struct stat st;
        if (stat(path, &st) == 0 && S_ISDIR(st.st_mode)) rc = 0;
    }
    printf("[MKDIR] %s -> %d\n", path, rc);
    return rc;
}

static Mutex g_random_mutex;

static volatile u32 g_rand_seq = 0;

extern "C" void __wrap__ZN8ZeroTier5Utils15getSecureRandomEPvj(void* buf, unsigned int bytes)
{
    mutexLock(&g_random_mutex);
    randomGet(buf, static_cast<size_t>(bytes));
    mutexUnlock(&g_random_mutex);

    const u32 seq = __sync_fetch_and_add(&g_rand_seq, 1);
    if (seq < 10) {
        const unsigned char* b = static_cast<const unsigned char*>(buf);
        const unsigned show = bytes < 8 ? bytes : 8;
        char line[128];
        int off = snprintf(line, sizeof(line), "[RAND] #%u n=%u:", seq, bytes);
        for (unsigned i = 0; i < show && off > 0 && off < (int)sizeof(line) - 4; i++) {
            off += snprintf(line + off, sizeof(line) - off, " %02x", b[i]);
        }
        if (off > 0 && off < (int)sizeof(line) - 2) {
            line[off] = 0x0A;
            log_write(line, static_cast<size_t>(off) + 1);
        }
    }
}

extern "C" int pipe(int fds[2])
{
    if (!fds) {
        errno = 22;
        return -1;
    }

    fds[0] = -1;
    fds[1] = -1;

    const int a = socket(AF_INET, SOCK_DGRAM, 0);
    if (a < 0) return -1;
    const int b = socket(AF_INET, SOCK_DGRAM, 0);
    if (b < 0) {
        close(a);
        return -1;
    }

    struct sockaddr_in aa;
    struct sockaddr_in bb;
    memset(&aa, 0, sizeof(aa));
    aa.sin_family = AF_INET;
    aa.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    aa.sin_port = 0;
    bb = aa;

    bool ok = bind(a, reinterpret_cast<struct sockaddr*>(&aa), sizeof(aa)) == 0
           && bind(b, reinterpret_cast<struct sockaddr*>(&bb), sizeof(bb)) == 0;

    socklen_t al = sizeof(aa);
    socklen_t bl = sizeof(bb);
    if (ok) ok = getsockname(a, reinterpret_cast<struct sockaddr*>(&aa), &al) == 0;
    if (ok) ok = getsockname(b, reinterpret_cast<struct sockaddr*>(&bb), &bl) == 0;
    if (ok) ok = connect(a, reinterpret_cast<struct sockaddr*>(&bb), bl) == 0;
    if (ok) ok = connect(b, reinterpret_cast<struct sockaddr*>(&aa), al) == 0;

    if (!ok) {
        close(a);
        close(b);
        return -1;
    }

    fds[0] = a;
    fds[1] = b;
    return 0;
}

static __attribute__((noreturn)) void diag_halt(const char* what)
{
    if (g_exiting) svcExitProcess();
    char line[160];
    const int n = snprintf(line, sizeof(line),
                           "\n[TRAP] %s from %s thread - halted\n",
                           what, on_main_thread() ? "main" : "worker");
    if (n > 0) {
        log_write(line, static_cast<size_t>(n));
        __wrap__write_r(_REENT, STDOUT_FILENO, line, static_cast<size_t>(n));
    }
    for (;;) svcSleepThread(1000000000ULL);
}

extern "C" __attribute__((noreturn)) void __real_exit(int code);
extern "C" __attribute__((noreturn)) void __real_abort(void);

extern "C" __attribute__((noreturn)) void __wrap_exit(int code)
{
    if (on_main_thread()) __real_exit(code);
    char what[48];
    snprintf(what, sizeof(what), "exit(%d)", code);
    diag_halt(what);
}

extern "C" __attribute__((noreturn)) void __wrap_abort(void)
{
    diag_halt("abort()");
}

extern "C" __attribute__((noreturn)) void __real__exit(int code);

extern "C" __attribute__((noreturn)) void __wrap__exit(int code)
{
    if (on_main_thread()) __real__exit(code);
    char what[48];
    snprintf(what, sizeof(what), "_exit(%d)", code);
    diag_halt(what);
}
