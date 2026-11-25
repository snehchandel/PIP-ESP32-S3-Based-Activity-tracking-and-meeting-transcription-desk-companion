/* Screen-to-screen slide transitions (pure C99). The content area slides like pages; header and status bar
 * always show the new screen. Horizontal slides read each output row as a 400-px window into the two source
 * rows laid side by side, so a frame is a few thousand byte shifts. */
#include <string.h>

#include "ui_render.h"

/* 400-px window starting at bit `off` of the 800-px row a||b */
static void window_row(uint8_t *out, const uint8_t *a, const uint8_t *b, int off)
{
    uint8_t row2[2 * RLCD_STRIDE + 1];
    memcpy(row2, a, RLCD_STRIDE);
    memcpy(row2 + RLCD_STRIDE, b, RLCD_STRIDE);
    row2[2 * RLCD_STRIDE] = 0;
    int q = off >> 3, r = off & 7;
    for (int i = 0; i < RLCD_STRIDE; i++) {
        unsigned v = (unsigned)row2[q + i] << 8 | row2[q + i + 1];
        out[i] = (uint8_t)(v >> (8 - r));
    }
}

void ui_slide_compose(rlcd_fb_t *out, const rlcd_fb_t *from, const rlcd_fb_t *to, int dir, float u, int y0, int y1)
{
    u = u < 0.0f ? 0.0f : (u > 1.0f ? 1.0f : u);
    int h = y1 - y0;
    int ox = (int)(u * (float)RLCD_W + 0.5f), oy = (int)(u * (float)h + 0.5f);
    for (int y = 0; y < RLCD_H; y++) {
        uint8_t *o = out->px + y * RLCD_STRIDE;
        if (y < y0 || y >= y1) {
            memcpy(o, to->px + y * RLCD_STRIDE, RLCD_STRIDE);
            continue;
        }
        const uint8_t *f = from->px + y * RLCD_STRIDE, *t = to->px + y * RLCD_STRIDE;
        switch (dir) {
        case 1: /* old moves left, new follows from the right */
            window_row(o, f, t, ox);
            break;
        case -1: /* old moves right, new follows from the left */
            window_row(o, t, f, RLCD_W - ox);
            break;
        case 2: { /* new drops in from the top, pushing the old one down */
            int src = y - y0 < oy ? y + h - oy : y - oy;
            memcpy(o, (y - y0 < oy ? to->px : from->px) + src * RLCD_STRIDE, RLCD_STRIDE);
            break;
        }
        case -2: { /* old lifts away upward, revealing the new one rising from below */
            int src = y + oy;
            memcpy(o, (src < y1 ? from->px + src * RLCD_STRIDE : to->px + (src - h) * RLCD_STRIDE), RLCD_STRIDE);
            break;
        }
        default: memcpy(o, t, RLCD_STRIDE); break;
        }
    }
}

/* where a screen sits in the flow: idle -> voice -> plan -> focus -> done, calendar to the right of it all */
static int rank(ui_screen_t s)
{
    switch (s) {
    case SCREEN_IDLE_READY: return 0;
    case SCREEN_VOICE_PICK: return 1;
    case SCREEN_LISTENING:
    case SCREEN_MEETING: return 2;
    case SCREEN_THINKING: return 3;
    case SCREEN_NEEDS_CONFIRMATION: return 4;
    case SCREEN_FOCUS_RUNNING:
    case SCREEN_PAUSED: return 5;
    case SCREEN_STEP_DONE: return 6;
    case SCREEN_BREAK: return 7;
    case SCREEN_DAILY_TASKS: return 9;
    default: return -1; /* alarm, error, sleep: interruptions */
    }
}

int ui_slide_dir(ui_screen_t from, ui_screen_t to)
{
    if (from == to || (unsigned)from >= SCREEN_COUNT || (unsigned)to >= SCREEN_COUNT) {
        return 0;
    }
    int a = rank(from), b = rank(to);
    if (b < 0) {
        return 2; /* alarms, errors and sleep drop in from the top */
    }
    if (a < 0) {
        return -2; /* ... and lift away again */
    }
    if (a == b) {
        return 0; /* pause / resume: same layout, no motion */
    }
    return b > a ? 1 : -1;
}
