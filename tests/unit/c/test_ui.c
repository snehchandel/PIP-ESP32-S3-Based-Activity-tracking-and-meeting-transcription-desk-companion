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
                                 UI_STATE_SLEEP, UI_STATE_VOICE_PICK, UI_STATE_ERROR_RECOVERABLE, UI_STATE_MEETING};
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
    /* idle world: PIP only changes depth (in front of / behind the board) while clear of it, and an act
     * never starts or ends behind the board where the next act's cross-fade would pop it to the front */
    for (int act = 0; act < mascot_act_count(PIP_MODE_IDLE); act++) {
        for (int v = 0; v < 4; v++) {
            pip_perf_t pf = {PIP_MODE_IDLE, (uint8_t)act, (uint8_t)v, 1, 1};
            float D = mascot_perf_seconds(&pf);
            mascot_pose_t prev, cur;
            mascot_perf_pose(&pf, 0.0f, D, &prev);
            CHECK(!prev.behind || prev.x + 40.0f < PIP_BOARD_DX);
            for (float t = 0.05f; t <= D + 0.001f; t += 0.05f) {
                mascot_perf_pose(&pf, t, D, &cur);
                if (cur.behind != prev.behind) {
                    bool clear = cur.x + 40.0f < PIP_BOARD_DX || prev.x > PIP_WORLD_R + PIP_OFFSCREEN - 1.0f ||
                                 cur.x < PIP_WORLD_L - PIP_OFFSCREEN + 1.0f;
                    if (!clear) {
                        printf("depth pop in %s at %.2f s (x %.1f)\n", mascot_act_name(PIP_MODE_IDLE, act), (double)t,
                               (double)cur.x);
                    }
                    CHECK(clear);
                }
                CHECK(cur.x >= PIP_WORLD_L - PIP_OFFSCREEN - 1.0f && cur.x <= PIP_WORLD_R + PIP_OFFSCREEN + 1.0f);
                prev = cur;
            }
            CHECK(fabsf(prev.x) < 12.0f); /* back home */
        }
    }
    CHECK(mascot_act_count(PIP_MODE_IDLE) >= 30);

    /* a flying prop starts (and ends) in PIP's right hand, where the prop trip delivers it */
    for (int mode = 0; mode < PIP_MODE_COUNT; mode++) {
        if (mode == PIP_MODE_PICK) {
            continue;
        }
        for (int act = 0; act < mascot_act_count((pip_mode_t)mode); act++) {
            for (int v = 0; v < 4; v++) {
                for (int dir = 0; dir < 2; dir++) {
                    pip_perf_t pf = {(uint8_t)mode, (uint8_t)act, (uint8_t)v, (uint8_t)dir, 1};
                    float D = mascot_perf_seconds(&pf);
                    for (int end = 0; end < 2; end++) {
                        mascot_pose_t ps;
                        pip_rig_t rg;
                        mascot_perf_pose(&pf, end ? D : 0.0f, D, &ps);
                        if (ps.obj == PROP_NONE || ps.obj == PROP_BALLOON) {
                            continue; /* a balloon always hangs from the hand on its string */
                        }
                        mascot_rig(&ps, &rg);
                        float dx = ps.obj_x - rg.hand[1].x, dy = ps.obj_y - rg.hand[1].y;
                        if (dx * dx + dy * dy > 18.0f * 18.0f) {
                            printf("%s/%s v%d: flying prop %.0f px from the hand at the %s\n",
                                   mascot_mode_name((pip_mode_t)mode), mascot_act_name((pip_mode_t)mode, act), v,
                                   (double)sqrtf(dx * dx + dy * dy), end ? "end" : "start");
                            CHECK(0);
                        }
                    }
                }
            }
        }
    }
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

    /* ---- seamless chaining: 2 h of play with a screen change every ~7 s. PIP never jumps, and at every seam
     * (new performance, end of a prop trip) its props are unchanged unless it is off-screen: props come from
     * and go back to the screen edge instead of popping in or out. ---- */
    mascot_anim_init(&an, 4321, 0);
    mascot_set_mode(&an, PIP_MODE_IDLE, 0);
    mascot_anim_step(&an, 0);
    mascot_pose_t last = an.pose;
    uint32_t seen_perf = an.perf_count;
    bool was_trip = an.trip;
    int trips = 0, seams = 0, jumps = 0, pops = 0;
    uint32_t rng = 77;
    for (uint32_t t = 50; t < MASCOT_NO_REPEAT_MS; t += 50) {
        if (t % 6700u == 0u) {
            rng = rng * 1103515245u + 12345u;
            pip_mode_t md = (pip_mode_t)((rng >> 16) % PIP_MODE_COUNT);
            mascot_set_mode(&an, md == PIP_MODE_PICK ? PIP_MODE_IDLE : md, t);
        }
        if (!mascot_anim_step(&an, t)) {
            continue;
        }
        const mascot_pose_t *p = &an.pose;
        bool off = p->x <= PIP_WORLD_L - 30.0f || p->x >= PIP_WORLD_R + 30.0f || last.x <= PIP_WORLD_L - 30.0f ||
                   last.x >= PIP_WORLD_R + 30.0f;
        if (!off && fabsf(p->x - last.x) > 10.0f) {
            jumps++;
            printf("jump %.1f -> %.1f at %u ms (%s/%s)\n", (double)last.x, (double)p->x, (unsigned)t,
                   mascot_mode_name(an.mode), mascot_act_name(an.mode, an.perf.act));
        }
        bool seam = an.perf_count != seen_perf || (was_trip && !an.trip);
        if (seam) {
            seams++;
            if (!off && !mascot_same_props(&last, p)) {
                pops++;
                printf("props pop at %u ms (%s/%s): held %d/%d fp %d obj %d -> held %d/%d fp %d obj %d\n", (unsigned)t,
                       mascot_mode_name(an.mode), mascot_act_name(an.mode, an.perf.act), last.held, last.held_l,
                       last.floor_prop, last.obj, p->held, p->held_l, p->floor_prop, p->obj);
            }
        }
        trips += an.trip && !was_trip;
        seen_perf = an.perf_count;
        was_trip = an.trip;
        last = *p;
    }
    printf("chaining: %d seams, %d prop trips, %d jumps, %d pops\n", seams, trips, jumps, pops);
    CHECK(trips > 100);
    CHECK_EQ(jumps, 0);
    CHECK_EQ(pops, 0);

    /* a trip really leaves the screen: the props are swapped while PIP is out of sight */
    mascot_pose_t tf, tt, tp;
    mascot_home_pose(&tf);
    tf.held = PROP_MUG;
    mascot_home_pose(&tt);
    tt.floor_prop = PROP_PLANT;
    tt.fp_x = 36.0f;
    tt.fp_y = 2.0f;
    CHECK(!mascot_same_props(&tf, &tt));
    float trip_s = mascot_trip_seconds(&tf, &tt);
    float min_x = 0.0f;
    bool swapped_off = true, carried = false;
    int prev_held = PROP_MUG;
    for (float t = 0.0f; t <= trip_s; t += 0.05f) {
        mascot_trip_pose(&tf, &tt, t, &tp);
        min_x = fminf(min_x, tp.x);
        if (tp.held != prev_held && tp.x > PIP_WORLD_L - PIP_OFFSCREEN + 1.0f) {
            swapped_off = false;
        }
        carried |= tp.floor_prop == PROP_PLANT && tp.fp_lift > 10.0f;
        prev_held = tp.held;
    }
    mascot_trip_pose(&tf, &tt, trip_s, &tp);
    CHECK(min_x <= PIP_WORLD_L - PIP_OFFSCREEN + 0.5f);
    CHECK(swapped_off && carried);
    CHECK(tp.floor_prop == PROP_PLANT && fabsf(tp.fp_x - 36.0f) < 0.5f && tp.fp_lift < 0.5f && fabsf(tp.x) < 0.5f);

    /* ---- task-specific acts: what PIP does follows the task at hand, not a random pick ---- */
    for (int act_k = 0; act_k < PIP_ACTIVITY_COUNT; act_k++) {
        CHECK_EQ(mascot_activity_from_name(mascot_activity_name((pip_activity_t)act_k)), act_k);
        static const pip_mode_t follows[] = {PIP_MODE_FOCUS, PIP_MODE_PAUSE, PIP_MODE_DONE};
        for (int fm = 0; fm < 3; fm++) {
            pip_mode_t md = follows[fm];
            mascot_anim_init(&an, 500u + (uint32_t)act_k, 0);
            mascot_set_scene(&an, md, PIP_TAG(act_k), 0);
            int matched = 0, tagged = 0;
            for (uint32_t t = 0; t < 30u * 60u * 1000u; t += 50) { /* half an hour on this screen */
                uint32_t before = an.perf_count;
                mascot_anim_step(&an, t);
                if (an.perf_count != before || t == 0) {
                    uint32_t at = mascot_act_tags(md, an.perf.act);
                    tagged++;
                    matched += (at & PIP_TAG(act_k)) != 0u;
                }
            }
            if (matched != tagged) {
                printf("%s/%s: %d of %d acts fit\n", mascot_mode_name(md), mascot_activity_name((pip_activity_t)act_k),
                       matched, tagged);
            }
            CHECK(tagged > 10);
            CHECK_EQ(matched, tagged); /* every activity has its own acts on these screens */
        }
    }
    /* switching activity mid-focus restarts with the new activity's act at once */
    mascot_anim_init(&an, 9, 0);
    mascot_set_scene(&an, PIP_MODE_FOCUS, PIP_TAG(PIP_ACT_WRITE), 0);
    mascot_anim_step(&an, 0);
    mascot_set_scene(&an, PIP_MODE_FOCUS, PIP_TAG(PIP_ACT_CALL), 1000);
    CHECK(mascot_act_tags(PIP_MODE_FOCUS, an.perf.act) & PIP_TAG(PIP_ACT_CALL));
    /* listening follows the picked voice activity */
    for (int vc = 0; vc < 4; vc++) {
        mascot_anim_init(&an, 31, 0);
        mascot_set_scene(&an, PIP_MODE_LISTEN, PIP_TAG_VOICE(vc), 0);
        CHECK(mascot_act_tags(PIP_MODE_LISTEN, an.perf.act) & PIP_TAG_VOICE(vc));
    }
    /* the break follows its own cue, in order: stretch, sip water, look far away, stretch... */
    CHECK(mascot_lib_sequential(PIP_MODE_BREAK) && mascot_lib_sequential(PIP_MODE_THINK));
    mascot_anim_init(&an, 5, 0);
    mascot_set_scene(&an, PIP_MODE_BREAK, 0, 0);
    int order[6], no = 0;
    order[no++] = an.perf.act;
    for (uint32_t t = 50; t < 5u * 60u * 1000u && no < 6; t += 50) {
        uint32_t before = an.perf_count;
        mascot_anim_step(&an, t);
        if (an.perf_count != before) order[no++] = an.perf.act;
    }
    CHECK_EQ(no, 6);
    for (int i = 0; i < no; i++) CHECK_EQ(order[i], i % mascot_act_count(PIP_MODE_BREAK));
    /* thinking: transcribing first, planning acts once the words are in */
    mascot_anim_init(&an, 6, 0);
    mascot_set_scene(&an, PIP_MODE_THINK, PIP_TAG_TRANSCRIBE, 0);
    CHECK(mascot_act_tags(PIP_MODE_THINK, an.perf.act) == PIP_TAG_TRANSCRIBE);
    mascot_set_scene(&an, PIP_MODE_THINK, PIP_TAG_PLANNING, 500);
    CHECK(mascot_act_tags(PIP_MODE_THINK, an.perf.act) == PIP_TAG_PLANNING);
    /* idle with a step lined up: free play, and every third act previews the next task */
    mascot_anim_init(&an, 77, 0);
    mascot_set_scene(&an, PIP_MODE_IDLE, PIP_TAG(PIP_ACT_COOK), 0);
    int previews = 0, plays = 0;
    for (uint32_t t = 0; t < 20u * 60u * 1000u; t += 50) {
        uint32_t before = an.perf_count;
        mascot_anim_step(&an, t);
        if (an.perf_count != before || t == 0) {
            uint32_t at = mascot_act_tags(PIP_MODE_IDLE, an.perf.act);
            CHECK(at == 0u || at == PIP_TAG(PIP_ACT_COOK) || at == PIP_TAG_EGG);
            previews += at == PIP_TAG(PIP_ACT_COOK);
            plays++;
        }
    }
    CHECK(previews * 4 >= plays && previews * 2 <= plays); /* about one in three */

    /* ---- easter eggs: rare on idle, never on the focus screen, a potato now and then when upset ---- */
    {
        int eggs = 0, perfs = 0, focus_eggs = 0, potatoes = 0, errors = 0;
        mascot_anim_init(&an, 2024, 0);
        mascot_set_scene(&an, PIP_MODE_IDLE, 0, 0);
        uint32_t seen = an.perf_count;
        for (uint32_t t = 0; t < 4u * 3600u * 1000u; t += 50) {
            mascot_anim_step(&an, t);
            if (an.perf_count != seen) {
                seen = an.perf_count;
                perfs++;
                eggs += (mascot_act_tags(PIP_MODE_IDLE, an.perf.act) & PIP_TAG_EGG) != 0u;
            }
        }
        printf("eggs: %d of %d idle performances in 4 h\n", eggs, perfs);
        CHECK(eggs >= 3 && eggs * 12 <= perfs); /* "sometimes": a handful an afternoon, well under 1 in 12 */
        mascot_anim_init(&an, 7, 0);
        mascot_set_scene(&an, PIP_MODE_FOCUS, PIP_TAG(PIP_ACT_WRITE), 0);
        seen = an.perf_count;
        for (uint32_t t = 0; t < 3600u * 1000u; t += 50) {
            mascot_anim_step(&an, t);
            if (an.perf_count != seen) {
                seen = an.perf_count;
                focus_eggs += (mascot_act_tags(PIP_MODE_FOCUS, an.perf.act) & PIP_TAG_EGG) != 0u;
            }
        }
        CHECK_EQ(focus_eggs, 0);
        mascot_anim_init(&an, 8, 0);
        mascot_set_scene(&an, PIP_MODE_ERROR, 0, 0);
        seen = an.perf_count;
        for (uint32_t t = 0; t < 30u * 60u * 1000u; t += 50) {
            mascot_anim_step(&an, t);
            if (an.perf_count != seen) {
                seen = an.perf_count;
                errors++;
                potatoes += (mascot_act_tags(PIP_MODE_ERROR, an.perf.act) & PIP_TAG_EGG) != 0u;
            }
        }
        CHECK(potatoes > 0 && potatoes < errors);
        /* a relative only appears behind the smoke: the form flips while the puff is thick */
        for (int ea = 0; ea < mascot_act_count(PIP_MODE_IDLE); ea++) {
            if (!(mascot_act_tags(PIP_MODE_IDLE, ea) & PIP_TAG_EGG)) continue;
            pip_perf_t pf = {PIP_MODE_IDLE, (uint8_t)ea, 0, 1, 1};
            float D = mascot_perf_seconds(&pf);
            mascot_pose_t prev, cur;
            mascot_perf_pose(&pf, 0.0f, D, &prev);
            CHECK_EQ(prev.form, PIP_FORM_PIP);
            for (float t = 0.05f; t <= D; t += 0.05f) {
                mascot_perf_pose(&pf, t, D, &cur);
                if (cur.form != prev.form) CHECK(cur.puff > 0.8f || prev.puff > 0.8f);
                prev = cur;
            }
            CHECK_EQ(prev.form, PIP_FORM_PIP);
        }
    }

    /* ---- hands on the object: typing on the keys, fretting + strumming the guitar ---- */
    {
        pip_perf_t typing = {PIP_MODE_FOCUS, 1, 0, 1, 1}; /* "typing" */
        CHECK(strcmp(mascot_act_name(PIP_MODE_FOCUS, 1), "typing") == 0);
        mascot_pose_t ps;
        pip_rig_t rg;
        mascot_perf_pose(&typing, 3.0f, mascot_perf_seconds(&typing), &ps); /* typing, not glancing up at you */
        mascot_rig(&ps, &rg);
        pip_laptop_t lt;
        mascot_laptop(&ps, &lt);
        CHECK(lt.screen_vis);                                  /* the screen is turned toward you */
        CHECK(ps.fp_x > ps.x + 25.0f && ps.yaw > 20.0f);       /* beside PIP, PIP turned toward it */
        CHECK(lt.lid[2].y < lt.deck[2].y - 12.0f);             /* lid open, standing up from the deck */
        CHECK(ps.fp_x + lt.lid[2].x < (float)(STAGE_X + STAGE_W - STAGE_CX)); /* inside the column stage */
        for (int i = 0; i < 2; i++) { /* both hands on the keys (tapping lifts them up to 2 px) */
            CHECK(fabsf(rg.hand[i].x - (ps.fp_x + lt.keys[i].x)) < 1.5f);
            CHECK(fabsf(rg.hand[i].y - (ps.fp_y + lt.keys[i].y)) < 3.0f);
        }
        CHECK(rg.arm_z[1] > 0.5f && rg.arm_z[0] < 0.0f); /* the arm on the laptop's side in front, the other behind */
        ps.fp_lift = 12.0f; /* carried on a prop trip: lid shut, no screen */
        mascot_laptop(&ps, &lt);
        CHECK(!lt.screen_vis);
        CHECK(fabsf(lt.lid[2].y - lt.deck[1].y) < 3.0f);
        int gi = -1;
        for (int k = 0; k < mascot_act_count(PIP_MODE_FOCUS); k++) {
            if (strcmp(mascot_act_name(PIP_MODE_FOCUS, k), "plays guitar") == 0) gi = k;
        }
        CHECK(gi >= 0);
        pip_perf_t gtr = {PIP_MODE_FOCUS, (uint8_t)gi, 0, 1, 1};
        mascot_perf_pose(&gtr, 6.0f, mascot_perf_seconds(&gtr), &ps);
        mascot_rig(&ps, &rg);
        float cyb = (rg.b_top + rg.b_bot) * 0.5f;
        CHECK(rg.hand[0].x < rg.bx - 18.0f && fabsf(rg.hand[0].y - (cyb - 8.0f)) < 2.0f); /* on the neck */
        CHECK(fabsf(rg.hand[1].x - (rg.bx + 5.0f)) < 2.0f && fabsf(rg.hand[1].y - cyb) < 8.0f); /* strings */

        /* the calendar is held by its edges below the face; pointing at the board, one hand holds it */
        int ci = -1;
        for (int k = 0; k < mascot_act_count(PIP_MODE_IDLE); k++) {
            if (strcmp(mascot_act_name(PIP_MODE_IDLE, k), "check calendar") == 0) ci = k;
        }
        CHECK(ci >= 0);
        pip_perf_t cal = {PIP_MODE_IDLE, (uint8_t)ci, 0, 1, 1};
        float cd = mascot_perf_seconds(&cal);
        mascot_perf_pose(&cal, 2.0f, cd, &ps);
        mascot_rig(&ps, &rg);
        CHECK(ps.held == PROP_CALENDAR);
        CHECK(fabsf(rg.hand[0].x - (rg.held_c.x - 17.0f)) < 0.5f && fabsf(rg.hand[1].x - (rg.held_c.x + 17.0f)) < 0.5f);
        CHECK(rg.held_c.y - 22.0f > rg.h_bot - 3.0f); /* the calendar's top stays below the face */
        mascot_perf_pose(&cal, cd * 0.8f, cd, &ps); /* turned to the board, pointing */
        mascot_rig(&ps, &rg);
        CHECK(fabsf(rg.hand[1].x - (rg.held_c.x + 17.0f)) < 0.5f);
        CHECK(rg.hand[0].y < rg.held_c.y - 12.0f); /* the pointing hand let go and is up */
        CHECK(rg.held_c.x > rg.bx + 5.0f);                        /* held out in front, toward the board */
        cal.variant = 1; /* with a pencil: the left hand writes on the page */
        mascot_perf_pose(&cal, 2.0f, cd, &ps);
        mascot_rig(&ps, &rg);
        CHECK(ps.held_l == PROP_PENCIL);
        CHECK(fabsf(rg.hand[0].x - rg.held_c.x) < 10.0f && rg.hand[0].y < rg.held_c.y);
    }

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

    /* idle: PIP walking behind the board is hidden by it; the board text is untouched */
    static rlcd_fb_t ref;
    m.state = UI_STATE_IDLE_READY;
    m.page = PAGE_FOCUS;
    mascot_home_pose(&m.pose);
    m.pose.x = 2000.0f; /* far off-screen */
    ui_render(&ref, &m, NULL);
    m.pose.x = 160.0f;
    m.pose.behind = 1;
    ui_render(&fb, &m, NULL);
    for (int y = BOARD_Y + 6; y < BOARD_B - 6; y++) {
        CHECK(memcmp(fb.px + y * RLCD_STRIDE + (BOARD_X + 8) / 8, ref.px + y * RLCD_STRIDE + (BOARD_X + 8) / 8,
                     (size_t)((BOARD_R - 8) / 8 - (BOARD_X + 8) / 8)) == 0);
    }
    int shown = 0; /* PIP's feet show under the board, between its short legs */
    for (int y = BOARD_B + 4; y < FLOOR_Y; y++) {
        for (int x = BOARD_X; x <= BOARD_R; x++) {
            shown += fb_get(&fb, x, y) != fb_get(&ref, x, y);
        }
    }
    CHECK(shown > 40);
    m.pose.behind = 0; /* in front it covers the board */
    ui_render(&fb, &m, NULL);
    CHECK(memcmp(fb.px, ref.px, sizeof fb.px) != 0);
    CHECK(ink_in(STAGE_X + STAGE_W, ZONE_TOP, 399, BAR_Y - 1) > 0);
    mascot_home_pose(&m.pose);

    /* slides: whole screens move, header and bar always show the new screen */
    static rlcd_fb_t from, to, out;
    fb_clear(&from, INK_WHITE);
    fb_clear(&to, INK_BLACK);
    ui_slide_compose(&out, &from, &to, 1, 0.0f, ZONE_TOP, BAR_Y);
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, ZONE_TOP, 399, BAR_Y - 1), 0);
    CHECK_EQ(ink_in(0, 0, 399, ZONE_TOP - 1), 400 * ZONE_TOP);
    ui_slide_compose(&out, &from, &to, 1, 0.25f, ZONE_TOP, BAR_Y);
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, ZONE_TOP, 299, BAR_Y - 1), 0); /* old moved left by 100 */
    CHECK_EQ(ink_in(300, ZONE_TOP, 399, BAR_Y - 1), 100 * (BAR_Y - ZONE_TOP));
    ui_slide_compose(&out, &from, &to, -1, 0.25f, ZONE_TOP, BAR_Y);
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, ZONE_TOP, 99, BAR_Y - 1), 100 * (BAR_Y - ZONE_TOP)); /* new enters from the left */
    CHECK_EQ(ink_in(100, ZONE_TOP, 399, BAR_Y - 1), 0);
    ui_slide_compose(&out, &from, &to, 1, 0.37f, ZONE_TOP, BAR_Y); /* odd bit offsets */
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, ZONE_TOP, 399, BAR_Y - 1), 148 * (BAR_Y - ZONE_TOP));
    ui_slide_compose(&out, &from, &to, 2, 0.5f, ZONE_TOP, BAR_Y);
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, ZONE_TOP, 399, ZONE_TOP + 113), 400 * 114); /* top half: the new screen */
    CHECK_EQ(ink_in(0, ZONE_TOP + 114, 399, BAR_Y - 1), 0);
    ui_slide_compose(&out, &from, &to, -2, 1.0f, ZONE_TOP, BAR_Y);
    memcpy(&fb, &out, sizeof fb);
    CHECK_EQ(ink_in(0, 0, 399, 299), 400 * 300);
    CHECK_EQ(ui_slide_dir(SCREEN_IDLE_READY, SCREEN_LISTENING), 1);
    CHECK_EQ(ui_slide_dir(SCREEN_FOCUS_RUNNING, SCREEN_IDLE_READY), -1);
    CHECK_EQ(ui_slide_dir(SCREEN_FOCUS_RUNNING, SCREEN_PAUSED), 0);
    CHECK_EQ(ui_slide_dir(SCREEN_IDLE_READY, SCREEN_DAILY_TASKS), 1);
    CHECK_EQ(ui_slide_dir(SCREEN_IDLE_READY, SCREEN_ALARM_RINGING), 2);
    CHECK_EQ(ui_slide_dir(SCREEN_ERROR, SCREEN_IDLE_READY), -2);

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
