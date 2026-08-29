cmake_minimum_required(VERSION 3.10)
project(pcdiag)

set(BUILD_STATIC_LIB ON)
set(BUILD_SHARED_LIB OFF)
set(BUILD_HOST_EXAMPLES OFF)
set(BUILD_HOST_SELFTEST OFF)
set(ALLOW_INSTALL_TARGET OFF)
set(ZTS_DISABLE_CENTRAL_API ON)

# Two gaps in stock libzt's own CMakeLists.txt on this toolchain -- see
# pc-diag/README.md. Neither is a change to libzt's behavior, just supplying
# what its own build already assumes is available.
add_compile_definitions(WIN32)
include_directories("${CMAKE_CURRENT_SOURCE_DIR}/libzt/ext/ZeroTierOne/ext")

add_subdirectory(libzt)

add_executable(pcdiag main.cpp)
target_include_directories(pcdiag PRIVATE libzt/include)
# ZeroTierSockets.h decorates every ZTS_API declaration __declspec(dllimport)
# on Windows unless ADD_EXPORTS is defined, regardless of whether the actual
# library being linked against is static or shared -- the header has no
# separate "static lib consumer" case. Defining it here isn't really asking
# for dllexport (nothing in this translation unit defines these symbols to
# export); it just avoids the dllimport decoration, which is what a static
# link needs since there's no import library backing it.
target_compile_definitions(pcdiag PRIVATE ADD_EXPORTS)
target_link_libraries(pcdiag zt-static)
