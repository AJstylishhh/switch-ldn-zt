#include <stratosphere.hpp>
#include <switch.h>

namespace ams {

namespace {
    constexpr size_t SysBHeapSize = 0x100000;
    void *g_heap = nullptr;
}

void Main() {
    // Phase 1 remains a pure AMS skeleton: no libzt, no zts_* and no LDN.
    // Match the working sysmodule startup shape: initialize a small heap,
    // initialize filesystem/services, then remain resident.
    if (g_heap == nullptr) {
        g_heap = std::malloc(SysBHeapSize);
        if (g_heap == nullptr) {
            svcSleepThread(1000000000ULL);
            return;
        }
    }

    // Keep initialization deliberately minimal. The AMS framework owns the
    // process bootstrap; this phase only establishes heap/fs state and idles.
    fsInitialize();

    for (;;) {
        svcSleepThread(1000000000ULL);
    }
}

void NORETURN Exit(int rc) {
    AMS_UNUSED(rc);
    for (;;) {
        svcSleepThread(1000000000ULL);
    }
}

}
