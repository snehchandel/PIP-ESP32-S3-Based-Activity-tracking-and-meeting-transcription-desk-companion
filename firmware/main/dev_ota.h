/* Firmware update over the protocol link (USB or Wi-Fi): PIP_OTA_BEGIN / PIP_OTA_DATA / PIP_OTA_END write the
 * inactive app slot, check the whole image's SHA-256, switch the boot slot and reboot. With
 * CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE the new image boots in PENDING_VERIFY and is only kept once it has run
 * healthily (dev_ota_confirm_if_healthy); a crash or reset before that rolls back to the previous firmware. */
#ifndef DEV_OTA_H
#define DEV_OTA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "pip_protocol.h"

/* Handle one OTA frame; returns the ACK status to send back (PIP_ACK_OK / FAILED / BUSY). */
uint8_t dev_ota_frame(const pip_frame_t *f);
int dev_ota_progress(void); /* -1 idle, else 0..100 */
void dev_ota_confirm_if_healthy(uint32_t uptime_ms);
int dev_ota_status_json(char *out, size_t cap);

#endif
