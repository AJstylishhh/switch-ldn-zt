# Sys B boot test

Phase 1 is a pure Atmosphere sysmodule skeleton. It intentionally links no libzt and compiles no ZeroTier compatibility sources.

Install the CI skeleton artifact and boot Atmosphere. The goal is a clean logo boot with no Sys B crash.

## Emergency disable

Sys B is auto-loaded by:

`atmosphere/contents/4200000000000011/flags/boot2.flag`

To stop Sys B from auto-loading, remove this file from the SD card:

`atmosphere/contents/4200000000000011/flags/boot2.flag`

Do not proceed to the next isolation phase until the skeleton boot test is successful.
