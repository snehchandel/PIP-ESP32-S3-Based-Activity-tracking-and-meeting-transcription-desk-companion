/* Portable PIP state coordinator: gestures -> actions, host frames -> model, local timer,
 * offline event log, link supervision and rendering. Pure C99, shared by device + sim_rlcd. */
#ifndef APP_CONTROLLER_H
#define APP_CONTROLLER_H

#include <stdbool.h>
#include <stdint.h>

#include "button_gestures.h"
#include "local_timer.h"
#include "pip_protocol.h"
#include "rlcd_fb.h"
#include "ui_model.h"

#define APP_LINK_TIMEOUT_MS 3000u
#define APP_HEARTBEAT_MS 1000u
#define APP_SLEEP_IDLE_MS (15u * 60u * 1000u)
#define APP_BREAK_MS (5u * 60u * 1000u)
#define APP_TOAST_MS 2000u
#define APP_ACK_TOAST_MS 6000u      /* host confirmations, e.g. "Alarm set: Wed 05:00" */
#define APP_RING_CHIME_MS 2500u     /* offline ringing: repeat the alarm chime... */
#define APP_RING_CHIME_FOR_MS 60000u /* ...for one minute */
#define APP_ALARMS_MAX 8
#define APP_FW_VERSION "1.3.0" /* keep in sync with PROJECT_VER in firmware/CMakeLists.txt */

typedef enum { CHIME_START = 1, CHIME_DONE, CHIME_PAUSE, CHIME_ALARM, CHIME_OFFLINE, CHIME_CONFIRM } chime_id_t;

typedef struct {
    uint32_t free_heap_b, free_psram_b;
    int32_t batt_mv; /* -1 unknown */
    bool rtc_ok, display_ok, audio_ok;
    char i2c_addrs[48];
    char reset_reason[24];
    uint32_t dropped_audio_chunks;
    char extra[640]; /* device-only JSON members (no braces): wifi / ota / wake status */
} app_diag_t;

typedef struct {
    void *ctx;
    void (*send)(void *ctx, uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len);
    void (*chime)(void *ctx, uint8_t chime_id);
    void (*capture)(void *ctx, bool start, uint32_t stream_id); /* PTT mic capture on/off */
    void (*diag)(void *ctx, app_diag_t *d);
    /* host->device voice stream: AUDIO_START_OUT / AUDIO_DATA_OUT (u32 stream, u16 seq, mono PCM16 16 kHz) / END */
    void (*play)(void *ctx, uint8_t type, const uint8_t *payload, uint16_t len);
} app_io_t;

typedef struct {
    char id[24];
    char title[40];
    uint32_t epoch_s;
    uint8_t chime_id;
    bool enabled;
    bool fired;
} app_alarm_t;

typedef struct {
    ui_model_t m;
    rlcd_fb_t fb;
    local_timer_t timer;
    local_timer_t brk;
    oev_queue_t oev;
    gestures_t gest;
    app_io_t io;
    bool is_sim;

    uint32_t now_ms;
    uint32_t last_rx_ms;
    bool ever_linked;
    uint32_t last_hb_ms;
    uint32_t boot_id;
    uint32_t event_seq;
    uint32_t state_rev;
    uint32_t calendar_rev;
    uint16_t tx_seq;
    uint16_t pending_oev_seq; /* seq of unacked OFFLINE_EVENTS frame, 0 = none */
    uint32_t pending_oev_ms;

    bool epoch_valid;
    uint32_t epoch_s_at;  /* epoch seconds at epoch_ms_at */
    uint32_t epoch_ms_at;
    int16_t tz_offset_min;

    char next_step_id[24];
    uint32_t idle_since_ms;
    uint32_t toast_until_ms;
    uint32_t toast_id;      /* last host toast shown (each id is shown once) */
    uint32_t ring_since_ms;
    uint32_t ring_chime_ms;
    uint32_t stream_id;
    uint32_t listen_start_ms;
    ui_state_t state_before_alarm;
    char alarm_id[24];
    app_alarm_t alarms[APP_ALARMS_MAX];
    uint8_t alarm_count;
    bool dirty;
    uint32_t crc_errors;

    mascot_anim_t anim;
    ui_state_t prev_state;
    uint32_t state_since_ms; /* for the stuck-state watchdog */
    ui_state_t state_before_pick;
    uint32_t pick_since_ms;
    uint32_t error_since_ms;
    bool error_local; /* raised by the device itself (vs. pushed by the host) */
    bool hands_free;  /* recording started by the wake word: the device ends it on silence */

    /* screen slide transitions (buffers are heap: PSRAM on the device) */
    ui_screen_t shown_screen;
    bool shown_valid;
    bool sliding;
    int8_t slide_dir;
    uint32_t slide_start_ms, slide_last_ms, slide_dur_ms;
    rlcd_fb_t *slide_from, *slide_to;
} app_t;

#define APP_PICK_TIMEOUT_MS 20000u
#define APP_STUCK_MS 180000u /* device-side watchdog for LISTENING / TRANSCRIBING / THINKING */
#define APP_ERROR_FLASH_MS 2400u

void app_init(app_t *a, const app_io_t *io, uint32_t now_ms, uint32_t boot_id, bool is_sim);
void app_tick(app_t *a, uint32_t now_ms);
void app_button_sample(app_t *a, btn_id_t btn, bool pressed, uint32_t now_ms);
void app_on_gesture(app_t *a, const gesture_event_t *e);
void app_on_frame(app_t *a, const pip_frame_t *f);
void app_set_epoch(app_t *a, uint32_t epoch_s);
uint32_t app_epoch_now(const app_t *a);
void app_set_battery(app_t *a, int pct);
void app_set_audio_level(app_t *a, uint8_t level);
void app_set_indoor(app_t *a, bool valid, int16_t temp_c10, uint8_t hum);
void app_local_error(app_t *a, const char *title, const char *text);
/* Wake word heard: start a hands-free voice message (returns false when PIP can't listen right now). */
bool app_voice_wake(app_t *a);
/* End a hands-free recording (silence detected / time limit). */
void app_voice_end(app_t *a);
/* Re-render into a->fb if anything changed (or a slide transition is running); returns true when the panel
 * needs a flush. */
bool app_render_if_dirty(app_t *a);

/* internal (shared between app_*.c files) */
void app_send(app_t *a, uint8_t type, bool ack, const uint8_t *payload, uint16_t len);
void app_toast(app_t *a, const char *msg);
void app_toast_for(app_t *a, const char *msg, uint32_t ms);
void app_stop_voice(app_t *a);
void app_sync_timer_to_model(app_t *a);
void app_send_offline_events(app_t *a);
void app_send_diag(app_t *a);
void app_send_heartbeat(app_t *a);
void app_ring_alarm(app_t *a, const char *id, const char *title, const char *hhmm, uint8_t audio);
void app_apply_ui_update(app_t *a, const char *json, size_t n);
void app_apply_calendar(app_t *a, const char *json, size_t n);
const char *app_state_name(ui_state_t s);
ui_state_t app_state_from_name(const char *s);

#endif
