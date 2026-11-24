/* 1-bit UI engine: framebuffer layout, primitives, text, all 11 screens + render budget. */
#include <string.h>
#include <time.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"
#include "tinytest.h"

static rlcd_fb_t fb;
static ui_meta_t meta;

static int ink_in(int x0, int y0, int x1, int y1)
{
    int n = 0;
    for (int y = y0; y <= y1; y++) {
        for (int x = x0; x <= x1; x++) {
            n += fb_get(&fb, x, y);
        }
    }
    return n;
}

int main(void)
{
    CHECK_EQ(sizeof(rlcd_fb_t), 15000);
    fb_clear(&fb, INK_WHITE);
    fb_set(&fb, 0, 0, INK_BLACK);
    CHECK_EQ(fb.px[0], 0x80); /* MSB = leftmost pixel, bit 1 = black */
    fb_set(&fb, 399, 299, INK_BLACK);
    CHECK_EQ(fb.px[14999], 0x01);
    fb_set(&fb, 400, 0, INK_BLACK); /* clipped */
    fb_set(&fb, -1, 5, INK_BLACK);
    CHECK_EQ(ink_in(0, 0, 399, 299), 2);

    fb_clear(&fb, INK_WHITE);
    fb_fill_rect(&fb, 10, 10, 20, 5, INK_BLACK);
    CHECK_EQ(ink_in(0, 0, 399, 299), 100);
    fb_rect(&fb, 100, 100, 18, 18, 2, INK_BLACK);
    CHECK_EQ(ink_in(100, 100, 117, 117), 18 * 18 - 14 * 14);

    CHECK(text_width(&FONT_16, "Focus") > 20);
    CHECK_EQ(text_width(&FONT_64, "25:00"), 5 * text_width(&FONT_64, "0")); /* tabular digits */
    CHECK_EQ(text_width(&FONT_64, "11:11"), text_width(&FONT_64, "00:00"));
    const char *s = "\xC2\xB7";
    CHECK_EQ(font_next_code(&s), 127);

    fb_clear(&fb, INK_WHITE);
    CHECK_EQ(text_draw_fit(&fb, &FONT_16, 0, 0, 60, "A very long step title that cannot fit", INK_BLACK), 1);
    CHECK_EQ(ink_in(61, 0, 399, 30), 0);
    int lines = text_draw_wrap(&fb, &FONT_16, 0, 40, 120, 2, 2, "Open template and add three headings now", INK_BLACK);
    CHECK_EQ(lines, 2);

    /* every screen renders, has an inverted bottom bar and a non-empty mascot stage */
    ui_model_t m;
    ui_model_init(&m);
    m.link = LINK_TETHERED;
    snprintf(m.step_title, sizeof m.step_title, "Draft summary");
    m.has_active_step = true;
    m.remaining_ms = 1500000;
    m.step_total_ms = 1500000;
    const ui_state_t states[] = {UI_STATE_IDLE_READY, UI_STATE_LISTENING, UI_STATE_THINKING,
                                 UI_STATE_RUNNING, UI_STATE_PAUSED, UI_STATE_BREAK, UI_STATE_STEP_DONE,
                                 UI_STATE_IDLE_READY, UI_STATE_ALARM_RINGING, UI_STATE_NEEDS_CONFIRMATION,
                                 UI_STATE_SLEEP};
    for (int i = 0; i < SCREEN_COUNT; i++) {
        m.state = states[i];
        m.page = i == SCREEN_DAILY_TASKS ? PAGE_AGENDA : PAGE_FOCUS;
        CHECK_EQ(ui_screen_for(&m), i);
        ui_render(&fb, &m, &meta);
        int bar = ink_in(0, BAR_Y, 399, 299);
        CHECK(bar > (int)(0.70 * 400 * 36));
        int stage = ink_in(MASCOT_X, MASCOT_Y, MASCOT_X + 119, MASCOT_Y + 119);
        CHECK(stage > (int)(0.12 * 14400) && stage < (int)(0.60 * 14400));
        CHECK(meta.n > 3);
    }
    /* alarm overrides agenda page; listening overrides everything but alarm */
    m.page = PAGE_AGENDA;
    m.state = UI_STATE_ALARM_RINGING;
    CHECK_EQ(ui_screen_for(&m), SCREEN_ALARM_RINGING);
    m.state = UI_STATE_LISTENING;
    CHECK_EQ(ui_screen_for(&m), SCREEN_LISTENING);

    /* mascot blink: only READY / WORKING, 2 FPS, 1 of 8 frames */
    CHECK_EQ(mascot_blink_phase(PIP_EXPR_ALARM, 3500), 0);
    CHECK_EQ(mascot_blink_phase(PIP_EXPR_READY, 3500), 1);
    CHECK_EQ(mascot_blink_phase(PIP_EXPR_READY, 3499), 0);
    CHECK(mascot_bits(PIP_EXPR_READY, 1) != mascot_bits(PIP_EXPR_READY, 0));
    CHECK(mascot_bits(PIP_EXPR_ALARM, 1) == mascot_bits(PIP_EXPR_ALARM, 0));

    /* host render budget: <= 2 ms per full frame */
    m.page = PAGE_FOCUS;
    m.state = UI_STATE_RUNNING;
    clock_t t0 = clock();
    for (int i = 0; i < 200; i++) {
        ui_render(&fb, &m, NULL);
    }
    double ms = (double)(clock() - t0) * 1000.0 / CLOCKS_PER_SEC / 200.0;
    printf("render %.3f ms/frame\n", ms);
    CHECK(ms <= 2.0);
    TT_DONE();
}
