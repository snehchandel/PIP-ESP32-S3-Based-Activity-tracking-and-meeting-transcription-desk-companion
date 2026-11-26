/* Thin FreeRTOS wiring: hardware adapters <-> portable app_controller.
 * Core 0: USB rx + audio. Core 1: UI render, timer, buttons, RTC, battery. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"
#include "audio_codec.h"
#include "dev_config.h"
#include "dev_ota.h"
#include "dev_wake.h"
#include "esp_vad.h"
#include "net_link.h"
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
#include "freertos/stream_buffer.h"
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
static dev_config_t s_cfg;
static volatile int s_src;              /* 0 USB, 1 Wi-Fi: the link the PC last spoke on */
static volatile uint32_t s_usb_rx_ms;  /* last frame from the PC over USB: the cable always wins */

static uint32_t now_ms(void) { return (uint32_t)(esp_timer_get_time() / 1000); }
static void lock(void) { xSemaphoreTake(s_lock, portMAX_DELAY); }
static void unlock(void) { xSemaphoreGive(s_lock); }

/* the PC spoke over the USB cable in the last 3 s (then PIP answers over USB and never dials out) */
static bool usb_active(void)
{
    return s_usb_rx_ms != 0 && now_ms() - s_usb_rx_ms < 3000u && usb_transport_host_connected();
}

static void io_send(void *ctx, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *p, uint16_t len)
{
    /* the USB cable wins whenever the PC is using it; Wi-Fi (LAN or away link) only when it is not */
    if (!usb_active() && s_src == 1 && net_link_client_ready()) {
        net_link_send(type, flags, seq, p, len);
    } else {
        usb_transport_send(type, flags, seq, p, len);
    }
}

static void io_chime(void *ctx, uint8_t id) { xQueueSend(s_chime_q, &id, 0); }

/* Host voice (Piper TTS) arrives as AUDIO_*_OUT frames; a 1 s PSRAM stream buffer decouples USB from I2S. */
#define VOICE_BUF_BYTES 32768
static StreamBufferHandle_t s_voice;
static StaticStreamBuffer_t s_voice_sb;
static volatile bool s_voice_end;
static volatile bool s_voice_blocked; /* after an abort: ignore late chunks until the next stream */
static volatile uint32_t s_voice_dropped;

static void io_play(void *ctx, uint8_t type, const uint8_t *p, uint16_t len)
{
    if (!s_voice) {
        return;
    }
    if (type == PIP_AUDIO_START_OUT) {
        xStreamBufferReset(s_voice);
        s_voice_end = false;
        s_voice_blocked = false;
    } else if (type == PIP_AUDIO_DATA_OUT && len > 6) {
        if (s_voice_blocked) {
            return;
        }
        size_t n = (size_t)(len - 6) & ~(size_t)1; /* whole 16-bit samples only */
        if (s_capture || xStreamBufferSend(s_voice, p + 6, n, 0) < n) {
            s_voice_dropped++; /* half-duplex: never speak over the mic; or buffer overrun */
        }
    } else if (type == PIP_AUDIO_END_OUT) {
        if (len >= 5 && p[4] == 1) { /* abort: drop what is still buffered */
            s_voice_blocked = true;
            xStreamBufferReset(s_voice);
        }
        s_voice_end = true;
    }
}

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
    d->dropped_audio_chunks = s_voice_dropped;
    snprintf(d->i2c_addrs, sizeof d->i2c_addrs, "%s", s_i2c_found);
    snprintf(d->reset_reason, sizeof d->reset_reason, "%s", reset_reason());
    uint32_t env_ok = 0, env_fail = 0;
    shtc3_stats(&env_ok, &env_fail);
    int n = snprintf(d->extra, sizeof d->extra, "\"env\":{\"ok\":%lu,\"fail\":%lu},", (unsigned long)env_ok,
                     (unsigned long)env_fail);
    n += net_link_status_json(d->extra + n, sizeof d->extra - (size_t)n);
    if (n > 0 && (size_t)n + 2 < sizeof d->extra) {
        d->extra[n++] = ',';
        n += dev_ota_status_json(d->extra + n, sizeof d->extra - (size_t)n);
    }
    if (n > 0 && (size_t)n + 2 < sizeof d->extra) {
        d->extra[n++] = ',';
        dev_wake_status_json(d->extra + n, sizeof d->extra - (size_t)n);
    }
}

