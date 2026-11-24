idf_component_register(SRCS "rtc_pcf85063.c" "i2c_scan.c" INCLUDE_DIRS "include"
    REQUIRES esp_driver_i2c board_pins)
