// Stock-libzt control node.
//
// This is deliberately built against an UNPATCHED, freshly-cloned libzt --
// see pc-diag/README.md for why that matters. It exists to answer one
// question the Switch-side logging alone could not: does a normal client on
// this ZeroTier network also see roots go silent after the HELLO handshake
// (making this a libzt/ZeroTier-side issue, or a router/NAT issue that
// affects everyone on this network), or does it stay online (making it
// specific to the Switch's own network stack)? It also acts as a real peer
// with a known IP that the Switch .nro can be pinged from/to.
//
// Log format intentionally mirrors source/main.cpp's [HB] line so the two
// logs can be diffed directly.

#include <ZeroTierSockets.h>

#include <atomic>
#include <cinttypes>
#include <csignal>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <chrono>
#include <fstream>
#include <string>
#include <thread>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

static std::atomic<bool> g_node_down{false};
static std::atomic<bool> g_shutdown_requested{false};

static void on_sigint(int)
{
    // Same lesson as source/main.cpp's exit path: zts_node_stop() only sets
    // a flag and returns immediately, and the service thread it signals is
    // never joined anywhere in libzt. Request a clean shutdown from the main
    // loop instead of exiting here directly, so it can wait for the real
    // ZTS_EVENT_NODE_DOWN completion signal before the process ends.
    g_shutdown_requested = true;
}

static int64_t now_ms()
{
    return std::chrono::duration_cast<std::chrono::milliseconds>(
               std::chrono::steady_clock::now().time_since_epoch())
        .count();
}

static void on_event(void* ptr)
{
    const auto* msg = static_cast<const zts_event_msg_t*>(ptr);
    if (!msg) return;
    switch (msg->event_code) {
        case ZTS_EVENT_NODE_ONLINE:
            std::printf("[ZT] Node ONLINE: %010" PRIx64 " port=%d\n",
                        zts_node_get_id(), zts_node_get_port());
            break;
        case ZTS_EVENT_NODE_OFFLINE:
            std::printf("[ZT] Node OFFLINE (phy port=%d)\n", zts_node_get_port());
            break;
        case ZTS_EVENT_NODE_DOWN:
            g_node_down = true;
            std::printf("[ZT] Node DOWN\n");
            break;
        case ZTS_EVENT_NETWORK_READY_IP4:
            std::printf("[ZT] IPv4 address assigned\n");
            break;
        case ZTS_EVENT_PEER_DIRECT:
        case ZTS_EVENT_PEER_RELAY:
        case ZTS_EVENT_PEER_UNREACHABLE:
        case ZTS_EVENT_PEER_PATH_DISCOVERED:
        case ZTS_EVENT_PEER_PATH_DEAD: {
            const char* name = "peerev";
            if (msg->event_code == ZTS_EVENT_PEER_PATH_DEAD) name = "PATH_DEAD";
            else if (msg->event_code == ZTS_EVENT_PEER_UNREACHABLE) name = "UNREACHABLE";
            else if (msg->event_code == ZTS_EVENT_PEER_DIRECT) name = "DIRECT";
            else if (msg->event_code == ZTS_EVENT_PEER_RELAY) name = "RELAY";
            else name = "PATH_DISCOVERED";
            if (msg->peer) {
                std::printf("[ZT] PEER %s peer=%010" PRIx64 " role=%d lat=%d\n",
                            name, msg->peer->peer_id, (int)msg->peer->role, msg->peer->latency);
            }
            break;
        }
        default:
            break;
    }
}

static bool read_network_id(uint64_t& out)
{
    std::ifstream f("config/network_id.txt");
    if (!f) return false;
    std::string s;
    f >> s;
    if (s.empty()) return false;
    out = std::strtoull(s.c_str(), nullptr, 16);
    return out != 0;
}

