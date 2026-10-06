/*
 * ZeroTier sysmodule (Sys B) — Phase 2b
 *
 * Uses nx-mod/libzt-nx sysmodule profile (switch branch >= 664bfa9):
 * smaller tables, bounded multicast queue, optional 2 MiB genmem borrow.
 *
 * Phase 1 (76c138b-era lib, no zts_*): boot OK on device.
 * Phase 2 (76c138b + zts_init): logo 0xffe.
 * Phase 2b: same call with post-shrink lib + embedding hooks.
 *
 * Still NO zts_node_start / zts_net_join until init survives boot.
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

        /* AMS malloc arena */
        constexpr size_t MallocBufferSize = 1_MB;
        alignas(os::MemoryPageSize) constinit u8 g_malloc_buffer[MallocBufferSize];

        /* nx-mod libzt may borrow up to 2 MiB for identity hash */
        constexpr size_t ZtGenmemSize = 2_MB;
        alignas(os::MemoryPageSize) constinit u8 g_zt_genmem[ZtGenmemSize];
        constinit bool g_zt_genmem_in_use = false;

        constexpr const char *ZtStorageDir = "sdmc:/config/switch-ldn-zt";

    }

    namespace sysb {

        /* General AMS/fs heap — larger than Phase 1 for ZT side allocations */
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
         * Phase 2b: only zts_init_from_storage.
         * Never abort the sysmodule on ZT failure.
         * Main thread stack is 0x20000 (128 KiB) per app.json — matches nx-mod guidance.
         */
        const int zt_rc = zts_init_from_storage(ZtStorageDir);
        AMS_UNUSED(zt_rc);

        while (true)
        {
            os::SleepThread(TimeSpan::FromSeconds(1));
        }
    }

}

/* ---- nx-mod/libzt-nx embedding hooks (weak symbols in the library) ---- */

extern "C" void zt_stub_hit(const char *what)
{
    /* First use of a stubbed metrics/feature — keep quiet for boot isolation. */
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
