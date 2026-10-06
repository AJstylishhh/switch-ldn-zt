# Sys B hardware results

Title: `4200000000000011`

| Phase | libzt | What | Result |
|-------|-------|------|--------|
| Skeleton | none | AMS hooks only | Boot OK |
| Phase 1 | `76c138b` (pre-shrink) | link only, no `zts_*` | Boot OK |
| Phase 2 | `76c138b` | `zts_init_from_storage` | **Logo 0xffe** |
| **Phase 2b** | **`1aa9ada` / `>=664bfa9`** | sysmodule-fit lib + init only | **test this** |

## Phase 2b install

Artifact: `zerotier-sysmodule-phase2b`

```
atmosphere/contents/4200000000000011/exefs.nsp
atmosphere/contents/4200000000000011/flags/boot2.flag
atmosphere/contents/4200000000000011/toolbox.json
```

Optional: `sdmc:/config/switch-ldn-zt/`

## Recover

Delete or rename `atmosphere/contents/4200000000000011/`.

## Notes

- nx-mod credits switch-ldn-zt for the original Switch port; sysmodule shrink is theirs.
- Still no `node_start` / join until init boots clean.
