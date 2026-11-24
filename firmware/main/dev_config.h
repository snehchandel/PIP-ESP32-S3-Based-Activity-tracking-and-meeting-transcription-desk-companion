/* Device settings that survive reboots (NVS namespace "pip"): Wi-Fi credentials, the LAN link token shared
 * with the PC (HMAC key for the Wi-Fi link), and the wake-word choice. Provisioned by the PC with a
 * PIP_DEVICE_CONFIG frame - over USB the first time. */
#ifndef DEV_CONFIG_H
#define DEV_CONFIG_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "esp_err.h"

typedef struct {
    char ssid[33];
    char pass[65];
    uint8_t token[32];
    bool has_token;
    bool wake_on;
    char wake_word[24]; /* model keyword, e.g. "hiesp", "jarvis", "computer", "hijoy" */
} dev_config_t;

esp_err_t dev_config_init(void); /* nvs_flash_init (erases a stale/foreign NVS layout) */
void dev_config_load(dev_config_t *c);
esp_err_t dev_config_save(const dev_config_t *c);

/* Apply a PIP_DEVICE_CONFIG JSON payload onto *c. Returns true if anything changed;
 * *wifi_changed / *wake_changed tell the caller what to re-apply. */
bool dev_config_apply_json(dev_config_t *c, const char *json, size_t n, bool *wifi_changed, bool *wake_changed);

#endif
