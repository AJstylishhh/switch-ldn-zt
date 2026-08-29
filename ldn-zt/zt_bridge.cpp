#include "zt_bridge.hpp"

#include <ZeroTierSockets.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <arpa/inet.h>

namespace {

std::uint64_t g_network_id = 0;
bool g_started = false;

bool read_network_id(std::uint64_t& out)
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

    out = static_cast<std::uint64_t>(value);
    return true;
}

} // namespace

namespace zt_bridge {

int start()
{
    if (g_started) return ZTS_ERR_OK;

    if (!read_network_id(g_network_id)) {
        std::printf("[LDN-ZT] network_id.txt missing/invalid\n");
        return ZTS_ERR_ARG;
    }

    int rc = zts_init_from_storage("sdmc:/config/zerotier-switch/zt");
    if (rc != ZTS_ERR_OK) {
        std::printf("[LDN-ZT] zts_init_from_storage=%d\n", rc);
        return rc;
    }

    rc = zts_init_set_port(9993);
    if (rc != ZTS_ERR_OK) return rc;

    zts_init_allow_secondary_port(1);
    zts_init_allow_port_mapping(1);

    rc = zts_node_start();
    if (rc != ZTS_ERR_OK) {
        std::printf("[LDN-ZT] zts_node_start=%d\n", rc);
        return rc;
    }

    rc = zts_net_join(g_network_id);
    if (rc != ZTS_ERR_OK) {
        std::printf("[LDN-ZT] zts_net_join=%d net=%llx\n", rc,
                    static_cast<unsigned long long>(g_network_id));
        zts_node_stop();
        return rc;
    }

    g_started = true;
    std::printf("[LDN-ZT] ZeroTier started net=%llx\n",
                static_cast<unsigned long long>(g_network_id));
    return ZTS_ERR_OK;
}

int stop()
{
    if (!g_started) return ZTS_ERR_OK;
    g_started = false;
    const int rc = zts_node_free();
    g_network_id = 0;
    return rc;
}

std::uint64_t network_id()
{
    return g_network_id;
}

std::uint32_t ipv4_address()
{
    if (!g_started || g_network_id == 0) return 0;

    zts_sockaddr_storage storage{};
    if (zts_addr_get(g_network_id, ZTS_AF_INET, &storage) != ZTS_ERR_OK) return 0;

    const auto* addr = reinterpret_cast<const zts_sockaddr_in*>(&storage);
    return ntohl(addr->sin_addr.s_addr);
}

std::uint32_t ipv4_netmask()
{
    if (!g_started || g_network_id == 0) return 0;

    zts_sockaddr_storage storage{};
    if (zts_addr_get(g_network_id, ZTS_AF_INET, &storage) != ZTS_ERR_OK) return 0;

    const auto* addr = reinterpret_cast<const zts_sockaddr_in*>(&storage);
    const unsigned int prefix = ntohs(addr->sin_port);
    if (prefix == 0 || prefix > 32) return 0;
    return prefix == 32 ? 0xFFFFFFFFu : (0xFFFFFFFFu << (32 - prefix));
}

} // namespace zt_bridge
