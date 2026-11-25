/* Exact boundary timings for the gesture recognizer (spec v6 section 5.3). */
#include <string.h>

#include "button_gestures.h"
#include "tinytest.h"

typedef struct {
    gesture_event_t ev[16];
    int n;
} log_t;

/* Drive `btn` with raw level from `segs` (alternating released/pressed durations starting
 * pressed at t0), sampling every 1 ms until t_end. */
static void drive(gestures_t *g, btn_id_t btn, uint32_t t0, const uint32_t *segs, int nseg, uint32_t t_end, log_t *log)
{
    uint32_t edges[16];
    uint32_t t = t0;
    for (int i = 0; i < nseg; i++) {
        edges[i] = t;
        t += segs[i];
    }
    for (uint32_t now = t0 - 50; now <= t_end; now++) {
        bool pressed = false;
        for (int i = 0; i < nseg; i++) {
            if (now >= edges[i] && now < edges[i] + segs[i]) {
                pressed = (i % 2) == 0;
            }
        }
        gesture_event_t ev[4];
        int k = gestures_update(g, btn, pressed, now, ev, 4);
        for (int i = 0; i < k && log->n < 16; i++) {
            log->ev[log->n++] = ev[i];
        }
    }
}

static log_t run(btn_id_t btn, const uint32_t *segs, int nseg, uint32_t extra)
{
    gestures_t g;
    log_t log;
    memset(&log, 0, sizeof log);
    gestures_init(&g, 0);
    uint32_t total = 0;
    for (int i = 0; i < nseg; i++) {
        total += segs[i];
    }
    drive(&g, btn, 1000, segs, nseg, 1000 + total + extra, &log);
    return log;
}

int main(void)
{
    /* debounce: 29 ms bounce rejected, 30 ms accepted */
    uint32_t b29[] = {29};
    log_t l = run(BTN_KEY, b29, 1, 1000);
    CHECK_EQ(l.n, 0);
    uint32_t b30[] = {30};
    l = run(BTN_KEY, b30, 1, 1000);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);

    /* short click is emitted only after the 300 ms double-click window expires */
    uint32_t click[] = {100};
    l = run(BTN_KEY, click, 1, 1000);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);
    CHECK_EQ(l.ev[0].ts_ms, 1000 + 100 + 300);

    /* double click: gap 299 -> DOUBLE, gap 301 -> two SHORTs */
    uint32_t d299[] = {80, 299, 80};
    l = run(BTN_KEY, d299, 3, 1000);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_DOUBLE);
    uint32_t d301[] = {80, 301, 80};
    l = run(BTN_KEY, d301, 3, 1000);
    CHECK_EQ(l.n, 2);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);
    CHECK_EQ(l.ev[1].gesture, GEST_SHORT);

    /* PTT hold: 449 ms -> SHORT, 450 ms -> HOLD_START + HOLD_END */
    uint32_t h449[] = {449};
    l = run(BTN_KEY, h449, 1, 1000);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);
    uint32_t h450[] = {450};
    l = run(BTN_KEY, h450, 1, 1000);
    CHECK_EQ(l.n, 2);
    CHECK_EQ(l.ev[0].gesture, GEST_HOLD_START);
    CHECK_EQ(l.ev[0].ts_ms, 1450);
    CHECK_EQ(l.ev[1].gesture, GEST_HOLD_END);
    CHECK_EQ(l.ev[1].flags, 0);

    /* long hold cancels a pending click */
    uint32_t ch[] = {80, 150, 600};
    l = run(BTN_KEY, ch, 3, 1000);
    CHECK_EQ(l.n, 2);
    CHECK_EQ(l.ev[0].gesture, GEST_HOLD_START);
    CHECK_EQ(l.ev[1].gesture, GEST_HOLD_END);

    /* 10 min PTT watchdog forces HOLD_END(timeout); release later emits nothing more */
    uint32_t wd[] = {450 + PTT_MAX_DURATION_MS + 500};
    l = run(BTN_KEY, wd, 1, 1000);
    CHECK_EQ(l.n, 2);
    CHECK_EQ(l.ev[1].gesture, GEST_HOLD_END);
    CHECK_EQ(l.ev[1].flags, GEST_FLAG_TIMEOUT);
    CHECK_EQ(l.ev[1].ts_ms, 1000 + 450 + PTT_MAX_DURATION_MS);

    /* BOOT rescue: 1199 -> SHORT, 1200 -> RESCUE only */
    uint32_t r1199[] = {1199};
    l = run(BTN_BOOT, r1199, 1, 500);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);
    uint32_t r1200[] = {1200};
    l = run(BTN_BOOT, r1200, 1, 500);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_RESCUE);

    /* BOOT short waits out the double-click window; two quick clicks are a double-click (= park the task) */
    uint32_t bs[] = {100};
    l = run(BTN_BOOT, bs, 1, 400);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_SHORT);
    CHECK_EQ(l.ev[0].ts_ms, 1100 + DOUBLE_CLICK_WINDOW_MS);
    uint32_t bd[] = {80, 150, 80};
    l = run(BTN_BOOT, bd, 3, 400);
    CHECK_EQ(l.n, 1);
    CHECK_EQ(l.ev[0].gesture, GEST_DOUBLE);

    /* BOOT startup lockout: a press within 500 ms of reset is ignored entirely */
    {
        gestures_t g;
        log_t lg;
        memset(&lg, 0, sizeof lg);
        gestures_init(&g, 1000);
        uint32_t seg[] = {2000};
        drive(&g, BTN_BOOT, 1100, seg, 1, 4000, &lg);
        CHECK_EQ(lg.n, 0);
    }
    TT_DONE();
}
