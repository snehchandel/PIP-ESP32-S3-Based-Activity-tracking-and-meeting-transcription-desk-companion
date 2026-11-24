idf_component_register(SRCS "audio_codec.c" "chimes.c" INCLUDE_DIRS "include"
    REQUIRES esp_driver_i2c board_pins PRIV_REQUIRES esp_driver_i2s esp_driver_gpio esp_codec_dev)
