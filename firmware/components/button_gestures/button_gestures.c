#include "button_gestures.h"

#include <string.h>

typedef struct {
    gesture_event_t *out;
    int max;
    int n;
} sink_t;

static void emit(sink_t *s, btn_id_t b, gesture_t g, uint8_t flags, uint32_t ts)
{
    if (s->n < s->max) {
        s->out[s->n].btn = b;
        s->out[s->n].gesture = g;
        s->out[s->n].flags = flags;
        s->out[s->n].ts_ms = ts;
        s->n++;
    }
}

void gestures_init(gestures_t *g, uint32_t now_ms)
{
    memset(g, 0, sizeof *g);
    g->boot_ms = now_ms;
    for (int i = 0; i < BTN_COUNT; i++) {
        g->b[i].raw_since = now_ms;
    }
}

static void on_press(gestures_t *g, btn_id_t id, uint32_t t, sink_t *s)
{
    btn_fsm_t *b = &g->b[id];
    if (id == BTN_BOOT && t - g->boot_ms < BOOT_STARTUP_LOCKOUT_MS) {
        b->locked = true; /* preserve ROM download-mode chord right after reset */
        return;
    }
    if (id == BTN_KEY && b->clicks == 1 && t - b->release_ms >= DOUBLE_CLICK_WINDOW_MS) {
        emit(s, id, GEST_SHORT, 0, b->release_ms + DOUBLE_CLICK_WINDOW_MS);
        b->clicks = 0;
    }
    b->press_ms = t;
    b->hold_fired = false;
    b->ptt_timed_out = false;
}

static void on_release(gestures_t *g, btn_id_t id, uint32_t t, sink_t *s)
{
    btn_fsm_t *b = &g->b[id];
    if (b->locked) {
        b->locked = false;
        return;
    }
    if (b->hold_fired) {
        if (id == BTN_KEY && !b->ptt_timed_out) {
            emit(s, id, GEST_HOLD_END, 0, t);
        }
        b->hold_fired = false;
        return;
    }
    if (id == BTN_BOOT) {
        emit(s, id, GEST_SHORT, 0, t);
        return;
    }
    if (b->clicks == 1) {
        emit(s, id, GEST_DOUBLE, 0, t);
        b->clicks = 0;
    } else {
        b->clicks = 1;
        b->release_ms = t;
    }
}

static void timeouts(gestures_t *g, btn_id_t id, uint32_t now, sink_t *s)
{
    btn_fsm_t *b = &g->b[id];
    /* holds only count while the raw line is still pressed (a pending release wins) */
    if (b->stable && b->raw && !b->locked) {
        uint32_t held = now - b->press_ms;
        if (!b->hold_fired) {
            if (id == BTN_KEY && held >= KEY_HOLD_PTT_MS) {
                b->hold_fired = true;
                b->clicks = 0; /* long hold cancels a pending click */
                emit(s, id, GEST_HOLD_START, 0, b->press_ms + KEY_HOLD_PTT_MS);
            } else if (id == BTN_BOOT && held >= BOOT_HOLD_RESCUE_MS) {
                b->hold_fired = true;
                emit(s, id, GEST_RESCUE, 0, b->press_ms + BOOT_HOLD_RESCUE_MS);
            }
        } else if (id == BTN_KEY && !b->ptt_timed_out && held >= KEY_HOLD_PTT_MS + PTT_MAX_DURATION_MS) {
            b->ptt_timed_out = true;
            emit(s, id, GEST_HOLD_END, GEST_FLAG_TIMEOUT, b->press_ms + KEY_HOLD_PTT_MS + PTT_MAX_DURATION_MS);
        }
    } else if (id == BTN_KEY && !b->stable && !b->raw && b->clicks == 1 && now - b->release_ms >= DOUBLE_CLICK_WINDOW_MS) {
        b->clicks = 0;
        emit(s, id, GEST_SHORT, 0, b->release_ms + DOUBLE_CLICK_WINDOW_MS);
    }
}

static void settle(gestures_t *g, btn_id_t id, uint32_t now_ms, sink_t *s)
{
    btn_fsm_t *b = &g->b[id];
    if (b->raw != b->stable && now_ms - b->raw_since >= DEBOUNCE_MS) {
        b->stable = b->raw;
        if (b->stable) {
            on_press(g, id, b->raw_since, s);
        } else {
            on_release(g, id, b->raw_since, s);
        }
    }
    timeouts(g, id, now_ms, s);
}

int gestures_update(gestures_t *g, btn_id_t id, bool pressed, uint32_t now_ms, gesture_event_t *out, int max)
{
    sink_t s = {out, max, 0};
    if ((unsigned)id >= BTN_COUNT) {
        return 0;
    }
    btn_fsm_t *b = &g->b[id];
    /* 1) settle what the line did up to `now` (the previous level lasted until now) */
    settle(g, id, now_ms, &s);
    /* 2) then apply the new sample */
    if (pressed != b->raw) {
        b->raw = pressed;
        b->raw_since = now_ms;
    }
    settle(g, id, now_ms, &s);
    return s.n;
}