// Unlike the Switch build, this app cannot see root_tx/root_rx directly.
// posix_compat.cpp gets those counts by linking with -Wl,--wrap=sendto and
// -Wl,--wrap=recvfrom over libzt's actual root traffic; there is no
// equivalent portable hook on a stock host build, and this app is not linked
// against libzt's internals to add one. So the signal this tool actually
// compares against the Switch log is ONLINE/offline, taken directly from
// ZTS_EVENT_NODE_ONLINE/OFFLINE in on_event() and printed every 5s in [HB] --
// that is the same thing the 30s-offline bug showed up as on the Switch, and
// it is what answers the control-group question this tool exists for.
//
// The UDP socket below is unrelated to that -- it is a plain zts_bsd_socket
// ping/pong exchange with the Switch .nro, riding inside the ZeroTier tunnel,
// for manually confirming the tunnel actually carries traffic once online.

int main(int argc, char** argv)
{
    // stdout is fully buffered (not line-buffered) whenever it isn't a real
    // console -- redirected to a file, piped, or captured by a process
    // launcher. Without this, nothing appears until the buffer fills or the
    // process exits, which defeats watching a long-running node live.
    // _IOLBF specifically does NOT work on MSVC's CRT: its docs state a
    // stream requesting line buffering silently gets full buffering instead
    // whenever the destination isn't an actual console. _IONBF is the mode
    // MSVC actually honors for a real per-line flush.
    std::setvbuf(stdout, nullptr, _IONBF, 0);

#ifdef _WIN32
    WSADATA wsa;
    WSAStartup(MAKEWORD(2, 2), &wsa);
#endif
    std::signal(SIGINT, on_sigint);

    uint64_t network_id = 0;
    if (!read_network_id(network_id)) {
        std::fprintf(stderr, "config/network_id.txt missing or empty (run from pc-diag/)\n");
        return 1;
    }
    std::printf("PC Diagnostic Node (stock libzt)\n--------------------------------\n");
    std::printf("Network: %016" PRIx64 "\n", network_id);

    // Two instances on the same machine cannot share an identity/storage
    // directory (both would fight over the same identity files) or a
    // primary UDP port (both would try to bind the same real OS socket).
    // <instance> picks a disjoint storage dir, primary port, and local ping
    // port per instance so `pcdiag.exe <peer_ip> 0` and
    // `pcdiag.exe <peer_ip> 1 9994` can run side by side and ping each other.
    std::string target_ip;
    if (argc > 1) target_ip = argv[1];
    const int instance = (argc > 2) ? std::atoi(argv[2]) : 0;
    const uint16_t target_port = (argc > 3) ? static_cast<uint16_t>(std::atoi(argv[3])) : 9994;

    const std::string storage_dir = (instance == 0) ? "./zt-storage" : ("./zt-storage-" + std::to_string(instance));
    const uint16_t primary_port = static_cast<uint16_t>(9993 + instance);
    const uint16_t local_ping_port = static_cast<uint16_t>(9994 + instance);
    std::printf("Instance %d: storage=%s primary_port=%u local_ping_port=%u\n",
                instance, storage_dir.c_str(), primary_port, local_ping_port);

    zts_init_from_storage(storage_dir.c_str());
    zts_init_set_port(primary_port);
    zts_init_allow_secondary_port(1);
    zts_init_set_event_handler(on_event);

    const int start_rc = zts_node_start();
    std::printf("zts_node_start() -> %d\n", start_rc);
    if (start_rc != ZTS_ERR_OK) return 1;

    std::printf("Waiting for node to come online...\n");
    while (!zts_node_is_online()) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    const int join_rc = zts_net_join(network_id);
    std::printf("zts_net_join -> %d\n", join_rc);

    char ip[64] = {};
    while (zts_addr_is_assigned(network_id, ZTS_AF_INET) == 0) {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    zts_addr_get_str(network_id, ZTS_AF_INET, ip, sizeof(ip));
    std::printf("================================\n");
    std::printf(" ZeroTier IP : %s\n", ip);
    std::printf(" Node ID     : %010" PRIx64 "\n", zts_node_get_id());
    std::printf("================================\n");

    // Plain OS UDP socket for the actual ping exchange with the Switch --
    // deliberately NOT a libzt socket. zts_bsd_socket() traffic would ride
    // inside the ZeroTier tunnel and tell us nothing about the tunnel's own
    // health; a real interface-level socket bound to our ZT-assigned address
    // is the one libzt exposes for that via zts_bsd_*, but for a quick ping
    // test that's still tunnel traffic. This app cares about ONE thing:
    // whether the node stays ONLINE, which the event handler above already
    // reports directly from the core -- the ping exchange below is just
    // for manually confirming reachability to the Switch once online.
    int sock = static_cast<int>(zts_bsd_socket(ZTS_AF_INET, ZTS_SOCK_DGRAM, 0));
    if (sock < 0) {
        std::printf("zts_bsd_socket failed: %d\n", sock);
    } else {
        zts_sockaddr_in bindaddr{};
        bindaddr.sin_family = ZTS_AF_INET;
        bindaddr.sin_port = htons(local_ping_port);
        zts_bsd_bind(sock, (zts_sockaddr*)&bindaddr, sizeof(bindaddr));
        std::printf("UDP ping socket bound on port %u\n", local_ping_port);
    }

    zts_sockaddr_in target{};
    bool have_target = false;
    if (!target_ip.empty() && sock >= 0) {
        target.sin_family = ZTS_AF_INET;
        target.sin_port = htons(target_port);
        zts_inet_pton(ZTS_AF_INET, target_ip.c_str(), &target.sin_addr);
        have_target = true;
        std::printf("Will ping %s:%u over the ZeroTier tunnel\n", target_ip.c_str(), target_port);
    }

    const int64_t start = now_ms();
    int64_t last_report = 0;
    int64_t last_ping = 0;
    uint32_t ping_seq = 0;
    char rxbuf[256];

    std::printf("Running. Press Ctrl+C to exit cleanly.\n");

    while (!g_shutdown_requested) {
        const int64_t elapsed = now_ms() - start;

        if (sock >= 0) {
            zts_sockaddr_in from{};
            zts_socklen_t fromlen = sizeof(from);
            const int n = static_cast<int>(zts_bsd_recvfrom(sock, rxbuf, sizeof(rxbuf) - 1, ZTS_MSG_DONTWAIT,
                                                             (zts_sockaddr*)&from, &fromlen));
            if (n > 0) {
                rxbuf[n] = 0;
                char fromip[64] = {};
                zts_inet_ntop(ZTS_AF_INET, &from.sin_addr, fromip, sizeof(fromip));
                std::printf("[RX] from=%s:%u len=%d msg=%s\n", fromip, ntohs(from.sin_port), n, rxbuf);
                if (std::strncmp(rxbuf, "PING", 4) == 0) {
                    char pong[32];
                    const int pn = std::snprintf(pong, sizeof(pong), "PONG %.20s", rxbuf + 5);
                    zts_bsd_sendto(sock, pong, pn, 0, (zts_sockaddr*)&from, fromlen);
                }
            }
        }

        if (have_target && (elapsed - last_ping) >= 2000) {
            last_ping = elapsed;
            char msg[32];
            const int mn = std::snprintf(msg, sizeof(msg), "PING %u", ping_seq++);
            const int rc = static_cast<int>(zts_bsd_sendto(sock, msg, mn, 0, (zts_sockaddr*)&target, sizeof(target)));
            std::printf("[TX] to=%s:9994 msg=\"%s\" rc=%d\n", target_ip.c_str(), msg, rc);
        }

        if ((elapsed - last_report) >= 5000) {
            last_report = elapsed;
            std::printf("[HB] t=%llds id=%010" PRIx64 " online=%d ready=%d\n",
                        static_cast<long long>(elapsed / 1000), zts_node_get_id(),
                        zts_node_is_online(), zts_net_transport_is_ready(network_id));
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    std::printf("\nShutting down...\n");
    if (sock >= 0) zts_bsd_close(sock);
    zts_node_stop();
    for (int waited_ms = 0; !g_node_down && waited_ms < 3000; waited_ms += 50) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    std::printf("Done.\n");
    return 0;
}
