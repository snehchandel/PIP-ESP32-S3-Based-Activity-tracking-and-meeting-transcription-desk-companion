#include "dev_ota.h"

#include <stdio.h>
#include <string.h>

#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "mbedtls/sha256.h"

static const char *TAG = "ota";
static esp_ota_handle_t s_h;
static const esp_partition_t *s_part;
static uint32_t s_total, s_got;
static uint8_t s_want[32];
static mbedtls_sha256_context s_sha;
static bool s_active, s_confirmed;
static char s_last[48] = "none";

static uint32_t rd32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }

static void abort_update(const char *why)
{
    if (s_active) {
        esp_ota_abort(s_h);
        mbedtls_sha256_free(&s_sha);
    }
    s_active = false;
    snprintf(s_last, sizeof s_last, "failed: %s", why);
    ESP_LOGW(TAG, "update aborted: %s", why);
}

static void reboot_cb(void *arg) { esp_restart(); }

uint8_t dev_ota_frame(const pip_frame_t *f)
{
    switch (f->type) {
    case PIP_OTA_BEGIN: {
        if (f->len < 4 + 32) {
            return PIP_ACK_BAD_LEN;
        }
        if (s_active) {
            abort_update("restarted");
        }
        s_part = esp_ota_get_next_update_partition(NULL);
        s_total = rd32(f->payload);
        if (!s_part || s_total < 1024 || s_total > s_part->size) {
            snprintf(s_last, sizeof s_last, "failed: image size");
            return PIP_ACK_FAILED;
        }
        memcpy(s_want, f->payload + 4, 32);
        if (esp_ota_begin(s_part, s_total, &s_h) != ESP_OK) { /* erases what the image needs */
            snprintf(s_last, sizeof s_last, "failed: begin");
            return PIP_ACK_FAILED;
        }
        mbedtls_sha256_init(&s_sha);
        mbedtls_sha256_starts(&s_sha, 0);
        s_got = 0;
        s_active = true;
        ESP_LOGI(TAG, "update: %lu bytes -> %s", (unsigned long)s_total, s_part->label);
        return PIP_ACK_OK;
    }
    case PIP_OTA_DATA: {
        if (!s_active || f->len < 5) {
            return PIP_ACK_FAILED;
        }
        uint32_t off = rd32(f->payload), n = (uint32_t)f->len - 4u;
        if (off + n <= s_got) {
            return PIP_ACK_OK; /* duplicate of a chunk we already have (host retried after a lost ACK) */
        }
        if (off != s_got || off + n > s_total) {
            abort_update("out of order");
            return PIP_ACK_FAILED;
        }
        if (esp_ota_write(s_h, f->payload + 4, n) != ESP_OK) {
            abort_update("write");
            return PIP_ACK_FAILED;
        }
        mbedtls_sha256_update(&s_sha, f->payload + 4, n);
        s_got += n;
        return PIP_ACK_OK;
    }
    case PIP_OTA_END: {
        if (!s_active || s_got != s_total) {
            abort_update("incomplete");
            return PIP_ACK_FAILED;
        }
        uint8_t sum[32];
        mbedtls_sha256_finish(&s_sha, sum);
        mbedtls_sha256_free(&s_sha);
        if (memcmp(sum, s_want, 32) != 0) {
            esp_ota_abort(s_h);
            s_active = false;
            snprintf(s_last, sizeof s_last, "failed: checksum");
            return PIP_ACK_FAILED;
        }
        s_active = false;
        if (esp_ota_end(s_h) != ESP_OK || esp_ota_set_boot_partition(s_part) != ESP_OK) {
            snprintf(s_last, sizeof s_last, "failed: image invalid");
            return PIP_ACK_FAILED;
        }
        snprintf(s_last, sizeof s_last, "installed, rebooting");
        static esp_timer_handle_t t;
        const esp_timer_create_args_t ta = {.callback = reboot_cb, .name = "ota_reboot"};
        if (!t) esp_timer_create(&ta, &t);
        esp_timer_start_once(t, 800 * 1000); /* let the ACK leave first */
        return PIP_ACK_OK;
    }
    default: return PIP_ACK_UNKNOWN_TYPE;
    }
}

int dev_ota_progress(void) { return s_active && s_total ? (int)((uint64_t)s_got * 100u / s_total) : -1; }

void dev_ota_confirm_if_healthy(uint32_t uptime_ms)
{
    if (s_confirmed || uptime_ms < 20000u) {
        return;
    }
    s_confirmed = true;
    esp_ota_img_states_t st;
    const esp_partition_t *run = esp_ota_get_running_partition();
    if (esp_ota_get_state_partition(run, &st) == ESP_OK && st == ESP_OTA_IMG_PENDING_VERIFY) {
        esp_ota_mark_app_valid_cancel_rollback(); /* 20 s up and rendering: keep this firmware */
        ESP_LOGI(TAG, "new firmware confirmed");
    }
}

int dev_ota_status_json(char *out, size_t cap)
{
    const esp_partition_t *run = esp_ota_get_running_partition();
    const esp_app_desc_t *d = esp_app_get_description();
    return snprintf(out, cap, "\"ota\":{\"slot\":\"%s\",\"app_ver\":\"%s\",\"built\":\"%s %s\",\"progress\":%d,\"last\":\"%s\"}",
                    run ? run->label : "?", d->version, d->date, d->time, dev_ota_progress(), s_last);
}
