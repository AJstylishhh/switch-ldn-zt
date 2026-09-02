# Sys B hardware results

Title: `4200000000000011`

| Phase | What | Result |
|-------|------|--------|
| Skeleton (no libzt) | AMS hooks only | Boot OK |
| Phase 1 | libzt linked, **no** `zts_*` | Boot OK |
| Phase 2 | `zts_init_from_storage` | **Logo 0xffe** |

Conclusion: linking `libzt.a` is fine; **any real `zts_*` reference** pulls objects that abort at sysmodule load (same class of failure as full ZT inside ldn_mitm).

NRO ZeroTier still works but does not stay up in-game.

## Recover from bad build
Delete or rename `atmosphere/contents/4200000000000011/` (or only `flags/boot2.flag`).
