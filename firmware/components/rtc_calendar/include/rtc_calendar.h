/* PCF85063A wall-clock RTC (stores UTC) + shared I2C bus probe helpers. */
#ifndef RTC_CALENDAR_H
#define RTC_CALENDAR_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "driver/i2c_master.h"
#include "esp_err.h"

esp_err_t pcf_rtc_init(i2c_master_bus_handle_t bus);
/* Returns UTC epoch seconds, or 0 if the RTC is absent or its clock-integrity flag is set. */
uint32_t pcf_rtc_read_epoch(void);
esp_err_t pcf_rtc_write_epoch(uint32_t epoch_s);
bool pcf_rtc_present(void);

/* Pure helpers (exposed for tests) */
uint32_t rtc_civil_to_epoch(int year, int month, int day, int hh, int mm, int ss);
void rtc_epoch_to_civil(uint32_t epoch, int *year, int *month, int *day, int *hh, int *mm, int *ss, int *wday);

/* Probe the known board addresses; writes e.g. "0x18,0x40,0x51" into out. Returns count. */
int i2c_probe_known(i2c_master_bus_handle_t bus, char *out, size_t cap, uint8_t *es7210_addr);

#endif
