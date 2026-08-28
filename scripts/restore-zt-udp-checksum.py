from pathlib import Path

# The upstream libzt NodeService intentionally enables SO_NO_CHECK, but that
# is not a good assumption for the Switch/lwIP UDP path while debugging the
# ONLINE -> OFFLINE failure. Restore normal UDP checksums for the Switch build
# so root replies are tested against a standards-compliant UDP datagram.

found = False
for path in Path("libzt").rglob("NodeService.cpp"):
    try:
        s = path.read_text()
    except Exception:
        continue
    old = "_phy(this, false, false)"
    new = "_phy(this, false, true)"
    if old in s:
        s = s.replace(old, new, 1)
        path.write_text(s)
        print(f"Restored upstream UDP checksum setting in {path}: noCheck=true")
        found = True
        break
    if new in s:
        print(f"UDP checksum setting already restored in {path}: noCheck=true")
        found = True
        break

if not found:
    raise SystemExit("ERROR: active libzt NodeService.cpp not found or PHY constructor not recognized")
