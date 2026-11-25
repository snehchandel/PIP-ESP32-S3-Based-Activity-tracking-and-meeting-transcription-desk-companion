/* Deterministic debounce + click / double-click / PTT hold / rescue hold recognizer.
 * Pure C99 with an injectable millisecond clock (spec v6 section 5.3). */
#ifndef BUTTON_GESTURES_H
#define BUTTON_GESTURES_H

#include <stdbool.h>
#include <stdint.h>

#define DEBOUNCE_MS 30u
#define DOUBLE_CLICK_WINDOW_MS 300u
#define KEY_HOLD_PTT_MS 450u
#define PTT_MAX_DURATION_MS 600000u /* voice messages may run 10 minutes */
#define BOOT_HOLD_RESCUE_MS 1200u
#define BOOT_STARTUP_LOCKOUT_MS 500u

typedef enum { BTN_KEY = 0, BTN_BOOT = 1, BTN_COUNT = 2 } btn_id_t;

typedef enum {
    GEST_NONE = 0,
    GEST_SHORT = 1,
    GEST_DOUBLE = 2,
    GEST_HOLD_START = 3, /* KEY: PTT start */
    GEST_HOLD_END = 4,   /* KEY: PTT end (flags bit0 = watchdog timeout) */
    GEST_RESCUE = 5      /* BOOT: cut step in half */
} gesture_t;

#define GEST_FLAG_TIMEOUT 0x01

typedef struct {
    btn_id_t btn;
    gesture_t gesture;
    uint8_t flags;
    uint32_t ts_ms;
} gesture_event_t;

typedef struct {
    bool raw;            /* last raw sample */
    uint32_t raw_since;  /* when raw last changed */
    bool stable;         /* debounced level (true = pressed) */
    uint32_t press_ms;   /* debounced press edge time */
    uint32_t release_ms; /* debounced release edge time */
    uint8_t clicks;      /* pending short releases awaiting double window */
    bool hold_fired;     /* PTT / rescue already emitted for this press */
    bool ptt_timed_out;
    bool locked;         /* BOOT startup lockout: ignore until released */
} btn_fsm_t;

typedef struct {
    btn_fsm_t b[BTN_COUNT];
    uint32_t boot_ms;
} gestures_t;

void gestures_init(gestures_t *g, uint32_t now_ms);
/* Sample one button's raw level (true = pressed). Emits up to `max` events into out.
 * Call for every button at least every ~10 ms; also drives timeouts. Returns count. */
int gestures_update(gestures_t *g, btn_id_t btn, bool pressed, uint32_t now_ms, gesture_event_t *out, int max);

#endif
