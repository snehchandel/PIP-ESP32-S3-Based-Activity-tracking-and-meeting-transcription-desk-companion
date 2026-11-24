#include <stdio.h>

#include "board_pins.h"
#include "rtc_calendar.h"

int i2c_probe_known(i2c_master_bus_handle_t bus, char *out, size_t cap, uint8_t *es7210_addr)
{
    static const uint8_t addrs[] = {I2C_ADDR_ES8311, I2C_ADDR_ES7210, I2C_ADDR_ES7210_ALT, I2C_ADDR_PCF85063,
                                    I2C_ADDR_SHTC3};
    size_t n = 0;
    int found = 0;
    if (cap) {
        out[0] = 0;
    }
    if (es7210_addr) {
        *es7210_addr = 0;
    }
    for (size_t i = 0; i < sizeof addrs; i++) {
        if (i2c_master_probe(bus, addrs[i], 30) == ESP_OK) {
            int w = snprintf(out + n, cap - n, "%s0x%02X", found ? "," : "", addrs[i]);
            if (w > 0 && (size_t)w < cap - n) {
                n += (size_t)w;
            }
            found++;
            if (es7210_addr && !*es7210_addr && (addrs[i] == I2C_ADDR_ES7210 || addrs[i] == I2C_ADDR_ES7210_ALT)) {
                *es7210_addr = addrs[i];
            }
        }
    }
    return found;
}
