#include <stdio.h>
#ifdef __SWITCH__
#include <switch.h>
#endif

/* Temporary Switch diagnostics must live after the required headers. */
#ifdef __SWITCH__
static void switch_diag_print(const char *msg) {
    printf("%s", msg);
    consoleUpdate(NULL);
}
#endif

/* Existing upstream VirtualTap.cpp content is intentionally retained by the CI patcher. */
