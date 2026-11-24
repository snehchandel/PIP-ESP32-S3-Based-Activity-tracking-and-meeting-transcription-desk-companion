# Host toolchain for the portable C core + sim_rlcd: zig cc from the project venv.
# Usage: cmake -S firmware -B build/host -G Ninja -DPIP_HOST_BUILD=ON -DCMAKE_TOOLCHAIN_FILE=tools/host-toolchain.cmake
if(WIN32 OR CMAKE_HOST_WIN32)
    set(CMAKE_C_COMPILER ${CMAKE_CURRENT_LIST_DIR}/zcc.cmd)
    set(CMAKE_AR ${CMAKE_CURRENT_LIST_DIR}/zar.cmd CACHE FILEPATH "" FORCE)
    set(CMAKE_RANLIB ${CMAKE_CURRENT_LIST_DIR}/zranlib.cmd CACHE FILEPATH "" FORCE)
endif()
