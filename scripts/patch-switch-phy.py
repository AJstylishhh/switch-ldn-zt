from pathlib import Path

# The upstream libzt VirtualTap constructs its physical UDP layer with
# noCheck=true. On Nintendo Switch we want normal IPv4 UDP checksums while
# debugging the ZeroTier root path; some network stacks/NATs are less tolerant
# of checksum-disabled UDP than desktop clients.

candidates = list(Path("libzt").rglob("VirtualTap.cpp"))
path = None
for p in candidates:
    try:
        s = p.read_text()
    except Exception:
        continue
    if "_phy(this, false, true)" in s and "class VirtualTap" not in s:
        # Source file may not contain the class declaration; accept the file
        # based on the constructor initializer below.
        path = p
        break
    if "_phy(this, false, true)" in s:
        path = p
        break

if path is None:
    raise SystemExit("ERROR: could not find libzt VirtualTap.cpp with _phy(this, false, true)")

s = path.read_text()
needle = "_phy(this, false, true)"
count = s.count(needle)
if count != 1:
    raise SystemExit(f"ERROR: expected exactly one {needle}, found {count} in {path}")

s = s.replace(needle, "_phy(this, false, false)", 1)
path.write_text(s)
print(f"Switch PHY patch: disabled SO_NO_CHECK in {path}")
