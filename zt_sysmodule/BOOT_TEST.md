# Sys B boot test notes

Title ID: `4200000000000011`

## Phase 1 (passed on hardware)
- libzt linked, **no** `zts_*` calls
- Logo boot OK with LDN #40 at `4200000000000010`
- ZeroTier Central offline (expected)

## Phase 2 (current)
- Calls **only** `zts_init_from_storage("sdmc:/config/switch-ldn-zt")` from `Main()`
- No `zts_node_start`, no join, no wait loops
- Failure of init must not abort the sysmodule
- Central may still be offline (node not started)

### Install
```
atmosphere/contents/4200000000000011/exefs.nsp
atmosphere/contents/4200000000000011/flags/boot2.flag
atmosphere/contents/4200000000000011/toolbox.json
```

Optional: create empty folder `sdmc:/config/switch-ldn-zt/` on the SD.

### Recover if logo crash
Remove or rename `atmosphere/contents/4200000000000011/` (or only `flags/boot2.flag`) via SD/Hekate.
