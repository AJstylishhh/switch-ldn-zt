# CMake toolchain file for cross-compiling to Nintendo Switch (libnx / devkitA64).
#
# Usage:
#   cmake -DCMAKE_TOOLCHAIN_FILE=cmake/switch.toolchain.cmake ...
#
# Assumes the devkitpro/devkita64 Docker image (or a normal devkitPro install) where
# the DEVKITPRO environment variable is already set, e.g. /opt/devkitpro

if(NOT DEFINED ENV{DEVKITPRO})
    message(FATAL_ERROR "DEVKITPRO environment variable is not set. Install devkitPro / use the devkitpro/devkita64 Docker image.")
endif()

set(DEVKITPRO $ENV{DEVKITPRO})
set(DEVKITA64 ${DEVKITPRO}/devkitA64)

# We're cross-compiling to a bare-metal-ish target (no full OS as far as CMake is
# concerned), so "Generic" avoids CMake trying to run Linux/UNIX-specific checks.
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

set(CMAKE_C_COMPILER   ${DEVKITA64}/bin/aarch64-none-elf-gcc)
set(CMAKE_CXX_COMPILER ${DEVKITA64}/bin/aarch64-none-elf-g++)
set(CMAKE_ASM_COMPILER ${DEVKITA64}/bin/aarch64-none-elf-gcc)
set(CMAKE_AR           ${DEVKITA64}/bin/aarch64-none-elf-ar CACHE FILEPATH "Archiver")

# CMake's default compiler sanity check tries to link+run a test executable, which
# doesn't make sense for a Switch target from within a build container. Restricting
# it to a static library test sidesteps that.
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# Standard libnx flags, same ones devkitPro's own Makefiles use for Switch homebrew.
set(SWITCH_ARCH_FLAGS "-march=armv8-a -mtune=cortex-a57 -mtp=soft -fPIE")
set(SWITCH_DEFINES "-D__SWITCH__ -DSWITCH")

set(CMAKE_C_FLAGS   "${SWITCH_ARCH_FLAGS} ${SWITCH_DEFINES} -U__STRICT_ANSI__" CACHE STRING "")
set(CMAKE_CXX_FLAGS "${SWITCH_ARCH_FLAGS} ${SWITCH_DEFINES} -fno-rtti -U__STRICT_ANSI__" CACHE STRING "")

set(CMAKE_EXE_LINKER_FLAGS "-specs=${DEVKITPRO}/libnx/switch.specs" CACHE STRING "")

# Where to find libnx headers/libs and any portlibs (e.g. if we need extra deps later).
set(CMAKE_FIND_ROOT_PATH
    ${DEVKITPRO}/libnx
    ${DEVKITPRO}/portlibs/switch
)
include_directories(
    ${DEVKITPRO}/libnx/include
    ${DEVKITPRO}/portlibs/switch/include
)
link_directories(
    ${DEVKITPRO}/libnx/lib
    ${DEVKITPRO}/portlibs/switch/lib
)

set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)

# NOTE: this file is a first attempt, not verified against a real build yet.
# If configure/build fails, the error output tells us exactly what to fix here —
# that's expected and is the point of running it in CI.