static void set_wake_label(void);

static void send_ack(uint16_t ref, uint8_t status)
{
    pip_ack_t k = {ref, status, 0, 0};
    uint8_t b[6];
    lock();
    app_send(&s_app, PIP_ACK, false, b, (uint16_t)pip_pack_ack(&k, b));
    unlock();
}

/* Device-only frames (settings, firmware update, wake-word test). Returns true when consumed. */
static bool device_frame(const pip_frame_t *f)
{
    switch (f->type) {
    case PIP_DEVICE_CONFIG: {
        unsigned changed = dev_config_apply_json(&s_cfg, (const char *)f->payload, f->len);
        uint8_t st = PIP_ACK_OK;
        if (changed && dev_config_save(&s_cfg) != ESP_OK) {
            st = PIP_ACK_FAILED;
        }
        send_ack(f->seq, st);
        if (changed & DEVCFG_WAKE) {
            dev_wake_configure(s_cfg.wake_on, s_cfg.wake_word);
            set_wake_label();
        }
        if (changed & (DEVCFG_WIFI | DEVCFG_TOKEN | DEVCFG_REMOTE)) {
            net_link_apply(&s_cfg, changed);
        }
        lock();
        app_send_diag(&s_app);
        unlock();
        return true;
    }
    case PIP_OTA_BEGIN:
    case PIP_OTA_DATA:
    case PIP_OTA_END:
        send_ack(f->seq, dev_ota_frame(f)); /* flash writes happen outside the app lock */
        return true;
    case PIP_WAKE_TEST:
        dev_wake_test_feed((const int16_t *)f->payload, f->len / 2);
        if (f->flags & PIP_FLAG_ACK_REQUIRED) {
            send_ack(f->seq, PIP_ACK_OK);
        }
        return true;
    default: return false;
    }
}

static void handle_frame(const pip_frame_t *f, int src)
{
    s_src = src;
    if (src == 0) {
        s_usb_rx_ms = now_ms();
    }
    lock();
    s_app.now_ms = now_ms();
    s_app.last_rx_ms = s_app.now_ms; /* device-only frames also prove the PC is there */
    s_app.ever_linked = true;
    unlock();
    if (device_frame(f)) {
        return;
    }
    lock();
    s_app.crc_errors = usb_transport_crc_errors();
    app_on_frame(&s_app, f);
    unlock();
}

static void on_usb_frame(const pip_frame_t *f, void *ctx) { handle_frame(f, 0); }
static void on_net_frame(const pip_frame_t *f, void *ctx) { handle_frame(f, 1); }

static void set_wake_label(void)
{
    static const char *const ids[] = {"hiesp", "jarvis", "computer", "hijoy"};
    static const char *const labels[] = {"Hi ESP", "Jarvis", "Computer", "Hi Joy"};
    const char *label = "";
    for (int i = 0; i < 4 && dev_wake_active(); i++) {
        if (strcmp(s_cfg.wake_word, ids[i]) == 0) label = labels[i];
    }
    lock();
    snprintf(s_app.m.wake_label, sizeof s_app.m.wake_label, "%s", label);
    s_app.dirty = true;
    unlock();
}

static void on_wake(int source, void *ctx)
{
    lock();
    s_app.now_ms = now_ms();
    bool started = source == 0 && app_voice_wake(&s_app); /* a test clip only reports the hit */
    uint8_t ev[2] = {(uint8_t)source, (uint8_t)(started ? 1 : 0)};
    app_send(&s_app, PIP_WAKE_EVENT, false, ev, sizeof ev);
    unlock();
}

