#include <stratosphere.hpp>

namespace ams {

void Main() {
    R_ABORT_UNLESS(log::Initialize());
    LogFormat("ZT-SYS: B1 main entered; libzt linked, no zts_* calls");

    for (;;) {
        svcSleepThread(1000000000ULL);
    }
}

void NORETURN Exit(int rc) {
    AMS_UNUSED(rc);
    AMS_ABORT("Exit called by immortal process");
}

}
