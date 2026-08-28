#include <switch.h>
#include <ZeroTierSockets.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cinttypes>
#include <cerrno>
#include <ctime>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

extern "C" void zt_net_stats(char* out, size_t n);
extern "C" void zt_report_state_files(void);
extern "C" void zt_log(const char* msg);
extern "C" void zt_begin_exit(void);

static uint64_t g_network_id = 0;
static char g_last_ip[64] = {};

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
        default: printf("[ZT] event %d\n", msg->event_code); break;
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

static PadState g_pad;

static void input_init()
{
    padConfigureInput(1, HidNpadStyleSet_NpadStandard);
    padInitializeDefault(&g_pad);
}

static bool exit_requested()
{
    padUpdate(&g_pad);
    return (padGetButtonsDown(&g_pad) & HidNpadButton_Plus) != 0;
}

static void wait_for_applet_exit()
{
    while (appletMainLoop()) {
        if (exit_requested()) break;
        consoleUpdate(NULL);
        svcSleepThread(1000000ULL);
    }
}

static void probe_network()
{
    printf("[NET] time=%lld\n", (long long)std::time(NULL));
    consoleUpdate(NULL);

    const int s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    printf("[NET] udp socket -> %d (errno=%d)\n", s, errno);
    consoleUpdate(NULL);
    if (s < 0) return;

    struct sockaddr_in local;
    std::memset(&local, 0, sizeof(local));
    local.sin_family = AF_INET;
    local.sin_addr.s_addr = htonl(INADDR_ANY);
    local.sin_port = htons(9993);
    errno = 0;
    const int b = bind(s, reinterpret_cast<struct sockaddr*>(&local), sizeof(local));
    printf("[NET] bind :9993 -> %d (errno=%d)\n", b, errno);
    consoleUpdate(NULL);

    static const unsigned char query[] = {
        0x12, 0x34, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x08, 'z', 'e', 'r', 'o', 't', 'i', 'e', 0x03, 'c', 'o', 'm', 0x00,
        0x00, 0x01, 0x00, 0x01
    };
    struct sockaddr_in dst;
    std::memset(&dst, 0, sizeof(dst));
    dst.sin_family = AF_INET;
    dst.sin_port = htons(53);
    dst.sin_addr.s_addr = inet_addr("8.8.8.8");
    errno = 0;
    const ssize_t sent = sendto(s, query, sizeof(query), 0,
                                reinterpret_cast<struct sockaddr*>(&dst), sizeof(dst));
    printf("[NET] sendto 8.8.8.8:53 -> %ld (errno=%d)\n", (long)sent, errno);
    consoleUpdate(NULL);

    fd_set rfds;
    FD_ZERO(&rfds);
    FD_SET(s, &rfds);
    struct timeval tv;
    tv.tv_sec = 3;
    tv.tv_usec = 0;
    errno = 0;
    const int sel = select(s + 1, &rfds, NULL, NULL, &tv);
    printf("[NET] select -> %d (errno=%d)\n", sel, errno);
    if (sel > 0) {
        unsigned char rbuf[512];
        errno = 0;
        const ssize_t got = recvfrom(s, rbuf, sizeof(rbuf), 0, NULL, NULL);
        printf("[NET] recvfrom -> %ld (errno=%d)\n", (long)got, errno);
        printf("[NET] INTERNET UDP OK\n");
    } else {
        printf("[NET] NO UDP REPLY\n");
    }
    consoleUpdate(NULL);
    close(s);
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
    if (rc != ZTS_ERR_OK) return rc;

    printf("zts_init_set_port: %d\n", zts_init_set_port(9993));
    printf("zts_init_allow_secondary_port: %d\n", zts_init_allow_secondary_port(1));
    printf("zts_init_allow_port_mapping: %d\n", zts_init_allow_port_mapping(0));
    consoleUpdate(NULL);
    return rc;
}

