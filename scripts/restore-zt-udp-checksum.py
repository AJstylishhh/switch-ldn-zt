from pathlib import Path

# Restore upstream libzt UDP checksum behavior for the Switch build.
# This script must remain independent of experimental auth tracing so CI can
# always produce a green NRO while we debug the runtime OFFLINE transition.

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

# Deliberately do not invoke the experimental IncomingPacket auth tracer here.
# The current vendored ZeroTier source layout does not match that tracer, and
# a diagnostic script must never be allowed to break the production build.
print("IncomingPacket auth trace: disabled for green-build baseline")
