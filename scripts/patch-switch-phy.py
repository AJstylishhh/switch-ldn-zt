from pathlib import Path

# ZeroTier's libzt service owns the physical UDP transport in src/NodeService.cpp.
# The older patch targeted ZeroTierOne/node/VirtualTap.cpp, but this Switch build
# removes that ZeroTierOne source from the core object list. Therefore that change
# did not affect the socket actually used by zts_node_start().
#
# Test the real PHY constructor by disabling SO_NO_CHECK there as well. Keep the
# old VirtualTap patch for compatibility with libzt revisions that still use it.

patched = False

for path in Path("libzt").rglob("NodeService.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue
    needle = "_phy(this, false, true)"
    if needle in s:
        if s.count(needle) != 1:
            raise SystemExit(f"ERROR: expected one {needle} in {path}, found {s.count(needle)}")
        s = s.replace(needle, "_phy(this, false, false)", 1)
        path.write_text(s)
        print(f"Switch PHY patch: disabled SO_NO_CHECK in active libzt NodeService: {path}")
        patched = True
        break

# Also patch the legacy ZeroTierOne VirtualTap when present. This is harmless if
# that source is not linked, and preserves compatibility with older layouts.
for path in Path("libzt").rglob("VirtualTap.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue
    needle = "_phy(this, false, true)"
    if needle in s:
        if s.count(needle) != 1:
            raise SystemExit(f"ERROR: expected one {needle} in {path}, found {s.count(needle)}")
        s = s.replace(needle, "_phy(this, false, false)", 1)
        path.write_text(s)
        print(f"Switch PHY patch: disabled SO_NO_CHECK in legacy VirtualTap: {path}")
        patched = True
        break

if not patched:
    raise SystemExit("ERROR: could not find an active ZeroTier PHY constructor with noCheck=true")
