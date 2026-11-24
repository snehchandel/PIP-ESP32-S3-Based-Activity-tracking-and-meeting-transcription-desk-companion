idf_component_register(
    SRCS "app_main.c" "app_controller.c" "app_gestures.c" "app_frames.c"
    INCLUDE_DIRS "."
    REQUIRES ui_core mascot_renderer button_gestures local_timer usb_protocol board_pins
             rlcd_display usb_transport audio_codec rtc_calendar battery_monitor
             esp_driver_gpio esp_driver_i2c esp_timer)
