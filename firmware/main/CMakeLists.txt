idf_component_register(
    SRCS "app_main.c" "app_controller.c" "app_gestures.c" "app_frames.c" "app_report.c"
         "dev_config.c" "net_link.c" "dev_ota.c" "dev_wake.c"
    INCLUDE_DIRS "."
    REQUIRES ui_core mascot_renderer button_gestures local_timer usb_protocol board_pins
             rlcd_display usb_transport audio_codec rtc_calendar battery_monitor
             esp_driver_gpio esp_driver_i2c esp_timer nvs_flash esp_wifi esp_netif esp_event app_update
             mbedtls lwip espressif__mdns espressif__esp-sr)
