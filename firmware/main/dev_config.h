/* Device settings that survive reboots (NVS namespace "pip"): saved Wi-Fi networks, the link token shared with
 * the PC (key for the Wi-Fi and away links), the wake-word choice and the away-link address. The struct and the
 * DEVICE_CONFIG JSON live in dev_settings.h (portable); this file is the NVS persistence. Provisioned by the PC
 * with a PIP_DEVICE_CONFIG frame - over USB the first time. */
#ifndef DEV_CONFIG_H
#define DEV_CONFIG_H

#include "dev_settings.h"
#include "esp_err.h"

esp_err_t dev_config_init(void); /* nvs_flash_init (erases a stale/foreign NVS layout) */
void dev_config_load(dev_config_t *c);
esp_err_t dev_config_save(const dev_config_t *c);

#endif
