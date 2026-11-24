#include "battery_monitor.h"

#include <stdlib.h>

#include "board_pins.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_log.h"

static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_cali;
static const char *TAG = "batt";

esp_err_t battery_init(void)
{
    adc_oneshot_unit_init_cfg_t unit = {.unit_id = ADC_UNIT_1};
    esp_err_t err = adc_oneshot_new_unit(&unit, &s_adc);
    if (err != ESP_OK) {
        return err;
    }
    adc_oneshot_chan_cfg_t ch = {.atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    err = adc_oneshot_config_channel(s_adc, ADC_CHANNEL_3, &ch);
    if (err != ESP_OK) {
        return err;
    }
    adc_cali_curve_fitting_config_t cal = {
        .unit_id = ADC_UNIT_1, .chan = ADC_CHANNEL_3, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12};
    err = adc_cali_create_scheme_curve_fitting(&cal, &s_cali);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "no ADC calibration scheme: %s", esp_err_to_name(err));
        s_cali = NULL;
    }
    return ESP_OK;
}

static int cmp_int(const void *a, const void *b) { return *(const int *)a - *(const int *)b; }

int32_t battery_read_mv(void)
{
    if (!s_adc || !s_cali) {
        return -1;
    }
    int v[16];
    for (int i = 0; i < 16; i++) {
        int raw = 0;
        if (adc_oneshot_read(s_adc, ADC_CHANNEL_3, &raw) != ESP_OK ||
            adc_cali_raw_to_voltage(s_cali, raw, &v[i]) != ESP_OK) {
            return -1;
        }
    }
    qsort(v, 16, sizeof v[0], cmp_int);
    int median = (v[7] + v[8]) / 2;
    return (int32_t)median * BAT_DIVIDER_NUM / BAT_DIVIDER_DEN;
}

int battery_pct_from_mv(int32_t mv)
{
    if (mv < 0) {
        return -1;
    }
    if (mv <= BAT_MV_EMPTY) {
        return 0;
    }
    if (mv >= BAT_MV_FULL) {
        return 100;
    }
    return (int)((mv - BAT_MV_EMPTY) * 100 / (BAT_MV_FULL - BAT_MV_EMPTY));
}
