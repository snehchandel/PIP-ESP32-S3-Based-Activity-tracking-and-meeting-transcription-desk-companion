idf_component_register(SRCS "usb_transport.c" INCLUDE_DIRS "include"
    REQUIRES usb_protocol PRIV_REQUIRES esp_driver_usb_serial_jtag)