int main(int argc, char* argv[])
{
    (void)argc; (void)argv;
    consoleInit(NULL);
    input_init();
    fsdevMountSdmc();

    printf("ZeroTier Switch\n------------------------------\nLoading network configuration...\n\n");
    consoleUpdate(NULL);

    static const SocketInitConfig sock_cfg = {
        .tcp_tx_buf_size     = 0x1000,
        .tcp_rx_buf_size     = 0x1000,
        .tcp_tx_buf_max_size = 0x20000,
        .tcp_rx_buf_max_size = 0x20000,
        .udp_tx_buf_size     = 0x2400,
        .udp_rx_buf_size     = 0xA500,
        .sb_efficiency       = 8,
        .num_bsd_sessions    = 16,
        .bsd_service_type    = BsdServiceType_Auto,
    };
    const Result sockRc = socketInitialize(&sock_cfg);
    printf("socketInitialize: 0x%x\n", sockRc);
    consoleUpdate(NULL);
    if (R_FAILED(sockRc)) {
        printf("Failed to bring up the network service. Cannot continue.\nPress + to exit.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 1;
    }

    mkdir("sdmc:/config", 0777);
    mkdir("sdmc:/config/zerotier-switch", 0777);
    mkdir("sdmc:/config/zerotier-switch/zt", 0777);

    if (!read_network_id(g_network_id)) {
        printf("Missing network ID.\n\nCreate this file:\n/config/zerotier-switch/network_id.txt\n\nPut your 16-digit ZeroTier network ID inside it.\nExample: 8056c2e21c000001\n\nPress + to exit.\n");
        wait_for_applet_exit();
        fsdevUnmountDevice("sdmc");
        consoleExit(NULL);
        return 0;
    }

    printf("Network ID : %016" PRIx64 "\n", g_network_id);
    consoleUpdate(NULL);

    probe_network();

    printf("Starting ZeroTier...\n");
    consoleUpdate(NULL);

    const int init_rc = init_zerotier_with_diagnostics();
    if (init_rc != ZTS_ERR_OK) {
        printf("Initialization failed.\nPress + to exit.\n");
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
    printf("[HB] calling zts_node_get_id()\n");
    const uint64_t probe_id = zts_node_get_id();
    printf("[HB] zts_node_get_id -> %010" PRIx64 "\n", probe_id);
    printf("[HB] calling zts_node_is_online()\n");
    const bool probe_online = zts_node_is_online();
    printf("[HB] zts_node_is_online -> %d\n", probe_online ? 1 : 0);
    consoleUpdate(NULL);

    printf("Press + to exit.\n\n");
    consoleUpdate(NULL);

    int waited = 0;
    bool was_online = false;
    bool was_ready = false;
    bool joined = false;

    while (appletMainLoop()) {
        if (exit_requested()) break;
        const bool online = zts_node_is_online();
        const bool ready = zts_net_transport_is_ready(g_network_id);

        if (online != was_online) {
            printf("[ZT] node is now %s (t=%ds)\n", online ? "ONLINE" : "OFFLINE", waited / 100);
            was_online = online;
            consoleUpdate(NULL);
        }
        if (ready != was_ready) {
            printf("[ZT] network transport is now %s (t=%ds)\n", ready ? "READY" : "NOT READY", waited / 100);
            was_ready = ready;
            consoleUpdate(NULL);
        }
        if (online && !joined) {
            const int join_rc = zts_net_join(g_network_id);
            printf("[ZT] zts_net_join -> %d (t=%ds)\n", join_rc, waited / 100);
            joined = true;
            consoleUpdate(NULL);
        }

        svcSleepThread(10000000ULL);
        waited++;

        if ((waited % 500) == 0) {
            char ip[64];
            ip[0] = 0;
            const int have_ip = zts_addr_is_assigned(g_network_id, ZTS_AF_INET);
            if (zts_addr_get_str(g_network_id, ZTS_AF_INET, ip, sizeof(ip)) != ZTS_ERR_OK) {
                snprintf(ip, sizeof(ip), "none");
            }
            if (have_ip && strcmp(ip, g_last_ip) != 0) {
                snprintf(g_last_ip, sizeof(g_last_ip), "%s", ip);
                printf("\n  ================================\n");
                printf("   ZeroTier IP : %s\n", ip);
                printf("   Node ID     : %010" PRIx64 "\n", zts_node_get_id());
                printf("   Network     : %016" PRIx64 "\n", g_network_id);
                printf("  ================================\n\n");
            }
            printf("[IP] assigned=%d addr=%s\n", have_ip, ip);

            char stats[160];
            zt_net_stats(stats, sizeof(stats));
            printf("[HB] t=%ds id=%016" PRIx64 " %s %s/%s\n",
                   waited / 100, zts_node_get_id(), stats,
                   online ? "ONLINE" : "offline", ready ? "READY" : "not-ready");
        }
        if ((waited % 3000) == 0) zt_report_state_files();
        if ((waited % 10) == 0) consoleUpdate(NULL);
    }

    printf("\nExiting...\n");
    consoleUpdate(NULL);

    zt_begin_exit();
    zt_log("[EXIT] requested, terminating\n");
    consoleExit(NULL);
    svcExitProcess();
    return 0;
}