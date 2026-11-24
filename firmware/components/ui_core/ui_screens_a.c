/* Screens 01-06: idle, listening, thinking, focus running, paused, break. */
#include <stdio.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

static int centered_x(const font_t *f, const char *s) { return CONTENT_X + (CONTENT_W - text_width(f, s)) / 2; }

/* Two-line hero headline (e.g. "Let's\nFocus!") centred in the content zone. */
static int hero(rlcd_fb_t *fb, const char *l1, const char *l2, int y, ui_meta_t *meta)
{
    const font_t *f = &FONT_32B;
    int w1 = text_width(f, l1), w2 = l2 ? text_width(f, l2) : 0;
    int w = w1 > w2 ? w1 : w2;
    text_draw_bold(fb, f, centered_x(f, l1), y, l1, INK_BLACK);
    int h = f->line_h;
    if (l2) {
        text_draw_bold(fb, f, centered_x(f, l2), y + f->line_h, l2, INK_BLACK);
        h += f->line_h;
    }
    ui_meta_add(meta, "primary_text", CONTENT_X + (CONTENT_W - w) / 2, y, w + 1, h, -1);
    return y + h;
}

static void big_timer(rlcd_fb_t *fb, uint32_t ms, int y, ui_meta_t *meta)
{
    char t[8];
    ui_fmt_mmss(t, ms);
    int w = text_width(&FONT_64, t);
    int x = CONTENT_X + (CONTENT_W - w) / 2;
    text_draw(fb, &FONT_64, x, y, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", x, y + 8, w, FONT_64.line_h - 22, -1);
}

static void step_title_block(rlcd_fb_t *fb, const ui_model_t *m, const font_t *f, int y, int lines, ui_meta_t *meta)
{
    int n = text_draw_wrap(fb, f, CONTENT_X, y, CONTENT_W, lines, 2, m->step_title, INK_BLACK);
    ui_meta_add(meta, "step_title", CONTENT_X, y, CONTENT_W, n * (f->line_h + 2), -1);
}

void ui_screen_idle(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_READY, "Ready", meta);
    int y = hero(fb, "Let's", "Focus!", 46, meta) + 18;
    char buf[128];
    if (m->has_active_step) {
        snprintf(buf, sizeof buf, "Next: %s (%um)", m->step_title, (unsigned)((m->remaining_ms + 59999u) / 60000u));
        int n = text_draw_wrap(fb, &FONT_16B, CONTENT_X, y, CONTENT_W, 2, 2, buf, INK_BLACK);
        ui_meta_add(meta, "secondary_text", CONTENT_X, y, CONTENT_W, n * 21, -1);
        ui_hint_t h[] = {{ICON_ARROW, "Start"}, {ICON_CYCLE, "Agenda"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    } else {
        const char *msg = m->link == LINK_TETHERED ? "Hold KEY and tell me what's on your mind."
                                                   : "Plan tasks in the PIP app, then focus here.";
        int n = text_draw_wrap(fb, &FONT_16B, CONTENT_X, y, CONTENT_W, 3, 2, msg, INK_BLACK);
        ui_meta_add(meta, "secondary_text", CONTENT_X, y, CONTENT_W, n * 21, -1);
        ui_hint_t h[] = {{ICON_MIC, "Hold: Talk"}, {ICON_CYCLE, "Agenda"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    }
}

void ui_screen_listening(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "Listening", meta);
    text_draw_bold(fb, &FONT_24B, CONTENT_X, 44, "Listening...", INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 44, text_width(&FONT_24B, "Listening...") + 1, FONT_24B.line_h, -1);
    char t1[8], t2[8], buf[24];
    ui_fmt_mmss(t1, (uint32_t)m->listen_elapsed_s * 1000u);
    ui_fmt_mmss(t2, (uint32_t)(m->listen_max_s ? m->listen_max_s : 60) * 1000u);
    snprintf(buf, sizeof buf, "%s / %s", t1, t2);
    text_draw(fb, &FONT_16B, CONTENT_X, 84, buf, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 84, text_width(&FONT_16B, buf), FONT_16B.line_h, -1);
    /* 8 discrete level bars, graded heights, filled up to the live level */
    const int bw = 20, gap = 8, base = 196;
    for (int i = 0; i < 8; i++) {
        int h = 18 + i * 9;
        int x = CONTENT_X + i * (bw + gap);
        if (i < m->audio_level) {
            fb_fill_rect(fb, x, base - h, bw, h, INK_BLACK);
        } else {
            fb_rect(fb, x, base - h, bw, h, 2, INK_BLACK);
        }
    }
    ui_meta_add(meta, "level_meter", CONTENT_X, base - 81, 8 * bw + 7 * gap, 81, -1);
    ui_hint_t h[] = {{ICON_MIC, "Release KEY to send"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_thinking(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "Thinking", meta);
    text_draw_bold(fb, &FONT_32B, CONTENT_X, 44, "Planning...", INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 44, text_width(&FONT_32B, "Planning...") + 1, FONT_32B.line_h, -1);
    /* 3-stage pipeline: done = filled dot, current = ring + dot, pending = ring */
    int cur = m->state == UI_STATE_TRANSCRIBING ? 0 : 1;
    const char *labels[3] = {cur == 0 ? "Transcribing..." : "Heard you",
                             m->thinking_stage[0] && cur == 1 ? m->thinking_stage : "Breaking into steps",
                             "Ready to focus"};
    for (int i = 0; i < 3; i++) {
        int y = 98 + i * 34, cx = CONTENT_X + 10, cy = y + 10;
        if (i < cur) {
            fb_fill_circle(fb, cx, cy, 9, INK_BLACK);
        } else {
            fb_fill_circle(fb, cx, cy, 9, INK_BLACK);
            fb_fill_circle(fb, cx, cy, 6, INK_WHITE);
            if (i == cur) {
                fb_fill_circle(fb, cx, cy, 3, INK_BLACK);
            }
        }
        if (i < 2) {
            fb_vline(fb, cx - 1, cy + 11, 13, 2, INK_BLACK);
        }
        text_draw_fit(fb, i <= cur ? &FONT_16B : &FONT_16, CONTENT_X + 30, y, CONTENT_W - 30, labels[i], INK_BLACK);
    }
    ui_meta_add(meta, "stage_list", CONTENT_X, 98, CONTENT_W, 3 * 34 - 14, -1);
    ui_hint_t h[] = {{-1, "Please wait"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_focus(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_WORKING, "Focus", meta);
    big_timer(fb, m->remaining_ms, 26, meta);
    char badge[40];
    if (m->is_starter) {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 Starter", (unsigned)m->step_index, (unsigned)m->step_total);
    } else {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 Focus Time", (unsigned)m->step_index, (unsigned)m->step_total);
    }
    ui_inverted_pill(fb, &FONT_14, CONTENT_X, 106, badge, meta, "step_badge");
    step_title_block(fb, m, &FONT_16B, 136, 2, meta);
    uint32_t total = m->step_total_ms ? m->step_total_ms : m->remaining_ms;
    ui_progress(fb, CONTENT_X, 222, CONTENT_W, 14, total - (m->remaining_ms > total ? total : m->remaining_ms), total,
                meta);
    ui_hint_t h[] = {{ICON_PAUSE, "Pause"}, {ICON_CHECK, "Done"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_paused(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Paused", meta);
    big_timer(fb, m->remaining_ms, 26, meta);
    ui_inverted_pill(fb, &FONT_14, CONTENT_X, 106, "Paused", meta, "step_badge");
    step_title_block(fb, m, &FONT_16, 136, 2, meta);
    const char *calm = "No rush \xE2\x80\x94 resume anytime";
    text_draw(fb, &FONT_14, CONTENT_X, 216, calm, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 216, text_width(&FONT_14, calm), FONT_14.line_h, -1);
    ui_hint_t h[] = {{ICON_PLAY, "Resume"}, {-1, "Hold BOOT: Split"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_break(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Break", meta);
    int y = hero(fb, "Take", "a Break!", 40, meta) + 12;
    char t[8];
    ui_fmt_mmss(t, m->break_remaining_ms);
    text_draw_bold(fb, &FONT_24B, centered_x(&FONT_24B, t), y, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", centered_x(&FONT_24B, t), y, text_width(&FONT_24B, t) + 1, FONT_24B.line_h, -1);
    const char *cue = "Stretch or grab water";
    text_draw(fb, &FONT_16, centered_x(&FONT_16, cue), y + 44, cue, INK_BLACK);
    ui_meta_add(meta, "calm_text", centered_x(&FONT_16, cue), y + 44, text_width(&FONT_16, cue), FONT_16.line_h, -1);
    ui_hint_t h[] = {{ICON_CHECK, "ok"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
