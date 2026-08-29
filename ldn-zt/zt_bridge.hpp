#pragma once

#include <cstdint>

namespace zt_bridge {

// Start the embedded ZeroTier node and join the configured network.
// Safe to call more than once; subsequent calls are no-ops.
int start();

// Stop/free the embedded ZeroTier node. Intended for sysmodule finalization.
int stop();

// Return the configured ZeroTier network ID, or 0 when not configured.
std::uint64_t network_id();

// Return the first assigned IPv4 address in LDN's uint32 representation
// (e.g. 10.48.0.146 == 0x0A300092), or 0 when not assigned yet.
std::uint32_t ipv4_address();

// Return the assigned IPv4 netmask in the same uint32 representation,
// or 0 when not assigned yet.
std::uint32_t ipv4_netmask();

} // namespace zt_bridge
