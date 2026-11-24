/* GPIO4 / ADC1_CH3 battery sense with 16-sample median filter and linear % mapping. */
#ifndef BATTERY_MONITOR_H
#define BATTERY_MONITOR_H

#include <stdint.h>

#include "esp_err.h"

esp_err_t battery_init(void);
/* Battery voltage in mV (median of 16 samples x divider), or -1 if unavailable. */
int32_t battery_read_mv(void);
/* Linear map BAT_MV_EMPTY..BAT_MV_FULL -> 0..100, or -1 if unavailable. */
int battery_pct_from_mv(int32_t mv);

#endif
