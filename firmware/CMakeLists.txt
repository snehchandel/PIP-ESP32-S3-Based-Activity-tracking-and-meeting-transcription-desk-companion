# Dual-target build:
#   ESP-IDF:  idf.py -C firmware build                (ESP32-S3 firmware)
#   Host:     cmake -S firmware -B build/host -DPIP_HOST_BUILD=ON   (sim_rlcd + C unit tests)
cmake_minimum_required(VERSION 3.16)

if(PIP_HOST_BUILD)
    include(${CMAKE_CURRENT_LIST_DIR}/host.cmake)
else()
    set(PROJECT_VER "1.4.0") # keep in sync with APP_FW_VERSION (main/app_controller.h)
    include($ENV{IDF_PATH}/tools/cmake/project.cmake)
    project(pip_firmware)
endif()
