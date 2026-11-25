/* SHTC3 temperature / humidity sensor (I2C 0x70) on the shared bus.
 * wake 0x3517 -> measure T-first, no clock stretching 0x7866 -> read 6 B (T, crc, RH, crc) -> sleep 0xB098 */
#include "board_pins.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "rtc_calendar.h"

static const char *TAG = "shtc3";
static i2c_master_dev_handle_t s_dev;

static uint8_t crc8(const uint8_t *d, int n)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < n; i++) {
        crc ^= d[i];
        for (int b = 0; b < 8; b++) {
            crc = (uint8_t)((crc & 0x80) ? ((crc << 1) ^ 0x31) : (crc << 1));
        }
    }
    return crc;
}

static esp_err_t cmd(uint16_t c)
{
    uint8_t b[2] = {(uint8_t)(c >> 8), (uint8_t)c};
    return i2c_master_transmit(s_dev, b, 2, 50);
}

esp_err_t shtc3_init(i2c_master_bus_handle_t bus)
{
    if (i2c_master_probe(bus, I2C_ADDR_SHTC3, 50) != ESP_OK) {
        ESP_LOGW(TAG, "SHTC3 not found");
        return ESP_ERR_NOT_FOUND;
    }
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = I2C_ADDR_SHTC3, .scl_speed_hz = I2C_FREQ_HZ};
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    if (err == ESP_OK) {
        cmd(0x3517);
        cmd(0xB098); /* back to sleep until the first measurement */
    }
    return err;
}

static uint32_t s_ok, s_fail;

/* one measurement: wake (harmless when already awake), measure T-first without clock stretching, read 6 bytes */
static bool read_once(int16_t *temp_c10, uint8_t *hum)
{
    uint8_t d[6];
    (void)cmd(0x3517);
    vTaskDelay(pdMS_TO_TICKS(1));
    if (cmd(0x7866) != ESP_OK) {
        return false;
    }
    vTaskDelay(pdMS_TO_TICKS(15)); /* normal-mode conversion <= 12.1 ms */
    if (i2c_master_receive(s_dev, d, 6, 50) != ESP_OK || crc8(d, 2) != d[2] || crc8(d + 3, 2) != d[5]) {
        return false;
    }
    uint32_t rt = ((uint32_t)d[0] << 8) | d[1], rh = ((uint32_t)d[3] << 8) | d[4];
    *temp_c10 = (int16_t)(-450 + (int32_t)(1750u * rt / 65536u)); /* T = -45 + 175 * raw / 2^16 */
    uint32_t h = 100u * rh / 65536u;
    *hum = (uint8_t)(h > 100u ? 100u : h);
    return true;
}

/* Field fix (BUG-017): the wake/measure/sleep cycle failed about every other read on the shared bus and the
 * header lost the indoor reading for 30 s each time. The sensor now stays awake (idle draw is negligible next to
 * the ESP32) and a failed read is retried. */
bool shtc3_read(int16_t *temp_c10, uint8_t *hum)
{
    if (!s_dev) {
        return false;
    }
    for (int attempt = 0; attempt < 3; attempt++) {
        if (read_once(temp_c10, hum)) {
            s_ok++;
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(5));
    }
    s_fail++;
    return false;
}

void shtc3_stats(uint32_t *ok, uint32_t *fail)
{
    *ok = s_ok;
    *fail = s_fail;
}
