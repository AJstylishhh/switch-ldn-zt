/*
 * ZeroTier sysmodule (Sys B).
 *
 * Phase 1 (hardware-proven): link libzt.a, NO zts_* calls.
 * Phase 2 (failed on device): zts_init_from_storage caused logo 0xffe.
 * Do not reintroduce zts_* until a safe load path exists for sysmodules.
 */

#include <stratosphere.hpp>

#include <cstdlib>
#include <cstdint>
#include <malloc.h>

#include <switch.h>

namespace ams {

    namespace {

        constexpr size_t MallocBufferSize = 1_MB;
        alignas(os::MemoryPageSize) constinit u8 g_malloc_buffer[MallocBufferSize];

    }

    namespace sysb {

        alignas(0x40) constinit u8 g_heap_memory[128_KB];
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
        /* Phase 1: no zts_* — referencing them pulls libzt objects that 0xffe at logo. */
        while (true)
        {
            os::SleepThread(TimeSpan::FromSeconds(1));
        }
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
