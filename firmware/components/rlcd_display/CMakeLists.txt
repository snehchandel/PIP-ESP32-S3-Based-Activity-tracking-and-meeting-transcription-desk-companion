idf_component_register(SRCS "rlcd_display.c" INCLUDE_DIRS "include"
    REQUIRES ui_core board_pins PRIV_REQUIRES esp_lcd esp_driver_spi esp_driver_gpio)
