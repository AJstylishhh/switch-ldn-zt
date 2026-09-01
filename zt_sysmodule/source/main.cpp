#include <stratosphere.hpp>

namespace ams {

void Main() {
    // Sys B is intentionally a minimal boot/link isolation target.
    // Do not initialize Atmosphere logging here: this target does not
    // provide the log namespace used by the full LDN sysmodule.
    for (;;) {
        svcSleepThread(1000000000ULL);
    }
}

void NORETURN Exit(int rc) {
    AMS_UNUSED(rc);
    AMS_ABORT("Exit called by immortal process");
}

}
