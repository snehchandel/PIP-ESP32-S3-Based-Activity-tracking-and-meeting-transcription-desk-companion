#include "board_pins.h"
#include "esp_log.h"
#include "rtc_calendar.h"

static const char *TAG = "rtc";
static i2c_master_dev_handle_t s_dev;
static bool s_present;

static uint8_t bcd2bin(uint8_t v) { return (uint8_t)((v >> 4) * 10 + (v & 0x0F)); }
static uint8_t bin2bcd(int v) { return (uint8_t)(((v / 10) << 4) | (v % 10)); }

/* days-from-civil (Howard Hinnant), valid for 1970..2099 */
uint32_t rtc_civil_to_epoch(int y, int m, int d, int hh, int mm, int ss)
{
    y -= m <= 2;
    int era = y / 400;
    int yoe = y - era * 400;
    int doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
    int doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    long days = (long)era * 146097L + doe - 719468L;
    return (uint32_t)(days * 86400L + hh * 3600L + mm * 60L + ss);
}

void rtc_epoch_to_civil(uint32_t epoch, int *year, int *month, int *day, int *hh, int *mm, int *ss, int *wday)
{
    long days = (long)(epoch / 86400u);
    long rem = (long)(epoch % 86400u);
    *hh = (int)(rem / 3600);
    *mm = (int)((rem / 60) % 60);
    *ss = (int)(rem % 60);
    *wday = (int)((days + 4) % 7); /* 1970-01-01 was a Thursday */
    days += 719468;
    long era = days / 146097;
    long doe = days - era * 146097;
    long yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    long doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    long mp = (5 * doy + 2) / 153;
    *day = (int)(doy - (153 * mp + 2) / 5 + 1);
    *month = (int)(mp < 10 ? mp + 3 : mp - 9);
    *year = (int)(yoe + era * 400 + (*month <= 2));
}

esp_err_t pcf_rtc_init(i2c_master_bus_handle_t bus)
{
    if (i2c_master_probe(bus, I2C_ADDR_PCF85063, 50) != ESP_OK) {
        ESP_LOGW(TAG, "PCF85063A not found at 0x%02X", I2C_ADDR_PCF85063);
        return ESP_ERR_NOT_FOUND;
    }
    i2c_device_config_t cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = I2C_ADDR_PCF85063, .scl_speed_hz = I2C_FREQ_HZ};
    esp_err_t err = i2c_master_bus_add_device(bus, &cfg, &s_dev);
    if (err == ESP_OK) {
        uint8_t ctrl1[2] = {0x00, 0x00}; /* Control_1: normal mode, clock running, 24h */
        err = i2c_master_transmit(s_dev, ctrl1, 2, 50);
    }
    s_present = err == ESP_OK;
    return err;
}

bool pcf_rtc_present(void) { return s_present; }

uint32_t pcf_rtc_read_epoch(void)
{
    if (!s_present) {
        return 0;
    }
    uint8_t reg = 0x04, t[7];
    if (i2c_master_transmit_receive(s_dev, &reg, 1, t, 7, 50) != ESP_OK) {
        return 0;
    }
    if (t[0] & 0x80) { /* OS flag: oscillator stopped, time invalid */
        return 0;
    }
    int ss = bcd2bin(t[0] & 0x7F), mm = bcd2bin(t[1] & 0x7F), hh = bcd2bin(t[2] & 0x3F);
    int day = bcd2bin(t[3] & 0x3F), mon = bcd2bin(t[5] & 0x1F), yr = 2000 + bcd2bin(t[6]);
    if (mon < 1 || mon > 12 || day < 1 || day > 31 || yr < 2024) {
        return 0;
    }
    return rtc_civil_to_epoch(yr, mon, day, hh, mm, ss);
}

esp_err_t pcf_rtc_write_epoch(uint32_t epoch_s)
{
    if (!s_present) {
        return ESP_ERR_INVALID_STATE;
    }
    int y, mo, d, hh, mm, ss, wd;
    rtc_epoch_to_civil(epoch_s, &y, &mo, &d, &hh, &mm, &ss, &wd);
    uint8_t b[8] = {0x04, bin2bcd(ss), bin2bcd(mm), bin2bcd(hh), bin2bcd(d), (uint8_t)wd, bin2bcd(mo), bin2bcd(y - 2000)};
    return i2c_master_transmit(s_dev, b, sizeof b, 50);
}
