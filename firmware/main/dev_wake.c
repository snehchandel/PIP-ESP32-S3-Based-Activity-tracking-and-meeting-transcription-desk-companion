#include "dev_wake.h"

#include <stdio.h>
#include <string.h>

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#include "freertos/FreeRTOS.h"
#include "freertos/stream_buffer.h"
#include "freertos/task.h"
#include "model_path.h"

static const char *TAG = "wake";
static srmodel_list_t *s_models;
static const esp_wn_iface_t *s_wn;
static model_iface_data_t *s_md;
static int s_chunk;
static StreamBufferHandle_t s_sb;
static volatile bool s_on, s_reload;
static char s_word[24] = "hiesp", s_loaded[40];
static dev_wake_cb_t s_cb;
static void *s_ctx;
static volatile int64_t s_test_until;
static volatile uint32_t s_hits;

static void load(void)
{
    if (s_md) {
        s_wn->destroy(s_md);
        s_md = NULL;
    }
    s_loaded[0] = 0;
    char *name = esp_srmodel_filter(s_models, ESP_WN_PREFIX, s_word);
    if (!name) {
        name = esp_srmodel_filter(s_models, ESP_WN_PREFIX, NULL); /* fall back to whatever is flashed */
    }
    if (!name) {
        return;
    }
    s_wn = esp_wn_handle_from_name(name);
    s_md = s_wn ? s_wn->create(name, DET_MODE_95) : NULL;
    if (s_md) {
        s_chunk = s_wn->get_samp_chunksize(s_md);
        snprintf(s_loaded, sizeof s_loaded, "%s", name);
        ESP_LOGI(TAG, "wake word model %s (chunk %d samples)", name, s_chunk);
    }
}

static void detect_task(void *arg)
{
    int16_t *buf = NULL;
    int cap = 0;
    for (;;) {
        if (s_reload) {
            s_reload = false;
            load();
            xStreamBufferReset(s_sb);
        }
        if (!s_md || (!s_on && esp_timer_get_time() > s_test_until)) {
            vTaskDelay(pdMS_TO_TICKS(100));
            continue;
        }
        if (cap < s_chunk) {
            heap_caps_free(buf);
            buf = heap_caps_malloc((size_t)s_chunk * 2, MALLOC_CAP_INTERNAL);
            cap = buf ? s_chunk : 0;
            if (!buf) {
                vTaskDelay(pdMS_TO_TICKS(500));
                continue;
            }
        }
        size_t want = (size_t)s_chunk * 2, got = 0;
        while (got < want) {
            size_t r = xStreamBufferReceive(s_sb, (uint8_t *)buf + got, want - got, pdMS_TO_TICKS(200));
            if (r == 0 && s_reload) break;
            got += r;
        }
        if (got < want) {
            continue;
        }
        if (s_wn->detect(s_md, buf) == WAKENET_DETECTED) {
            s_hits++;
            int src = esp_timer_get_time() < s_test_until ? 1 : 0;
            ESP_LOGI(TAG, "wake word detected (%s)", src ? "test" : "mic");
            xStreamBufferReset(s_sb);
            if (s_cb) s_cb(src, s_ctx);
        }
    }
}

bool dev_wake_init(dev_wake_cb_t cb, void *ctx)
{
    s_cb = cb;
    s_ctx = ctx;
    s_models = esp_srmodel_init("model");
    if (!s_models || s_models->num == 0) {
        ESP_LOGW(TAG, "no wake word models in the 'model' partition");
        return false;
    }
    s_sb = xStreamBufferCreate(16000, 2); /* ~0.5 s of audio */
    load();
    xTaskCreatePinnedToCore(detect_task, "wake", 6144, NULL, 4, NULL, 0);
    return s_md != NULL;
}

void dev_wake_configure(bool enabled, const char *word)
{
    if (word && word[0] && strcmp(word, s_word) != 0) {
        snprintf(s_word, sizeof s_word, "%s", word);
        s_reload = true;
    }
    s_on = enabled;
}

bool dev_wake_active(void) { return s_on && s_md != NULL; }

void dev_wake_feed(const int16_t *pcm, size_t n)
{
    if (s_on && s_md && s_sb && esp_timer_get_time() > s_test_until) {
        xStreamBufferSend(s_sb, pcm, n * 2, 0);
    }
}

void dev_wake_test_feed(const int16_t *pcm, size_t n)
{
    if (!s_md || !s_sb) {
        return;
    }
    s_test_until = esp_timer_get_time() + 2000000; /* the mic pauses while a test clip streams in */
    xStreamBufferSend(s_sb, pcm, n * 2, pdMS_TO_TICKS(500));
}

int dev_wake_status_json(char *out, size_t cap)
{
    int n = snprintf(out, cap, "\"wake\":{\"enabled\":%s,\"ready\":%s,\"word\":\"%s\",\"model\":\"%s\",\"hits\":%lu,\"words\":[",
                     s_on ? "true" : "false", s_md ? "true" : "false", s_word, s_loaded, (unsigned long)s_hits);
    for (int i = 0; s_models && i < s_models->num && n > 0 && (size_t)n < cap; i++) {
        const char *m = s_models->model_name[i];
        if (strncmp(m, "wn", 2) != 0) continue;
        const char *k = strchr(m, '_'); /* wn9_jarvis_tts -> jarvis */
        char word[24];
        snprintf(word, sizeof word, "%s", k ? k + 1 : m);
        char *u = strchr(word, '_');
        if (u) *u = 0;
        n += snprintf(out + n, cap - (size_t)n, "%s\"%s\"", out[n - 1] == '[' ? "" : ",", word);
    }
    if (n > 0 && (size_t)n < cap) {
        n += snprintf(out + n, cap - (size_t)n, "]}");
    }
    return n;
}
