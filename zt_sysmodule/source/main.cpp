/*
 * ZeroTier sysmodule (Sys B) — Phase 2c
 *
 * Goal: process stays alive through logo/home (like Phase 1).
 * Do NOT call zts_* at boot. Enable later (nobody's "ovl enable" idea):
 *   create empty file: sdmc:/config/switch-ldn-zt/enable
 * then this module notices within a few seconds and runs zts_init_from_storage
 * on a dedicated libnx thread (128 KiB stack).
 *
 * Still no zts_node_start / join / games.
 *
 * History:
 *   Phase 1: link libzt, no zts_* refs → boot OK
 *   Phase 2/2b: zts_init in Main at boot → logo 0xffe
 *   Phase 2c: deferred enable after boot
 */

#include <stratosphere.hpp>

#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <malloc.h>

#include <switch.h>
#include <ZeroTierSockets.h>

namespace ams {

    namespace {

        constexpr size_t MallocBufferSize = 1_MB;
        alignas(os::MemoryPageSize) constinit u8 g_malloc_buffer[MallocBufferSize];

        constexpr size_t ZtGenmemSize = 2_MB;
        alignas(os::MemoryPageSize) constinit u8 g_zt_genmem[ZtGenmemSize];
        constinit bool g_zt_genmem_in_use = false;

        constexpr const char *ZtStorageDir = "sdmc:/config/switch-ldn-zt";
        constexpr const char *ZtEnablePath = "sdmc:/config/switch-ldn-zt/enable";

        constinit bool g_zt_init_started = false;
        constinit bool g_zt_init_done = false;
        constinit int g_zt_init_rc = -999;

        /* Dedicated stack for ZT init (nx-mod: 128 KiB, libnx thread) */
        constexpr size_t ZtThreadStackSize = 0x20000;
        alignas(0x1000) constinit u8 g_zt_thread_stack[ZtThreadStackSize];
        constinit Thread g_zt_thread;

        bool EnableFlagExists()
        {
            FsFile f;
            const Result rc = fsFsOpenFile(fsdevGetDeviceFileSystem("sdmc"), ZtEnablePath + 5 /* skip sdmc: */,
                                          FsOpenMode_Read, &f);
            /* Prefer fs:: via Atmosphere for path "sdmc:/..." */
            AMS_UNUSED(rc);
            AMS_UNUSED(f);

            /* Simple portable check: try open via stdio after fsdev */
            FILE *fp = fopen(ZtEnablePath, "rb");
            if (fp == nullptr) {
                return false;
            }
            fclose(fp);
            return true;
        }

        void ZtInitThreadFunc(void *)
        {
            g_zt_init_rc = zts_init_from_storage(ZtStorageDir);
            g_zt_init_done = true;
        }

        void TryStartZtInit()
        {
            if (g_zt_init_started) {
                return;
            }
            if (!EnableFlagExists()) {
                return;
            }

            g_zt_init_started = true;

            /* libnx thread so newlib TLS is valid for libzt worker threads */
            const Result trc = threadCreate(
                &g_zt_thread,
                ZtInitThreadFunc,
                nullptr,
                g_zt_thread_stack,
                ZtThreadStackSize,
                0x2C,
                -2);

            if (R_SUCCEEDED(trc)) {
                threadStart(&g_zt_thread);
            } else {
                /* Fallback: same thread (still only after enable, not at logo) */
                ZtInitThreadFunc(nullptr);
            }
        }

    }

    namespace sysb {

        alignas(0x40) constinit u8 g_heap_memory[512_KB];
        constinit lmem::HeapHandle g_heap_handle;
        constinit bool g_heap_initialized;
        constinit os::SdkMutex g_heap_init_mutex;

        lmem::HeapHandle GetHeapHandle()
        {
            if (AMS_UNLIKELY(!g_heap_initialized))
            {
                std::scoped_lock lk(g_heap_init_mutex);

                if (AMS_LIKELY(!g_heap_initialized))
                {
                    g_heap_handle = lmem::CreateExpHeap(g_heap_memory, sizeof(g_heap_memory), lmem::CreateOption_ThreadSafe);
                    g_heap_initialized = true;
                }
            }

            return g_heap_handle;
        }

        void *Allocate(size_t size)
        {
            return lmem::AllocateFromExpHeap(GetHeapHandle(), size);
        }

        void Deallocate(void *p, size_t size)
        {
            AMS_UNUSED(size);
            return lmem::FreeToExpHeap(GetHeapHandle(), p);
        }

    }

    namespace init {

        void InitializeSystemModule()
        {
            R_ABORT_UNLESS(sm::Initialize());

            fs::InitializeForSystem();
            fs::SetAllocator(sysb::Allocate, sysb::Deallocate);
            fs::SetEnabledAutoAbort(false);

            R_ABORT_UNLESS(fs::MountSdCard("sdmc"));
        }

        void Startup()
        {
            init::InitializeAllocator(g_malloc_buffer, sizeof(g_malloc_buffer));
        }

        void FinalizeSystemModule() { /* ... */ }

    }

    void NORETURN Exit(int rc)
    {
        AMS_UNUSED(rc);
        AMS_ABORT("Exit called by immortal process");
    }

    void Main()
    {
        /*
         * Phase 2c: stay alive. No zts_* until enable file exists.
         * Boot path must match Phase 1 behavior for logo survival.
         */
        while (true)
        {
            TryStartZtInit();
            os::SleepThread(TimeSpan::FromSeconds(2));
        }
    }

}

extern "C" void zt_stub_hit(const char *what)
{
    AMS_UNUSED(what);
}

extern "C" void *zt_genmem_acquire(unsigned long size)
{
    if (size > ams::ZtGenmemSize || ams::g_zt_genmem_in_use)
    {
        return nullptr;
    }
    ams::g_zt_genmem_in_use = true;
    return ams::g_zt_genmem;
}

extern "C" void zt_genmem_release(void *p)
{
    if (p == ams::g_zt_genmem)
    {
        ams::g_zt_genmem_in_use = false;
    }
}

void *operator new(size_t size)
{
    return ams::sysb::Allocate(size);
}

void *operator new(size_t size, const std::nothrow_t &)
{
    return ams::sysb::Allocate(size);
}

void operator delete(void *p)
{
    return ams::sysb::Deallocate(p, 0);
}

void operator delete(void *p, size_t size)
{
    return ams::sysb::Deallocate(p, size);
}

void *operator new[](size_t size)
{
    return ams::sysb::Allocate(size);
}

void *operator new[](size_t size, const std::nothrow_t &)
{
    return ams::sysb::Allocate(size);
}

void operator delete[](void *p)
{
    return ams::sysb::Deallocate(p, 0);
}

void operator delete[](void *p, size_t size)
{
    return ams::sysb::Deallocate(p, size);
}
