# Host-native build of the portable firmware core: sim_rlcd + CTest unit tests.
project(pip_host C)
set(CMAKE_C_STANDARD 99)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(FW ${CMAKE_CURRENT_LIST_DIR})
set(TESTS ${FW}/../tests/unit/c)

set(PIP_WARN -Wall -Wextra -Werror -Wconversion -Wshadow -Wno-unused-parameter)

set(CORE_SRC
    ${FW}/components/usb_protocol/pip_protocol.c
    ${FW}/components/usb_protocol/json_mini.c
    ${FW}/components/button_gestures/button_gestures.c
    ${FW}/components/local_timer/local_timer.c
    ${FW}/components/mascot_renderer/mascot.c
    ${FW}/components/ui_core/ui_draw.c
    ${FW}/components/ui_core/ui_text.c
    ${FW}/components/ui_core/ui_chrome.c
    ${FW}/components/ui_core/ui_screens_a.c
    ${FW}/components/ui_core/ui_screens_b.c
    ${FW}/components/ui_core/ui_render.c
    ${FW}/components/ui_core/fonts_gen.c
    ${FW}/components/ui_core/icons_gen.c
    ${FW}/main/app_controller.c
    ${FW}/main/app_gestures.c
    ${FW}/main/app_frames.c
    ${FW}/main/app_report.c
)
set(CORE_INC
    ${FW}/components/board_pins/include
    ${FW}/components/usb_protocol/include
    ${FW}/components/button_gestures/include
    ${FW}/components/local_timer/include
    ${FW}/components/mascot_renderer/include
    ${FW}/components/ui_core/include
    ${FW}/assets/pip
    ${FW}/main
)

add_library(pip_core STATIC ${CORE_SRC})
target_include_directories(pip_core PUBLIC ${CORE_INC})
target_compile_options(pip_core PRIVATE ${PIP_WARN})
set_target_properties(pip_core PROPERTIES C_EXTENSIONS OFF)
# generated tables are exempt from -Wconversion noise but still -Werror clean
set_source_files_properties(${FW}/components/ui_core/fonts_gen.c ${FW}/components/ui_core/icons_gen.c
    PROPERTIES COMPILE_OPTIONS "-Wno-conversion")

add_executable(sim_rlcd ${FW}/sim/sim_rlcd_main.c ${FW}/sim/sim_render.c ${FW}/sim/sim_scenarios.c
    ${FW}/sim/sim_tcp.c ${FW}/sim/sim_net.c ${FW}/sim/png_write.c)
target_include_directories(sim_rlcd PRIVATE ${FW}/sim)
target_link_libraries(sim_rlcd PRIVATE pip_core)
target_compile_options(sim_rlcd PRIVATE ${PIP_WARN})
if(WIN32)
    target_link_libraries(sim_rlcd PRIVATE ws2_32)
endif()

enable_testing()
foreach(t test_protocol test_gestures test_timer test_json test_ui test_app)
    add_executable(${t} ${TESTS}/${t}.c)
    target_include_directories(${t} PRIVATE ${TESTS})
    target_link_libraries(${t} PRIVATE pip_core)
    target_compile_options(${t} PRIVATE ${PIP_WARN})
    add_test(NAME ${t} COMMAND ${t})
endforeach()
