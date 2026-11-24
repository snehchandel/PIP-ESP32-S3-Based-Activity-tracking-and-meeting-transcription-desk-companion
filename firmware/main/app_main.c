/* Thin FreeRTOS wiring: hardware adapters <-> portable app_controller.
 * Core 0: USB rx + audio. Core 1: UI render, timer, buttons, RTC, battery. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"
#include "audio_codec.h"
#include "battery_monitor.h"
#include "board_pins.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "rlcd_display.h"
#include "rtc_calendar.h"
#include "usb_transport.h"

static const char *TAG = "pip";
static app_t s_app;
static SemaphoreHandle_t s_lock;
static QueueHandle_t s_chime_q;
static i2c_master_bus_handle_t s_i2c;
static char s_i2c_found[48];
static bool s_display_ok;
static volatile bool s_capture;
static volatile uint32_t s_stream;
static int32_t s_batt_mv = -1;

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static void lock(void) { xSemaphoreTake(s_lock, portMAX_DELAY); }
static void unlock(void) { xSemaphoreGive(s_lock); }

static void io_send(void *ctx, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *p, uint16_t len)
{
    usb_transport_send(type, flags, seq, p, len);
}

static void io_chime(void *ctx, uint8_t id) { xQueueSend(s_chime_q, &id, 0); }

static void io_capture(void *ctx, bool start, uint32_t stream_id)
{
    s_stream = stream_id;
    s_capture = start;
    audio_set_capture(start);
}

static const char *reset_reason(void)
{
    switch (esp_reset_reason()) {
    case ESP_RST_POWERON: return "POWERON";
    case ESP_RST_SW: return "SW";
    case ESP_RST_PANIC: return "PANIC";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT";
    case ESP_RST_USB: return "USB";
    case ESP_RST_DEEPSLEEP: return "DEEPSLEEP";
    default: return "OTHER";
    }
}

static void io_diag(void *ctx, app_diag_t *d)
{
    d->free_heap_b = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    d->free_psram_b = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    d->batt_mv = s_batt_mv;
    d->rtc_ok = pcf_rtc_present();
    d->display_ok = s_display_ok;
    d->audio_ok = audio_ok();
    snprintf(d->i2c_addrs, sizeof d->i2c_addrs, "%s", s_i2c_found);
    snprintf(d->reset_reason, sizeof d->reset_reason, "%s", reset_reason());
}

static void on_frame(const pip_frame_t *f, void *ctx)
{
    lock();
    s_app.now_ms = now_ms();
    s_app.crc_errors = usb_transport_crc_errors();
    app_on_frame(&s_app, f);
    unlock();
}

static void ui_task(void *arg)
{
    uint32_t last_batt = 0, last_rtc_sync = 0;
    for (;;) {
        uint32_t t = now_ms();
        lock();
        app_button_sample(&s_app, BTN_KEY, gpio_get_level(PIN_KEY) == 0, t);
        app_button_sample(&s_app, BTN_BOOT, gpio_get_level(PIN_BOOT) == 0, t);
        app_tick(&s_app, t);
        if (t - last_batt >= 10000u || last_batt == 0) {
            last_batt = t;
            s_batt_mv = battery_read_mv();
            app_set_battery(&s_app, battery_pct_from_mv(s_batt_mv));
        }
        if (s_app.epoch_valid && s_app.m.link == LINK_TETHERED && t - last_rtc_sync >= 60000u) {
            last_rtc_sync = t;
            uint32_t host = app_epoch_now(&s_app), rtc = pcf_rtc_read_epoch();
            if (pcf_rtc_present() && (rtc > host + 2u || host > rtc + 2u)) {
                pcf_rtc_write_epoch(host);
            }
        }
        bool flush = app_render_if_dirty(&s_app);
        unlock();
        if (flush && s_display_ok) {
            rlcd_display_flush(&s_app.fb); /* only the ui task renders, so fb is stable here */
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}

