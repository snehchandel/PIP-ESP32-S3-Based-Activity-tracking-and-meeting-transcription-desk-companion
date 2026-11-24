/* Screens 01-06: idle (PIP's full-screen world), listening, thinking, focus running, paused, break. */
#include <stdio.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

static int centered_x(const font_t *f, const char *s) { return CONTENT_X + (CONTENT_W - text_width(f, s)) / 2; }

static int headline(rlcd_fb_t *fb, const font_t *f, const char *s, int y, bool center, ui_meta_t *meta)
{
    int x = center ? centered_x(f, s) : CONTENT_X;
    text_draw_bold(fb, f, x, y, s, INK_BLACK);
    ui_meta_add(meta, "primary_text", x, y, text_width(f, s) + 1, f->line_h, -1);
    return y + f->line_h;
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

/* ---- idle: PIP's world -------------------------------------------------------------------- */
typedef char board_geometry_guard_t[(BOARD_X - STAGE_CX == (int)PIP_BOARD_DX) ? 1 : -1];

/* the room: a floor of planks in gentle perspective and a little window on the back wall */
static void world_backdrop(rlcd_fb_t *fb)
{
    fb_hline(fb, WORLD_X, FLOOR_Y, WORLD_W, 2, INK_BLACK);
    const int y0 = FLOOR_Y + 2, y1 = BAR_Y - 1, vx = 200, vy = -260; /* vanishing point far above */
    for (int x = -60; x <= 460; x += 34) {
        for (int y = y0 + 2; y <= y1; y += 2) {
            int px = vx + (x - vx) * (y - vy) / (y1 - vy);
            if (px >= WORLD_X && px < WORLD_X + WORLD_W) {
                fb_set(fb, px, y, INK_BLACK);
            }
        }
    }
    for (int x = WORLD_X + 1; x < WORLD_X + WORLD_W; x += 3) {
        fb_set(fb, x, y0 + 9, INK_BLACK);
    }
    /* window: frame, cross bars, sill and a bit of glare */
    const int wx = 22, wy = 50, ww = 52, wh = 42;
    fb_rect(fb, wx, wy, ww, wh, 2, INK_BLACK);
    fb_vline(fb, wx + ww / 2 - 1, wy, wh, 2, INK_BLACK);
    fb_hline(fb, wx, wy + wh / 2 - 1, ww, 2, INK_BLACK);
    fb_fill_rect(fb, wx - 4, wy + wh, ww + 8, 3, INK_BLACK);
    fb_line(fb, wx + 6, wy + 13, wx + 13, wy + 6, 1, INK_BLACK);
    fb_line(fb, wx + 6, wy + 18, wx + 18, wy + 6, 1, INK_BLACK);
    fb_line(fb, wx + ww / 2 + 6, wy + wh / 2 + 13, wx + ww / 2 + 13, wy + wh / 2 + 6, 1, INK_BLACK);
}

typedef struct {
    char msg[128];
    int msg_lines;
    int agenda_rows;
    bool footer; /* date line at the bottom of the board */
} board_t;

static int agenda_open(const ui_model_t *m)
{
    int n = 0;
    for (int i = 0; i < m->today_count; i++) {
        n += !m->today[i].done;
    }
    return n;
}

#define BOARD_TX (BOARD_X + BOARD_PAD)
#define BOARD_TW (BOARD_R - BOARD_PAD - BOARD_TX)
#define BOARD_HEAD_Y (BOARD_Y + 7)
#define BOARD_ROW_H (FONT_12.line_h + 1)
#define BOARD_FOOT_Y (BOARD_B - 7 - FONT_11.line_h)

/* lay the board out: the agenda gets the rows that fit; the date shows when there is room for it */
static void board_layout(const ui_model_t *m, board_t *b)
{
    if (m->has_active_step) {
        snprintf(b->msg, sizeof b->msg, "Next: %s (%um)", m->step_title, (unsigned)((m->remaining_ms + 59999u) / 60000u));
    } else {
        snprintf(b->msg, sizeof b->msg, "%s",
                 m->link == LINK_TETHERED ? "Hold KEY and tell me what's on your mind."
                                          : "Plan tasks in the PIP app, then focus here.");
    }
    b->msg_lines = text_draw_wrap(NULL, &FONT_12B, 0, 0, BOARD_TW, 3, 2, b->msg, INK_BLACK);
    int y = BOARD_HEAD_Y + FONT_24B.line_h + 3 + b->msg_lines * (FONT_12B.line_h + 2);
    int open = agenda_open(m);
    b->agenda_rows = 0;
    if (open > 0) {
        y += 8 + FONT_11.line_h + 1;
        int with_foot = (BOARD_FOOT_Y - 3 - y) / BOARD_ROW_H, without = (BOARD_B - 6 - y) / BOARD_ROW_H;
        b->agenda_rows = open <= with_foot ? open : (open < without ? open : without);
    }
    b->footer = m->date_label[0] && y + b->agenda_rows * BOARD_ROW_H + 3 <= BOARD_FOOT_Y;
}

static void board_panel(rlcd_fb_t *fb, int x, int y, int w, int h)
{
    fb_fill_rrect(fb, x + 3, y + 3, w, h, 10, INK_BLACK); /* drop shadow */
    fb_fill_rrect(fb, x, y, w, h, 10, INK_WHITE);
    fb_rrect(fb, x, y, w, h, 10, 2, INK_BLACK);
    fb_rrect(fb, x + 4, y + 4, w - 8, h - 8, 7, 1, INK_BLACK); /* inner bezel */
}

/* free-standing message board on an easel: PIP can walk behind it (legs and feet show underneath) */
static void board_draw(rlcd_fb_t *fb, const ui_model_t *m, const board_t *b, ui_meta_t *meta)
{
    const int x = BOARD_X, w = BOARD_R - BOARD_X, h = BOARD_B - BOARD_Y;
    for (int k = 0; k < 2; k++) { /* easel legs splay out to little feet on the floor */
        int lx = k == 0 ? x + 40 : x + w - 40, foot = k == 0 ? -10 : 10;
        fb_line(fb, lx, BOARD_B - 4, lx + foot, FLOOR_Y - 1, 4, INK_BLACK);
        fb_fill_rrect(fb, lx + foot - 8, FLOOR_Y - 3, 17, 4, 2, INK_BLACK);
    }
    board_panel(fb, x, BOARD_Y, w, h);
    int board = ui_meta_add(meta, "board", x, BOARD_Y, w + 3, h + 3, -1);

    int y = BOARD_HEAD_Y;
    text_draw_bold(fb, &FONT_24B, BOARD_TX, y, "Let's Focus!", INK_BLACK);
    ui_meta_add(meta, "primary_text", BOARD_TX, y, text_width(&FONT_24B, "Let's Focus!") + 1, FONT_24B.line_h, board);
    y += FONT_24B.line_h + 3;
    int n = text_draw_wrap(fb, &FONT_12B, BOARD_TX, y, BOARD_TW, 3, 2, b->msg, INK_BLACK);
    ui_meta_add(meta, "secondary_text", BOARD_TX, y, BOARD_TW, n * (FONT_12B.line_h + 2), board);
    y += n * (FONT_12B.line_h + 2);
    if (b->agenda_rows > 0) {
        y += 8;
        int y0 = y;
        int lw = text_width(&FONT_11, "TODAY"), more = agenda_open(m) - b->agenda_rows, mw = 0;
        text_draw(fb, &FONT_11, BOARD_TX, y, "TODAY", INK_BLACK);
        if (more > 0) { /* the rest is one double press away */
            char buf[24];
            snprintf(buf, sizeof buf, "+%d more", more);
            mw = text_width(&FONT_11, buf) + 6;
            text_draw(fb, &FONT_11, BOARD_TX + BOARD_TW - mw + 6, y, buf, INK_BLACK);
        }
        fb_hline(fb, BOARD_TX + lw + 6, y + 7, BOARD_TW - lw - 6 - mw, 1, INK_BLACK);
        y += FONT_11.line_h + 1;
        int shown = 0;
        for (int i = 0; i < m->today_count && shown < b->agenda_rows; i++) {
            const agenda_item_t *it = &m->today[i];
            if (it->done) {
                continue;
            }
            const char *hh = it->hhmm[0] ? it->hhmm : "any";
            text_draw(fb, &FONT_12B, BOARD_TX, y, hh, INK_BLACK);
            text_draw_fit(fb, &FONT_12, BOARD_TX + 44, y, BOARD_TW - 44, it->title, INK_BLACK);
            y += BOARD_ROW_H;
            shown++;
        }
        ui_meta_add(meta, "agenda_preview", BOARD_TX, y0, BOARD_TW, y - y0, board);
    }
    if (b->footer) {
        text_draw(fb, &FONT_11, BOARD_TX, BOARD_FOOT_Y, m->date_label, INK_BLACK);
        ui_meta_add(meta, "date_text", BOARD_TX, BOARD_FOOT_Y, text_width(&FONT_11, m->date_label), FONT_11.line_h, board);
    }
}

void ui_screen_idle(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    world_backdrop(fb);
    board_t b;
    board_layout(m, &b);
    /* depth: PIP behind the board is drawn first and covered by it */
    if (m->pose.behind) {
        ui_draw_mascot_on(fb, &m->pose, &UI_STAGE_WORLD);
    }
    board_draw(fb, m, &b, meta);
    if (!m->pose.behind) {
        ui_draw_mascot_on(fb, &m->pose, &UI_STAGE_WORLD);
    }
    ui_meta_add(meta, "mascot_stage", MASCOT_X, MASCOT_Y, MASCOT_W, MASCOT_H, -1);
    if (m->has_active_step) {
        ui_hint_t h[] = {{ICON_ARROW, "Start"}, {ICON_CYCLE, "2x: Calendar"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    } else {
        ui_hint_t h[] = {{ICON_MIC, "Hold: Talk"}, {ICON_CYCLE, "2x: Calendar"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    }
}

void ui_screen_listening(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "Listening", meta);
    headline(fb, &FONT_24B, "Listening...", 44, false, meta);
    char t1[8], t2[8], buf[48];
    ui_fmt_mmss(t1, (uint32_t)m->listen_elapsed_s * 1000u);
    ui_fmt_mmss(t2, (uint32_t)(m->listen_max_s ? m->listen_max_s : 60) * 1000u);
    snprintf(buf, sizeof buf, "%s \xC2\xB7 %s / %s", ui_voice_choice_label(m->voice_choice), t1, t2);
    text_draw(fb, &FONT_14B, CONTENT_X, 80, buf, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 80, text_width(&FONT_14B, buf), FONT_14B.line_h, -1);
    /* 10 discrete level bars, graded heights, filled up to the live level */
    const int bw = 16, gap = 7, base = 200;
    for (int i = 0; i < 10; i++) {
        int h = 14 + i * 8;
        int x = CONTENT_X + i * (bw + gap);
        if (i < (int)m->audio_level * 10 / 8) {
            fb_fill_rect(fb, x, base - h, bw, h, INK_BLACK);
        } else {
            fb_rect(fb, x, base - h, bw, h, 2, INK_BLACK);
        }
    }
    ui_meta_add(meta, "level_meter", CONTENT_X, base - 86, 10 * bw + 9 * gap, 86, -1);
    const char *tip = "Say it the way you'd tell a friend.";
    text_draw_fit(fb, &FONT_12, CONTENT_X, 214, CONTENT_W, tip, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 214, CONTENT_W, FONT_12.line_h, -1);
    ui_hint_t h[] = {{ICON_MIC, "Release KEY to send"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_thinking(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "Thinking", meta);
    headline(fb, &FONT_24B, "Planning...", 44, false, meta);
    /* 3-stage pipeline: done = filled dot, current = ring + dot, pending = ring */
    int cur = m->state == UI_STATE_TRANSCRIBING ? 0 : 1;
    const char *labels[3] = {cur == 0 ? "Transcribing..." : "Heard you",
                             m->thinking_stage[0] && cur == 1 ? m->thinking_stage : "Breaking into steps",
                             "Ready to focus"};
    for (int i = 0; i < 3; i++) {
        int y = 92 + i * 32, cx = CONTENT_X + 9, cy = y + 8;
        fb_fill_circle(fb, cx, cy, 8, INK_BLACK);
        if (i >= cur) {
            fb_fill_circle(fb, cx, cy, 5, INK_WHITE);
            if (i == cur) {
                fb_fill_circle(fb, cx, cy, 3, INK_BLACK);
            }
        }
        if (i < 2) {
            fb_vline(fb, cx - 1, cy + 10, 12, 2, INK_BLACK);
        }
        text_draw_fit(fb, i <= cur ? &FONT_14B : &FONT_14, CONTENT_X + 26, y, CONTENT_W - 26, labels[i], INK_BLACK);
    }
    ui_meta_add(meta, "stage_list", CONTENT_X, 92, CONTENT_W, 3 * 32 - 14, -1);
    ui_hint_t h[] = {{-1, "Please wait"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_focus(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_WORKING, "Focus", meta);
    big_timer(fb, m->remaining_ms, 34, meta);
    char badge[96];
    if (m->is_starter) {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 Starter", (unsigned)m->step_index, (unsigned)m->step_total);
    } else {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 %s", (unsigned)m->step_index, (unsigned)m->step_total,
                 m->task_title[0] ? m->task_title : "Focus Time");
    }
    ui_inverted_pill(fb, &FONT_12B, CONTENT_X, 112, badge, meta, "step_badge");
    step_title_block(fb, m, &FONT_14B, 136, 3, meta);
    if (m->next_step_title[0]) {
        char nx[80];
        snprintf(nx, sizeof nx, "Then: %s", m->next_step_title);
        text_draw_fit(fb, &FONT_11, CONTENT_X, 198, CONTENT_W, nx, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 198, CONTENT_W, FONT_11.line_h, -1);
    }
    uint32_t total = m->step_total_ms ? m->step_total_ms : m->remaining_ms;
    ui_progress(fb, CONTENT_X, 228, CONTENT_W, 14, total - (m->remaining_ms > total ? total : m->remaining_ms), total,
                meta);
    ui_hint_t h[] = {{ICON_PAUSE, "Pause"}, {ICON_CHECK, "Done"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_paused(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Paused", meta);
    big_timer(fb, m->remaining_ms, 34, meta);
    ui_inverted_pill(fb, &FONT_12B, CONTENT_X, 112, "Paused", meta, "step_badge");
    step_title_block(fb, m, &FONT_14, 136, 3, meta);
    const char *calm = "No rush \xE2\x80\x94 resume anytime";
    text_draw(fb, &FONT_12, CONTENT_X, 222, calm, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 222, text_width(&FONT_12, calm), FONT_12.line_h, -1);
    ui_hint_t h[] = {{ICON_PLAY, "Resume"}, {-1, "Hold BOOT: Split"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_break(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Break", meta);
    int y = headline(fb, &FONT_24B, "Take a Break!", 48, true, meta) + 12;
    char t[8];
    ui_fmt_mmss(t, m->break_remaining_ms);
    text_draw(fb, &FONT_64, centered_x(&FONT_64, t), y - 8, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", centered_x(&FONT_64, t), y, text_width(&FONT_64, t), FONT_64.line_h - 22, -1);
    const char *cue = "Stretch, sip some water, look far away.";
    int n = text_draw_wrap(fb, &FONT_12, CONTENT_X, y + 70, CONTENT_W, 2, 2, cue, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, y + 70, CONTENT_W, n * (FONT_12.line_h + 2), -1);
    ui_hint_t h[] = {{ICON_CHECK, "ok"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