static void ui_task(void *arg)
{
    uint32_t last_batt = 0, last_rtc_sync = 0, last_env = 0, env_every = 30000u;
    for (;;) {
        uint32_t t = now_ms();
        int16_t temp_c10 = 0;
        uint8_t hum = 0;
        bool env_due = t - last_env >= env_every || last_env == 0, env_ok = false;
        if (env_due) { /* ~15 ms I2C conversion: done outside the app lock */
            last_env = t;
            env_ok = shtc3_read(&temp_c10, &hum);
            env_every = env_ok ? 30000u : 2000u; /* a miss is retried soon */
        }
        lock();
        if (env_due) {
            app_set_indoor(&s_app, env_ok, temp_c10, hum);
        }
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
        int prog = dev_ota_progress();
        static int last_prog = -1;
        if (prog >= 0 && prog / 5 != last_prog / 5) {
            char msg[40];
            snprintf(msg, sizeof msg, "Updating firmware %d%%", prog);
            app_toast_for(&s_app, msg, 4000);
        }
        last_prog = prog;
        dev_ota_confirm_if_healthy(t);
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
    static int16_t tone[AUDIO_CHUNK_SAMPLES];
    static uint8_t pkt[6 + AUDIO_CHUNK_BYTES];
    bool was = false, speaking = false;
    uint16_t chunk = 0;
    uint32_t samples = 0, stream = 0, quiet_since = 0, total_ms = 0;
    /* hands-free recordings end on silence: WebRTC VAD on 20 ms frames */
    vad_handle_t vad = vad_create(VAD_MODE_1);
    uint32_t speech_ms = 0, silence_ms = 0, rec_ms = 0;
    /* acknowledgement chime over the live mic: played 20 ms per mic chunk so no speech is lost */
    uint8_t duplex_id = 0, amp_hold = 0, vad_skip = 0;
    uint32_t duplex_pos = 0;
    for (;;) {
        if (s_capture && audio_ok()) {
            if (!was) {
                was = true;
                chunk = 0;
                samples = 0;
                stream = s_stream;
                speech_ms = silence_ms = rec_ms = total_ms = 0;
            }
            uint8_t cid;
            if (!duplex_id && xQueuePeek(s_chime_q, &cid, 0) == pdTRUE && (cid == CHIME_CONFIRM || cid == CHIME_START)) {
                (void)xQueueReceive(s_chime_q, &cid, 0); /* "heard you" / "go ahead"; other chimes wait as before */
                duplex_id = cid;
                duplex_pos = 0;
            }
            if (duplex_id) {
                size_t k = audio_chime_fill(duplex_id, APP_DUPLEX_CHIME_VOL, duplex_pos, tone, AUDIO_CHUNK_SAMPLES);
                if (k > 0) {
                    memset(tone + k, 0, (AUDIO_CHUNK_SAMPLES - k) * sizeof tone[0]);
                    (void)audio_write_mono_duplex(tone, AUDIO_CHUNK_SAMPLES);
                    duplex_pos += (uint32_t)k;
                    amp_hold = 6; /* the I2S DMA still holds ~90 ms of tone: keep the amp on for it */
                    vad_skip = 12; /* the mic hears the chime (and ~200 ms of echo in its DMA): not speech */
                } else {
                    duplex_id = 0;
                }
            } else if (amp_hold && --amp_hold == 0) {
                audio_amp_off();
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
                bool hands_free = s_app.hands_free, autom = s_app.voice_auto;
                if (s_app.vad_reset) { /* the activity was just decided: the message proper starts now */
                    s_app.vad_reset = false;
                    speech_ms = silence_ms = rec_ms = 0;
                }
                unlock();
                total_ms += 20;
                bool heard = false; /* while our own chime is in the mic, neither speech nor silence counts */
                if (hands_free && vad) {
                    rec_ms += 20;
                    heard = vad_skip == 0;
                    if (heard && vad_process(vad, mono, AUDIO_RATE_HZ, 20) == VAD_SPEECH) {
                        speech_ms += 20;
                        silence_ms = 0;
                    } else if (heard) {
                        silence_ms += 20;
                    }
                }
                if (vad_skip) {
                    vad_skip--;
                }
                if (hands_free && vad && autom) {
                    /* after the wake word: silence -> the picker; else wait for the PC to name the activity */
                    if (speech_ms < 300 && rec_ms >= APP_AUTO_NO_SPEECH_MS) {
                        lock();
                        app_voice_auto_timeout(&s_app);
                        unlock();
                    } else if ((speech_ms >= 300 && silence_ms >= APP_AUTO_WAIT_MS) ||
                               total_ms >= APP_VOICE_MAX_S * 1000u) {
                        lock();
                        app_voice_end(&s_app);
                        unlock();
                    }
                } else if (hands_free && vad) {
                    /* done: a 3.5 s pause after real speech (5 s once they've talked for 20 s - long brain
                     * dumps have thinking pauses), nothing said for 6 s, or the 10 minute limit */
                    uint32_t quiet_end = speech_ms >= APP_QUIET_LONG_AFTER_MS ? APP_QUIET_END_LONG_MS : APP_QUIET_END_MS;
                    if ((speech_ms >= 300 && silence_ms >= quiet_end) ||
                        (speech_ms < 300 && rec_ms >= APP_NO_SPEECH_END_MS) || total_ms >= APP_VOICE_MAX_S * 1000u) {
                        lock();
                        app_voice_end(&s_app);
                        unlock();
                    }
                }
            }
            continue;
        }
        if (was) {
            was = false;
            if (duplex_id || amp_hold) { /* recording ended mid-chime */
                duplex_id = amp_hold = vad_skip = 0;
                audio_amp_off();
            }
            uint8_t b[12];
            lock();
            pip_audio_end_t e = {stream, (uint8_t)(s_app.voice_cancel ? APP_AUDIO_END_CANCELLED : 0u), 0, 0, samples};
            s_app.voice_cancel = false;
            app_send(&s_app, PIP_AUDIO_END, true, b, (uint16_t)pip_pack_audio_end(&e, b));
            unlock();
        }
        static int16_t voice[AUDIO_CHUNK_SAMPLES];
        size_t got = s_voice ? xStreamBufferReceive(s_voice, voice, sizeof voice, 0) : 0;
        if (got >= 2 && audio_ok()) {
            audio_play_mono(voice, got / 2); /* blocks ~20 ms per chunk: paced by the codec */
            speaking = true;
            continue;
        }
        if (speaking && s_voice_end) { /* stream finished and fully drained */
            audio_amp_off();
            speaking = false;
            quiet_since = now_ms();
        }
        uint8_t id;
        if (xQueueReceive(s_chime_q, &id, 0) == pdTRUE && audio_ok()) {
            audio_play_chime(id, id == CHIME_NUDGE || id == CHIME_WRAP ? 45 : 70); /* time cues stay gentle */
            quiet_since = now_ms();
            continue;
        }
        /* listen for the wake word only while PIP itself is silent (it must never hear its own voice) */
        if (!speaking && dev_wake_active() && audio_ok() && now_ms() - quiet_since > 400u) {
            if (audio_read_chunk(mono) == ESP_OK) { /* blocks ~20 ms */
                dev_wake_feed(mono, AUDIO_CHUNK_SAMPLES);
                continue;
            }
        }
        vTaskDelay(pdMS_TO_TICKS(20));
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
    dev_config_init();
    dev_config_load(&s_cfg);
    s_chime_q = xQueueCreate(4, sizeof(uint8_t));
    uint8_t *voice_store = heap_caps_malloc(VOICE_BUF_BYTES + 1, MALLOC_CAP_SPIRAM);
    if (voice_store) {
        s_voice = xStreamBufferCreateStatic(VOICE_BUF_BYTES, 2, voice_store, &s_voice_sb);
    }
    buttons_init();
    i2c_init();
    uint8_t es7210 = 0;
    int found = i2c_probe_known(s_i2c, s_i2c_found, sizeof s_i2c_found, &es7210);
    ESP_LOGI(TAG, "i2c devices (%d): %s", found, s_i2c_found);
    pcf_rtc_init(s_i2c);
    shtc3_init(s_i2c);
    battery_init();
    if (audio_init(s_i2c, es7210) != ESP_OK) {
        ESP_LOGW(TAG, "audio unavailable - continuing without sound");
    }
    s_display_ok = rlcd_display_init() == ESP_OK;

    app_io_t io = {NULL, io_send, io_chime, io_capture, io_diag, io_play};
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
    usb_transport_init(on_usb_frame, NULL);
    net_link_init(&s_cfg, on_net_frame, NULL, usb_active);
    if (dev_wake_init(on_wake, NULL)) {
        dev_wake_configure(s_cfg.wake_on, s_cfg.wake_word);
        set_wake_label();
    }
    xTaskCreatePinnedToCore(ui_task, "ui", 8192, NULL, 5, NULL, 1);
    xTaskCreatePinnedToCore(audio_task, "audio", 6144, NULL, 7, NULL, 0);
    ESP_LOGI(TAG, "PIP fw %s up (display=%d audio=%d rtc=%d)", APP_FW_VERSION, s_display_ok, audio_ok(),
             pcf_rtc_present());
}