static void audio_task(void *arg)
{
    static int16_t mono[AUDIO_CHUNK_SAMPLES];
    static uint8_t pkt[6 + AUDIO_CHUNK_BYTES];
    bool was = false;
    uint16_t chunk = 0;
    uint32_t samples = 0, stream = 0;
    for (;;) {
        if (s_capture && audio_ok()) {
            if (!was) {
                was = true;
                chunk = 0;
                samples = 0;
                stream = s_stream;
            }
            if (audio_read_chunk(mono) == ESP_OK) {
                memcpy(pkt, &stream, 4); /* little-endian target */
                memcpy(pkt + 4, &chunk, 2);
                memcpy(pkt + 6, mono, AUDIO_CHUNK_BYTES);
                chunk++;
                samples += AUDIO_CHUNK_SAMPLES;
                lock();
                app_set_audio_level(&s_app, audio_level_bars(mono, AUDIO_CHUNK_SAMPLES));
                app_send(&s_app, PIP_AUDIO_DATA, false, pkt, sizeof pkt);
                unlock();
            }
            continue;
        }
        if (was) {
            was = false;
            pip_audio_end_t e = {stream, 0, (uint8_t)(samples >= 60u * AUDIO_RATE_HZ), 0, samples};
            uint8_t b[12];
            lock();
            app_send(&s_app, PIP_AUDIO_END, true, b, (uint16_t)pip_pack_audio_end(&e, b));
            unlock();
        }
        uint8_t id;
        if (xQueueReceive(s_chime_q, &id, pdMS_TO_TICKS(20)) == pdTRUE && audio_ok()) {
            audio_play_chime(id, 70);
        }
    }
}

static void buttons_init(void)
{
    gpio_config_t io = {
        .pin_bit_mask = (1ULL << PIN_KEY) | (1ULL << PIN_BOOT),
        .mode = GPIO_MODE_INPUT,
        .pull_up_en = GPIO_PULLUP_ENABLE,
    };
    gpio_config(&io);
}

static void i2c_init(void)
{
    i2c_master_bus_config_t cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = PIN_I2C_SDA,
        .scl_io_num = PIN_I2C_SCL,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    ESP_ERROR_CHECK(i2c_new_master_bus(&cfg, &s_i2c));
}

void app_main(void)
{
    s_lock = xSemaphoreCreateMutex();
    s_chime_q = xQueueCreate(4, sizeof(uint8_t));
    buttons_init();
    i2c_init();
    uint8_t es7210 = 0;
    int found = i2c_probe_known(s_i2c, s_i2c_found, sizeof s_i2c_found, &es7210);
    ESP_LOGI(TAG, "i2c devices (%d): %s", found, s_i2c_found);
    pcf_rtc_init(s_i2c);
    battery_init();
    if (audio_init(s_i2c, es7210) != ESP_OK) {
        ESP_LOGW(TAG, "audio unavailable - continuing without sound");
    }
    s_display_ok = rlcd_display_init() == ESP_OK;

    app_io_t io = {NULL, io_send, io_chime, io_capture, io_diag};
    app_init(&s_app, &io, now_ms(), esp_random(), false);
    uint32_t epoch = pcf_rtc_read_epoch();
    if (epoch) {
        app_set_epoch(&s_app, epoch);
    }
    s_batt_mv = battery_read_mv();
    app_set_battery(&s_app, battery_pct_from_mv(s_batt_mv));
    app_render_if_dirty(&s_app);
    if (s_display_ok) {
        rlcd_display_flush(&s_app.fb);
    }
    usb_transport_init(on_frame, NULL);
    xTaskCreatePinnedToCore(ui_task, "ui", 8192, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(audio_task, "audio", 6144, NULL, 7, NULL, 0);
    ESP_LOGI(TAG, "PIP fw %s up (display=%d audio=%d rtc=%d)", APP_FW_VERSION, s_display_ok, audio_ok(),
             pcf_rtc_present());
}
