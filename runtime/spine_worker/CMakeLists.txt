cmake_minimum_required(VERSION 3.20)
project(nikke_spine_worker LANGUAGES C CXX)

set(SPINE_ROOT "/opt/spine-runtimes" CACHE PATH "官方 Spine 4.0 源码目录")
set(SFML_ROOT "/opt/SFML-2.5.1" CACHE PATH "官方 SFML 2.5.1 目录")

add_subdirectory("${SPINE_ROOT}/spine-cpp" "${CMAKE_BINARY_DIR}/spine-cpp" EXCLUDE_FROM_ALL)
add_library(spine-sfml-cpp STATIC
    "${SPINE_ROOT}/spine-sfml/cpp/src/spine/spine-sfml.cpp"
    "${SPINE_ROOT}/spine-sfml/cpp/src/spine/spine-sfml.h"
)
target_include_directories(spine-sfml-cpp PUBLIC
    "${SPINE_ROOT}/spine-sfml/cpp/src"
    "${SPINE_ROOT}/spine-cpp/spine-cpp/include"
    "${SFML_ROOT}/include"
)
target_link_directories(spine-sfml-cpp PUBLIC "${SFML_ROOT}/lib")
target_link_libraries(spine-sfml-cpp PUBLIC spine-cpp sfml-graphics sfml-window sfml-system)

add_executable(nikke-spine-worker main.cpp)
target_include_directories(nikke-spine-worker PRIVATE
    "${SPINE_ROOT}/spine-sfml/cpp/src"
    "${SPINE_ROOT}/spine-cpp/spine-cpp/include"
    "${SFML_ROOT}/include"
)
target_link_directories(nikke-spine-worker PRIVATE "${SFML_ROOT}/lib")
target_link_libraries(nikke-spine-worker PRIVATE
    spine-sfml-cpp spine-cpp sfml-graphics sfml-window sfml-system
    freetype GL X11 Xrandr Xcursor Xi udev openal vorbisenc vorbisfile vorbis ogg
)
set_target_properties(nikke-spine-worker PROPERTIES CXX_STANDARD 11 CXX_STANDARD_REQUIRED ON)
if(NOT MSVC)
    target_compile_options(spine-sfml-cpp PRIVATE -fno-exceptions -fno-rtti)
    target_compile_options(nikke-spine-worker PRIVATE -fno-exceptions -fno-rtti)
endif()
