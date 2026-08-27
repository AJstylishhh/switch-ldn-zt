#include <switch.h>
#include <ZeroTierSockets.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cinttypes>
#include <cerrno>
#include <sys/stat.h>

static uint64_t g_network_id = 0;

static void print_event(void* ptr)
{
    const auto* msg = static_cast<const zts_event_msg_t*>(ptr);
    if (!msg) return;
    switch (msg->event_code) {
        case ZTS_EVENT_NODE_ONLINE: printf("[ZT] Node ONLINE: %" PRIx64 "\n", zts_node_get_id()); break;
        case ZTS_EVENT_NODE_OFFLINE: printf("[ZT] Node OFFLINE\n"); break;
        case ZTS_EVENT_NETWORK_OK: printf("[ZT] Network OK\n"); break;
        case ZTS_EVENT_NETWORK_ACCESS_DENIED: printf("[ZT] Network access denied\n"); break;
        case ZTS_EVENT_NETWORK_NOT_FOUND: printf("[ZT] Network not found\n"); break;
        case ZTS_EVENT_NETWORK_READY_IP4: printf("[ZT] IPv4 address assigned\n"); break;
        case ZTS_EVENT_NETWORK_DOWN: printf("[ZT] Network transport down\n"); break;
        default: break;
    }
}

static bool read_text_file(const char* path, char* out, size_t out_len)
{
    if (!out || out_len < 2) return false;
    FILE* f = std::fopen(path, "rb");
    if (!f) return false;
    const size_t n = std::fread(out, 1, out_len - 1, f);
    std::fclose(f);
    if (n == 0) return false;
    out[n] = '\0';
    size_t len = n;
    while (len > 0 && (out[len - 1] == '\n' || out[len - 1] == '\r' || out[len - 1] == ' ' || out[len - 1] == '\t')) out[--len] = '\0';
    return out[0] != '\0';
}

static bool read_network_id(uint64_t& out)
{
    char buf[64] = {};
    if (!read_text_file("sdmc:/config/zerotier-switch/network_id.txt", buf, sizeof(buf))) return false;
    char* end = nullptr;
    const unsigned long long value = std::strtoull(buf, &end, 16);
    if (end == buf || value == 0) return false;
    out = static_cast<uint64_t>(value);
    return true;
}

static void wait_for_applet_exit()
{
    while (appletMainLoop()) {
        consoleUpdate(NULL);
        svcSleepThread(1000000ULL); // 1ms sleep to yield CPU
    }
}

static int init_zerotier_with_diagnostics()
{
    printf("Testing Switch pipe compatibility...\n");
    consoleUpdate(NULL);
    int test_pipe[2] = {-1, -1};
    const int pipe_rc = pipe(test_pipe);
    printf("pipe() test result: %d\n", pipe_rc);
    consoleUpdate(NULL);

    if (pipe_rc == 0) {
        const char marker = 'Z';
        const ssize_t written = write(test_pipe[1], &marker, 1);
        char received = 0;
        const ssize_t read_count = read(test_pipe[0], &received, 1);
        printf("pipe write/read: %ld/%ld (byte=%c)\n", (long)written, (long)read_count, received ? received : '?');
        close(test_pipe[0]);
        close(test_pipe[1]);
        consoleUpdate(NULL);
    } else {
        printf("pipe() compatibility failed; ZeroTier cannot start safely. errno=%d\n", errno);
        consoleUpdate(NULL);
        return ZTS_ERR_GENERAL;
    }

    printf("Creating ZeroTier service...\n");
    consoleUpdate(NULL);
    const int rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    printf("zts_init_from_storage returned: %d\n", rc);
    consoleUpdate(NULL);
    return rc;
}

int main(int argc, char* argv[])
{
    (void)argc; (void)argv;
    consoleInit(NULL);
    fsdevMountSdmc();

    printf("ZeroTier Switch\n------------------------------\nLoading network configuration...\n\n");
    consoleUpdate(NULL);

    const Result sockRc = socketInitializeDefault();
    printf("socketInitializeDefault: 0x%x\n", sockRc);
    consoleUpdate(NULL);
    if (R_FAILED(sockRc)) {
        printf("Failed to bring up the network service. Cannot continue.\nClose the app from the Home menu.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 1;
    }

    mkdir("sdmc:/config", 0777);
    mkdir("sdmc:/config/zerotier-switch", 0777);
    mkdir("sdmc:/config/zerotier-switch/zt", 0777);

    if (!read_network_id(g_network_id)) {
        printf("Missing network ID.\n\nCreate this file:\n/config/zerotier-switch/network_id.txt\n\nPut your 16-digit ZeroTier network ID inside it.\nExample: 8056c2e21c000001\n\nClose the app from the Home menu.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 0;
    }

    printf("Network ID : %016" PRIx64 "\n", g_network_id);
    printf("Starting ZeroTier...\n");
    consoleUpdate(NULL);

    const int init_rc = init_zerotier_with_diagnostics();
    if (init_rc != ZTS_ERR_OK) {
        printf("Initialization failed.\nClose the app from the Home menu.\n");
        consoleUpdate(NULL);
        wait_for_applet_exit();
        socketExit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 1;
    }

    printf("[DIAG] About to register ZeroTier event handler...\n");
    consoleUpdate(NULL);
    zts_init_set_event_handler(print_event);

    printf("[DIAG] Event handler registration returned.\n");
    consoleUpdate(NULL);

    printf("[DIAG] About to call zts_node_start()...\n");
    consoleUpdate(NULL);

    const int start_rc = zts_node_start();

    printf("[DIAG] zts_node_start() returned: %d\n", start_rc);
    consoleUpdate(NULL);
    if (start_rc != ZTS_ERR_OK) printf("Node start failed.\n");

    printf("Waiting for ZeroTier node to come online...\n");
    int waited = 0;
    while (appletMainLoop() && !zts_node_is_online() && waited < 300) {
        svcSleepThread(1000000ULL); // 1ms yield
        waited++;
        consoleUpdate(NULL);
    }

    printf("Node ID    : %010" PRIx64 "\n", zts_node_get_id());
    printf("Node online: %s\n", zts_node_is_online() ? "yes" : "no");

    if (zts_node_is_online()) {
        const int join_rc = zts_net_join(g_network_id);
        printf("zts_net_join: %d\n", join_rc);
        printf("Waiting for network transport...\n");
        waited = 0;
        while (appletMainLoop() && !zts_net_transport_is_ready(g_network_id) && waited < 300) {
            svcSleepThread(1000000ULL); waited++; consoleUpdate(NULL);
        }
    }

    printf("\nStatus\n------\nZeroTier : %s\nNetwork  : %s\n\nClose the app from the Home menu.\n",
           zts_node_is_online() ? "ONLINE" : "OFFLINE",
           zts_net_transport_is_ready(g_network_id) ? "READY" : "NOT READY");
    wait_for_applet_exit();

    printf("\nStopping ZeroTier...\n");
    zts_node_stop();
    zts_node_free();
    socketExit();
    fsdevUnmountDevice("sdmc");
    consoleExit(NULL);
    return 0;
}
