/* 1-bit UI engine: framebuffer layout, primitives, text, all 11 screens + render budget. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
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
                                 UI_STATE_SLEEP, UI_STATE_VOICE_PICK, UI_STATE_ERROR_RECOVERABLE};
    for (int i = 0; i < SCREEN_COUNT; i++) {
        m.state = states[i];
        m.page = i == SCREEN_DAILY_TASKS ? PAGE_AGENDA : PAGE_FOCUS;
        CHECK_EQ(ui_screen_for(&m), i);
        ui_render(&fb, &m, &meta);
        int bar = ink_in(0, BAR_Y, 399, 299);
        CHECK(bar > (int)(0.70 * 400 * 36));
        int stage = ink_in(MASCOT_X, MASCOT_Y, MASCOT_X + MASCOT_W - 1, MASCOT_Y + MASCOT_H - 1);
        int area = MASCOT_W * MASCOT_H;
        CHECK(stage > (int)(0.08 * area) && stage < (int)(0.60 * area));
        CHECK(meta.n > 3);
    }
    /* alarm overrides agenda page; listening overrides everything but alarm */
    m.page = PAGE_AGENDA;
    m.state = UI_STATE_ALARM_RINGING;
    CHECK_EQ(ui_screen_for(&m), SCREEN_ALARM_RINGING);
    m.state = UI_STATE_LISTENING;
    CHECK_EQ(ui_screen_for(&m), SCREEN_LISTENING);

    /* error screen and picker win over everything except a ringing alarm */
    m.state = UI_STATE_ERROR_RECOVERABLE;
    CHECK_EQ(ui_screen_for(&m), SCREEN_ERROR);
    m.state = UI_STATE_VOICE_PICK;
    CHECK_EQ(ui_screen_for(&m), SCREEN_VOICE_PICK);
    CHECK_EQ(ui_voice_choice_activity(0), 1); /* Calendar */
    CHECK_EQ(ui_voice_choice_activity(1), 0); /* Brain dump */

    /* ---- PIP rig: turning around changes what is visible ---- */
    mascot_pose_t pose;
    pip_rig_t rig;
    mascot_home_pose(&pose);
    mascot_rig(&pose, &rig);
    CHECK(rig.visor && rig.eye_vis[0] && rig.eye_vis[1] && rig.chest_vis && !rig.back_vis);
    pose.yaw = 180.0f; /* back to the viewer */
    mascot_rig(&pose, &rig);
    CHECK(!rig.visor && rig.back_vis && !rig.chest_vis);
    pose.yaw = 90.0f; /* profile, facing the text: visor shifted right, one ear in front */
    mascot_rig(&pose, &rig);
    CHECK(rig.visor && rig.v_l > rig.hx - 5.0f && (rig.ear_z[0] > 0.5f || rig.ear_z[1] > 0.5f));
    mascot_home_pose(&pose);
    pose.arm_r = 180.0f; /* arm straight up */
    mascot_rig(&pose, &rig);
    CHECK(rig.hand[1].y < rig.shoulder[1].y - 15.0f);
    pose.arm_r = 0.0f;
    mascot_rig(&pose, &rig);
    CHECK(rig.hand[1].y > rig.shoulder[1].y + 15.0f);
    pose.scale = 1.7f; /* pressed against the glass */
    mascot_rig(&pose, &rig);
    CHECK(rig.hw > 100.0f);

    /* ---- every act of every library: smooth on stage (no jumps between 50 ms frames) ---- */
    int libs_checked = 0;
    for (int mode = 0; mode < PIP_MODE_COUNT; mode++) {
        if (mode == PIP_MODE_PICK) {
            continue;
        }
        for (int act = 0; act < mascot_act_count((pip_mode_t)mode); act++) {
            for (int dir = 0; dir < 2; dir++) {
                pip_perf_t pf = {(uint8_t)mode, (uint8_t)act, 0, (uint8_t)dir, 1};
                float D = mascot_perf_seconds(&pf);
                mascot_pose_t prev, cur;
                mascot_perf_pose(&pf, 0.0f, D, &prev);
                for (float t = 0.05f; t <= D; t += 0.05f) {
                    mascot_perf_pose(&pf, t, D, &cur);
                    bool on_stage = fabsf(cur.x) < 70.0f && fabsf(prev.x) < 70.0f;
                    if (on_stage && !(fabsf(cur.x - prev.x) <= 6.0f && fabsf(cur.y - prev.y) <= 9.0f)) {
                        printf("jump in %s/%s at %.2f s: x %.1f->%.1f y %.1f->%.1f\n", mascot_mode_name((pip_mode_t)mode),
                               mascot_act_name((pip_mode_t)mode, act), (double)t, (double)prev.x, (double)cur.x,
                               (double)prev.y, (double)cur.y);
                        CHECK(0);
                    }
                    CHECK(cur.scale > 0.5f && cur.scale < 2.0f);
                    prev = cur;
                }
            }
            libs_checked++;
        }
    }
    CHECK(mascot_act_count(PIP_MODE_IDLE) >= 25);
    CHECK(mascot_act_count(PIP_MODE_FOCUS) >= 8);
    CHECK(libs_checked > 50);

    /* ---- idle: 2 hours of play, no performance repeats, activity types rotate ---- */
    static mascot_anim_t an;
    mascot_anim_init(&an, 1234, 0);
    mascot_set_mode(&an, PIP_MODE_IDLE, 0);
    static uint16_t keys[1024];
    static uint8_t acts[1024];
    int nperf = 0, redraws = 0;
    uint32_t last_count = 0;
    for (uint32_t t = 0; t < MASCOT_NO_REPEAT_MS; t += 50) {
        redraws += mascot_anim_step(&an, t);
        if (an.perf_count != last_count && nperf < 1024) {
            last_count = an.perf_count;
            keys[nperf] = mascot_perf_key(&an.perf);
            acts[nperf] = an.perf.act;
            nperf++;
        }
    }
    int dupes = 0, close_acts = 0;
    for (int i = 0; i < nperf; i++) {
        for (int j = i + 1; j < nperf; j++) {
            dupes += keys[i] == keys[j];
        }
        for (int j = i + 1; j < nperf && j <= i + 6; j++) {
            close_acts += acts[i] == acts[j];
        }
    }
    printf("idle: %d performances in 2 h, %d repeats, %d same-activity within 6\n", nperf, dupes, close_acts);
    CHECK(nperf > 250);
    CHECK_EQ(dupes, 0);
    CHECK_EQ(close_acts, 0);
    CHECK(redraws > 100000 && redraws <= (int)(MASCOT_NO_REPEAT_MS / MASCOT_FRAME_MS) + 1); /* <= 20 FPS */

    /* ---- reactions: a double press spins PIP all the way round ---- */
    mascot_anim_init(&an, 99, 0);
    mascot_set_mode(&an, PIP_MODE_IDLE, 0);
    for (uint32_t t = 0; t <= 2000; t += 50) mascot_anim_step(&an, t);
    float yaw0 = an.pose.yaw;
    mascot_react(&an, PIP_REACT_DOUBLE, 2000);
    for (uint32_t t = 2050; t <= 2600; t += 50) mascot_anim_step(&an, t);
    CHECK(fabsf(an.pose.yaw - yaw0) > 90.0f);
    /* picker: PIP looks further down for lower options */
    mascot_set_mode(&an, PIP_MODE_PICK, 3000);
    mascot_set_pick(&an, 0, 4);
    for (uint32_t t = 3050; t <= 4500; t += 50) mascot_anim_step(&an, t);
    float top_look = an.pose.look_y;
    mascot_set_pick(&an, 3, 4);
    for (uint32_t t = 4550; t <= 5000; t += 50) mascot_anim_step(&an, t);
    CHECK(an.pose.look_y > top_look + 0.8f && an.pose.yaw > 30.0f);

    /* eyes are live: closing the lids changes the pixels */
    m.state = UI_STATE_IDLE_READY;
    m.page = PAGE_FOCUS;
    mascot_home_pose(&m.pose);
    ui_render(&fb, &m, NULL);
    int open_ink = ink_in(MASCOT_X, MASCOT_Y, MASCOT_X + MASCOT_W - 1, MASCOT_Y + MASCOT_H - 1);
    m.pose.lid = 1.0f;
    ui_render(&fb, &m, NULL);
    CHECK(ink_in(MASCOT_X, MASCOT_Y, MASCOT_X + MASCOT_W - 1, MASCOT_Y + MASCOT_H - 1) > open_ink);
    /* PIP never draws over the text column */
    fb_clear(&fb, INK_WHITE);
    mascot_home_pose(&m.pose);
    m.pose.x = 60.0f;
    m.pose.arm_r = 90.0f;
    m.pose.scale = 1.7f;
    ui_draw_mascot(&fb, &m.pose);
    CHECK_EQ(ink_in(STAGE_X + STAGE_W, 0, 399, 299), 0);

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
