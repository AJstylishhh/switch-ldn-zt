# Sys B Phase 2c — deferred enable

Title: `4200000000000011`

## Install

Artifact: `zerotier-sysmodule-phase2c`

```
atmosphere/contents/4200000000000011/exefs.nsp
atmosphere/contents/4200000000000011/flags/boot2.flag
atmosphere/contents/4200000000000011/toolbox.json
```

**Do not** create the enable file before first boot test.

## Test 1 — stay alive (required)

1. Install as above.
2. Ensure **no** file: `sdmc:/config/switch-ldn-zt/enable`
3. Boot CFW.

| Result | Meaning |
|--------|--------|
| Home menu OK, Ultrahand shows module on | Phase 2c boot path OK |
| Logo 0xffe | Linking `zts_*` still pulls fatal static init — stop |

## Test 2 — enable ZT after boot (only if Test 1 passed)

1. On SD (FTP/USB): create empty file
   `sdmc:/config/switch-ldn-zt/enable`
2. Wait a few seconds (module polls every 2s). No reboot required.
3. If console fatals after enable → init still unsafe even deferred.
4. If stays up → init survived; next is node_start (later).

## Recover

Delete `atmosphere/contents/4200000000000011/` or remove `enable` + reboot.

## Not in this build

- Network join / Central online
- Games / LDN
- `zts_node_start`
