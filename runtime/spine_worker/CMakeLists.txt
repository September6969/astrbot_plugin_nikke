cmake_minimum_required(VERSION 3.20)
project(nikke_spine_worker LANGUAGES C CXX)

set(SPINE_ROOT "/opt/spine-runtimes" CACHE PATH "官方 Spine runtimes 源码目录")

add_subdirectory("${SPINE_ROOT}/spine-cpp" "${CMAKE_BINARY_DIR}/spine-cpp" EXCLUDE_FROM_ALL)
add_subdirectory("${SPINE_ROOT}/spine-sdl" "${CMAKE_BINARY_DIR}/spine-sdl" EXCLUDE_FROM_ALL)

add_executable(nikke-spine-worker main.cpp)
target_include_directories(nikke-spine-worker PRIVATE
    "${SPINE_ROOT}/spine-cpp/spine-cpp/include"
    "${SPINE_ROOT}/spine-sdl/src"
)
target_link_libraries(nikke-spine-worker PRIVATE spine-sdl-cpp SDL2-static spine-cpp)
set_target_properties(nikke-spine-worker PROPERTIES CXX_STANDARD 11 CXX_STANDARD_REQUIRED ON)
if(NOT MSVC)
    target_compile_options(nikke-spine-worker PRIVATE -fno-exceptions -fno-rtti)
endif()
