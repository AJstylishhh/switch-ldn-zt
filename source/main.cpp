#include <switch.h>
#include <ZeroTierSockets.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cinttypes>
#include <sys/stat.h>

static uint64_t g_network_id = 0;
static bool g_joined = false;

static void print_event(void* ptr)
{
    const auto* msg = static_cast<const zts_event_msg_t*>(ptr);
    if (!msg) return;

    switch (msg->event_code) {
        case ZTS_EVENT_NODE_ONLINE:
            printf("[ZT] Node ONLINE: %" PRIx64 "\n", zts_node_get_id());
            break;
        case ZTS_EVENT_NODE_OFFLINE:
            printf("[ZT] Node OFFLINE\n");
            break;
        case ZTS_EVENT_NETWORK_OK:
            printf("[ZT] Network OK\n");
            g_joined = true;
            break;
        case ZTS_EVENT_NETWORK_ACCESS_DENIED:
            printf("[ZT] Network access denied\n");
            break;
        case ZTS_EVENT_NETWORK_NOT_FOUND:
            printf("[ZT] Network not found\n");
            break;
        case ZTS_EVENT_NETWORK_READY_IP4:
            printf("[ZT] IPv4 address assigned\n");
            break;
        case ZTS_EVENT_NETWORK_DOWN:
            printf("[ZT] Network transport down\n");
            g_joined = false;
            break;
        default:
            break;
    }
}

static bool read_network_id(uint64_t& out)
{
    FILE* f = std::fopen("sdmc:/config/zerotier-switch/network_id.txt", "rb");
    if (!f) return false;

    char buf[64] = {};
    const size_t n = std::fread(buf, 1, sizeof(buf) - 1, f);
    std::fclose(f);
    if (n == 0) return false;

    char* end = nullptr;
    const unsigned long long value = std::strtoull(buf, &end, 16);
    if (end == buf || value == 0) return false;

    out = static_cast<uint64_t>(value);
    return true;
}

int main(int argc, char* argv[])
{
    (void)argc;
    (void)argv;

    consoleInit(NULL);
    fsdevMountSdmc();

    printf("ZeroTier Switch\n");
    printf("------------------------------\n");
    printf("Loading network configuration...\n\n");

    mkdir("sdmc:/config", 0777);
    mkdir("sdmc:/config/zerotier-switch", 0777);
    mkdir("sdmc:/config/zerotier-switch/zt", 0777);

    if (!read_network_id(g_network_id)) {
        printf("Missing network ID.\n\n");
        printf("Create this file:\n");
        printf("/config/zerotier-switch/network_id.txt\n\n");
        printf("Put your 16-digit ZeroTier network ID inside it.\n");
        printf("Example: 8056c2e21c000001\n\n");
        printf("Press + to exit.\n");

        while (appletMainLoop()) {
            hidScanInput();
            if (hidKeysDown(CONTROLLER_P1_AUTO) & KEY_PLUS) break;
            consoleUpdate(NULL);
        }

        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 0;
    }

    printf("Network ID : %016" PRIx64 "\n", g_network_id);
    printf("Starting ZeroTier...\n");

    const int init_rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    printf("zts_init_from_storage: %d\n", init_rc);
    if (init_rc != ZTS_ERR_OK) {
        printf("Initialization failed.\n");
        printf("Press + to exit.\n");
        while (appletMainLoop()) {
            hidScanInput();
            if (hidKeysDown(CONTROLLER_P1_AUTO) & KEY_PLUS) break;
            consoleUpdate(NULL);
        }
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 1;
    }

    zts_init_set_event_handler(print_event);

    const int start_rc = zts_node_start();
    printf("zts_node_start: %d\n", start_rc);
    if (start_rc != ZTS_ERR_OK) {
        printf("Node start failed.\n");
    }

    printf("Waiting for ZeroTier node to come online...\n");
    int waited = 0;
    while (appletMainLoop() && !zts_node_is_online() && waited < 300) {
        hidScanInput();
        if (hidKeysDown(CONTROLLER_P1_AUTO) & KEY_PLUS) goto shutdown;
        zts_util_delay(100);
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
            hidScanInput();
            if (hidKeysDown(CONTROLLER_P1_AUTO) & KEY_PLUS) goto shutdown;
            zts_util_delay(100);
            waited++;
            consoleUpdate(NULL);
        }
    }

    printf("\nStatus\n");
    printf("------\n");
    printf("ZeroTier : %s\n", zts_node_is_online() ? "ONLINE" : "OFFLINE");
    printf("Network  : %s\n", zts_net_transport_is_ready(g_network_id) ? "READY" : "NOT READY");
    printf("\nPress + to exit.\n");

    while (appletMainLoop()) {
        hidScanInput();
        if (hidKeysDown(CONTROLLER_P1_AUTO) & KEY_PLUS) break;
        consoleUpdate(NULL);
    }

shutdown:
    printf("\nStopping ZeroTier...\n");
    zts_node_stop();
    zts_node_free();
    fsdevUnmountDevice("sdmc");
    consoleExit(NULL);
    return 0;
}
