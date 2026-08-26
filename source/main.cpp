#include <switch.h>
#include <ZeroTierSockets.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cinttypes>
#include <sys/stat.h>

// No direct HID API is used by this transport test application.
// It exits through the normal libnx applet lifecycle for compatibility.
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
    while (len > 0 && (out[len - 1] == '\n' || out[len - 1] == '\r' || out[len - 1] == ' ' || out[len - 1] == '\t')) {
        out[--len] = '\0';
    }

    return out[0] != '\0';
}

static bool read_network_id(uint64_t& out)
{
    char buf[64] = {};
    if (!read_text_file("sdmc:/config/zerotier-switch/network_id.txt", buf, sizeof(buf))) {
        return false;
    }

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
        zts_util_delay(50);
    }
}

static void run_transport_probe()
{
    char local_addr[ZTS_IP_MAX_STR_LEN] = {};
    if (!zts_addr_is_assigned(g_network_id, ZTS_AF_INET)) {
        printf("[PROBE] No ZeroTier IPv4 address assigned yet.\n");
        return;
    }

    if (zts_addr_get_str(g_network_id, ZTS_AF_INET, local_addr, sizeof(local_addr)) != ZTS_ERR_OK) {
        printf("[PROBE] Failed to obtain ZeroTier IPv4 address (errno=%d).\n", zts_errno);
        return;
    }

    printf("[PROBE] ZeroTier IPv4: %s\n", local_addr);
    printf("[PROBE] This is a transport-only test; ldn_mitm is not integrated yet.\n");

    char role[16] = {};
    if (!read_text_file("sdmc:/config/zerotier-switch/test_role.txt", role, sizeof(role))) {
        printf("[PROBE] No test_role.txt; skipping socket probe.\n");
        printf("[PROBE] Use 'server' on one Switch or 'client' on the other.\n");
        return;
    }

    constexpr unsigned int port = 11452;

    if (std::strcmp(role, "server") == 0) {
        printf("[PROBE] TCP SERVER %s:%u\n", local_addr, port);
        printf("[PROBE] Waiting for a ZeroTier peer...\n");

        char remote_addr[ZTS_INET6_ADDRSTRLEN] = {};
        unsigned short remote_port = 0;
        const int fd = zts_tcp_server(local_addr, port, remote_addr, sizeof(remote_addr), &remote_port);
        if (fd < 0) {
            printf("[PROBE] zts_tcp_server failed: fd=%d errno=%d\n", fd, zts_errno);
            return;
        }

        printf("[PROBE] Accepted %s:%u\n", remote_addr, remote_port);

        char buf[128] = {};
        const int n = zts_read(fd, buf, sizeof(buf) - 1);
        if (n < 0) {
            printf("[PROBE] zts_read failed: %d errno=%d\n", n, zts_errno);
        } else {
            buf[n] = '\0';
            printf("[PROBE] Received %d bytes: %s\n", n, buf);
            const int sent = zts_write(fd, buf, n);
            printf("[PROBE] Echo result: %d errno=%d\n", sent, zts_errno);
        }

        zts_close(fd);
        printf("[PROBE] Server test complete.\n");
        return;
    }

    if (std::strcmp(role, "client") == 0) {
        char peer_addr[ZTS_IP_MAX_STR_LEN] = {};
        if (!read_text_file("sdmc:/config/zerotier-switch/peer_ip.txt", peer_addr, sizeof(peer_addr))) {
            printf("[PROBE] client mode requires peer_ip.txt.\n");
            return;
        }

        printf("[PROBE] TCP CLIENT -> %s:%u\n", peer_addr, port);
        int fd = -1;
        for (int attempt = 0; attempt < 10 && fd < 0; ++attempt) {
            fd = zts_tcp_client(peer_addr, port);
            if (fd < 0) {
                printf("[PROBE] connect attempt %d failed: errno=%d\n", attempt + 1, zts_errno);
                zts_util_delay(500);
            }
        }

        if (fd < 0) {
            printf("[PROBE] Could not connect to peer.\n");
            return;
        }

        const char* msg = "switch-ldn-zt transport probe";
        const int sent = zts_write(fd, msg, std::strlen(msg));
        printf("[PROBE] Sent %d bytes.\n", sent);

        char buf[128] = {};
        const int n = zts_read(fd, buf, sizeof(buf) - 1);
        if (n < 0) {
            printf("[PROBE] zts_read failed: %d errno=%d\n", n, zts_errno);
        } else {
            buf[n] = '\0';
            printf("[PROBE] Echoed %d bytes: %s\n", n, buf);
        }

        zts_close(fd);
        printf("[PROBE] Client test complete.\n");
        return;
    }

    printf("[PROBE] Unknown test_role '%s' (use server/client).\n", role);
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
    consoleUpdate(NULL);
    svcSleepThread(3000000000ULL); // 3s pause so you can actually read this before anything risky runs

    // libzt needs the console's own network service running before it can open
    // any real socket to reach ZeroTier's servers over the internet. Without this,
    // zts_node_start() below can crash before ever printing anything further.
    const Result sockRc = socketInitializeDefault();
    printf("socketInitializeDefault: 0x%x\n", sockRc);
    consoleUpdate(NULL);
    svcSleepThread(3000000000ULL);
    if (R_FAILED(sockRc)) {
        printf("Failed to bring up the network service. Cannot continue.\n");
        printf("Close the app from the Home menu.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 1;
    }

    mkdir("sdmc:/config", 0777);
    mkdir("sdmc:/config/zerotier-switch", 0777);
    mkdir("sdmc:/config/zerotier-switch/zt", 0777);

    if (!read_network_id(g_network_id)) {
        printf("Missing network ID.\n\n");
        printf("Create this file:\n");
        printf("/config/zerotier-switch/network_id.txt\n\n");
        printf("Put your 16-digit ZeroTier network ID inside it.\n");
        printf("Example: 8056c2e21c000001\n\n");
        printf("Close the app from the Home menu.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 0;
    }

    printf("Network ID : %016" PRIx64 "\n", g_network_id);
    printf("Starting ZeroTier...\n");
    consoleUpdate(NULL);
    svcSleepThread(3000000000ULL);

    const int init_rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    printf("zts_init_from_storage: %d\n", init_rc);
    if (init_rc != ZTS_ERR_OK) {
        printf("Initialization failed.\n");
        printf("Close the app from the Home menu.\n");
        wait_for_applet_exit();
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
            zts_util_delay(100);
            waited++;
            consoleUpdate(NULL);
        }

        printf("Waiting for ZeroTier IPv4 assignment...\n");
        waited = 0;
        while (appletMainLoop() && !zts_addr_is_assigned(g_network_id, ZTS_AF_INET) && waited < 300) {
            zts_util_delay(100);
            waited++;
            consoleUpdate(NULL);
        }

        run_transport_probe();
    }

    printf("\nStatus\n");
    printf("------\n");
    printf("ZeroTier : %s\n", zts_node_is_online() ? "ONLINE" : "OFFLINE");
    printf("Network  : %s\n", zts_net_transport_is_ready(g_network_id) ? "READY" : "NOT READY");
    printf("\nClose the app from the Home menu.\n");

    wait_for_applet_exit();

shutdown:
    printf("\nStopping ZeroTier...\n");
    zts_node_stop();
    zts_node_free();
    socketExit();
    fsdevUnmountDevice("sdmc");
    consoleExit(NULL);
    return 0;
}
