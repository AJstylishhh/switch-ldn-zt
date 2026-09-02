/*
 * ZeroTier sysmodule (Sys B).
 *
 * Phase 2: link libzt and call ONLY zts_init_from_storage once from Main().
 * No zts_node_start, no zts_net_join, no wait/spin loops.
 * Startup shape still mirrors Defender ldn_mitm AMS hooks.
 */

#include <stratosphere.hpp>

#include <cstdlib>
#include <cstdint>
#include <malloc.h>

#include <switch.h>
#include <ZeroTierSockets.h>

namespace ams {

    namespace {

        constexpr size_t MallocBufferSize = 1_MB;
        alignas(os::MemoryPageSize) constinit u8 g_malloc_buffer[MallocBufferSize];

        /* Config/storage dir for libzt identity material on SD. */
        constexpr const char *ZtStorageDir = "sdmc:/config/switch-ldn-zt";

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
            /* Initialize our connection to sm. */
            R_ABORT_UNLESS(sm::Initialize());

            /* Initialize fs. */
            fs::InitializeForSystem();
            fs::SetAllocator(sysb::Allocate, sysb::Deallocate);
            fs::SetEnabledAutoAbort(false);

            /* Mount the SD card before any ZT storage path is used. */
            R_ABORT_UNLESS(fs::MountSdCard("sdmc"));
        }

        void Startup()
        {
            /* Initialize the global malloc allocator. */
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
         * Phase 2 isolation:
         * - Call zts_init_from_storage exactly once.
         * - Do NOT call zts_node_start / zts_net_join / delay loops.
         * - Never abort on ZT failure (sysmodule must stay up).
         */
        const int zt_rc = zts_init_from_storage(ZtStorageDir);
        AMS_UNUSED(zt_rc);

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
