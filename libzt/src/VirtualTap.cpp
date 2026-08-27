#include <stdio.h>
#ifdef __SWITCH__
#include <switch.h>
#endif

#ifdef __SWITCH__
static void switch_diag_print(const char *msg) {
    printf("%s", msg);
    consoleUpdate(NULL);
}
#endif

