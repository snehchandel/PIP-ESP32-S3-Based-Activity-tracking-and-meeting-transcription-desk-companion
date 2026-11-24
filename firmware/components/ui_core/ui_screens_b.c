/* Screens 07-11: step done, today's calendar, alarm, needs confirmation, standalone sleep. */
#include <stdio.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

static void headline(rlcd_fb_t *fb, const font_t *f, int y, const char *s, ui_meta_t *meta)
{
    text_draw_bold(fb, f, CONTENT_X, y, s, INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, y, text_width(f, s) + 1, f->line_h, -1);
}

void ui_screen_done(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_DONE, "Nice!", meta);
    headline(fb, &FONT_24B, 44, "Step Done!", meta);
    const char *done = m->done_title[0] ? m->done_title : "Step complete";
    int n = text_draw_wrap(fb, &FONT_12, CONTENT_X, 80, CONTENT_W, 3, 2, done, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 80, CONTENT_W, n * (FONT_12.line_h + 2), -1);
    if (m->next_step_title[0]) {
        text_draw(fb, &FONT_11, CONTENT_X, 142, "UP NEXT", INK_BLACK);
        char buf[96];
        snprintf(buf, sizeof buf, "%s (%um)", m->next_step_title, (unsigned)m->next_step_min);
        int k = text_draw_wrap(fb, &FONT_14B, CONTENT_X, 158, CONTENT_W, 3, 2, buf, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 142, CONTENT_W, 16 + k * (FONT_14B.line_h + 2), -1);
        ui_hint_t h[] = {{ICON_PLAY, "Next"}, {ICON_CHECK, "Rest"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    } else {
        const char *fin = "All steps finished. Well done.";
        int k = text_draw_wrap(fb, &FONT_14B, CONTENT_X, 150, CONTENT_W, 2, 2, fin, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 150, CONTENT_W, k * (FONT_14B.line_h + 2), -1);
        ui_hint_t h[] = {{ICON_CHECK, "ok"}};
        ui_chrome_bar(fb, m, h, 1, meta);
    }
}

static void kind_mark(rlcd_fb_t *fb, int x, int y, const agenda_item_t *it)
{
    /* task: box (ticked when done) - reminder: ring - alarm: bell-ish filled dot */
    if (it->kind == 2) {
        fb_fill_circle(fb, x + 5, y + 7, 5, INK_BLACK);
        fb_fill_rect(fb, x + 4, y + 11, 3, 3, INK_BLACK);
    } else if (it->kind == 1) {
        fb_fill_circle(fb, x + 5, y + 7, 5, INK_BLACK);
        fb_fill_circle(fb, x + 5, y + 7, 3, INK_WHITE);
    } else {
        fb_rect(fb, x, y + 2, 11, 11, 2, INK_BLACK);
        if (it->done) {
            fb_line(fb, x + 2, y + 7, x + 4, y + 10, 2, INK_BLACK);
            fb_line(fb, x + 4, y + 10, x + 9, y + 4, 2, INK_BLACK);
        }
    }
}

void ui_screen_daily(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_READY, "Today", meta);
    const char *date = m->date_label[0] ? m->date_label : "Today";
    headline(fb, &FONT_20B, 40, date, meta);
    fb_hline(fb, CONTENT_X, 66, CONTENT_W, 2, INK_BLACK);
    int y = 72;
    if (m->today_count == 0) {
        int n = text_draw_wrap(fb, &FONT_14B, CONTENT_X, y + 4, CONTENT_W, 2, 2, "Nothing scheduled today. Breathe.", INK_BLACK);
        ui_meta_add(meta, "checklist_rows", CONTENT_X, y + 4, CONTENT_W, n * (FONT_14B.line_h + 2), -1);
    } else {
        /* timeline: time column, rail with a mark per item, title (struck through when done) */
        int rows = m->today_count > UI_AGENDA_MAX ? UI_AGENDA_MAX : m->today_count;
        const int row_h = 20, tx = CONTENT_X, mx = CONTENT_X + 42, title_x = CONTENT_X + 60;
        int now = m->clock_valid ? (int)m->hh * 60 + (int)m->mm : -1;
        bool now_drawn = false;
        fb_vline(fb, mx + 5, y + 4, rows * row_h - 6, 1, INK_BLACK);
        for (int i = 0; i < rows; i++) {
            const agenda_item_t *it = &m->today[i];
            int ry = y + i * row_h;
            int mins = it->hhmm[0] ? (it->hhmm[0] - '0') * 600 + (it->hhmm[1] - '0') * 60 + (it->hhmm[3] - '0') * 10 +
                                         (it->hhmm[4] - '0')
                                   : -1;
            if (!now_drawn && now >= 0 && mins > now) { /* "now" marker above the first future item */
                fb_fill_triangle(fb, mx - 2, ry - 3, mx - 2, ry + 3, mx + 3, ry, INK_BLACK);
                for (int dx = title_x; dx < CONTENT_R; dx += 3) {
                    fb_set(fb, dx, ry, INK_BLACK);
                }
                now_drawn = true;
            }
            text_draw(fb, &FONT_12B, tx, ry + 1, it->hhmm[0] ? it->hhmm : "any", INK_BLACK);
            fb_fill_rect(fb, mx - 1, ry + 1, 13, 14, INK_WHITE);
            kind_mark(fb, mx, ry, it);
            text_draw_fit(fb, it->done ? &FONT_12 : &FONT_12B, title_x, ry + 1, CONTENT_R - title_x, it->title, INK_BLACK);
            if (it->done) {
                int w = text_width(&FONT_12, it->title);
                w = w > CONTENT_R - title_x ? CONTENT_R - title_x : w;
                fb_hline(fb, title_x, ry + 8, w, 1, INK_BLACK);
            }
        }
        ui_meta_add(meta, "checklist_rows", CONTENT_X, y, CONTENT_W, rows * row_h, -1);
    }
    char sum[48];
    snprintf(sum, sizeof sum, "Tomorrow: %u items \xC2\xB7 Parked: %u", (unsigned)m->tomorrow_count,
             (unsigned)m->parked_count);
    text_draw_fit(fb, &FONT_11, CONTENT_X, 240, CONTENT_W, sum, INK_BLACK);
    ui_meta_add(meta, "summary_text", CONTENT_X, 240, CONTENT_W, FONT_11.line_h, -1);
    ui_hint_t h[] = {{ICON_ARROW, "Focus"}, {ICON_CYCLE, "2x: Back"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_alarm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_ALARM, "Alarm!", meta);
    char pill[24];
    snprintf(pill, sizeof pill, "ALARM \xC2\xB7 %s", m->alarm_hhmm[0] ? m->alarm_hhmm : "--:--");
    ui_inverted_pill(fb, &FONT_16B, CONTENT_X, 44, pill, meta, "alarm_pill");
    const char *title = m->alarm_title[0] ? m->alarm_title : "Alarm";
    int n = text_draw_wrap(fb, &FONT_20B, CONTENT_X, 80, CONTENT_W, 3, 2, title, INK_BLACK);
    text_draw_wrap(fb, &FONT_20B, CONTENT_X + 1, 80, CONTENT_W, 3, 2, title, INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 80, CONTENT_W, n * (FONT_20B.line_h + 2), -1);
    fb_icon(fb, CONTENT_X, 190, m->alarm_audio ? ICON_MIC : ICON_BELL, INK_BLACK);
    text_draw(fb, &FONT_12B, CONTENT_X + 24, 192, m->alarm_audio ? "Voice wake-up, then chimes" : "Chimes", INK_BLACK);
    ui_meta_add(meta, "audio_indicator", CONTENT_X, 190, CONTENT_W, 18, -1);
    ui_hint_t h[] = {{-1, "KEY: Snooze 5m"}, {-1, "2x/BOOT: Dismiss"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_confirm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "Check", meta);
    headline(fb, &FONT_20B, 44, "Confirm Time", meta);
    const char *q = m->clarification[0] ? m->clarification : "Is this time right?";
    /* question framed as a card so it reads as "the thing to answer" */
    int n = text_draw_wrap(NULL, &FONT_14B, 0, 0, CONTENT_W - 20, 4, 3, q, INK_BLACK);
    int card_h = n * 20 + 16;
    fb_rrect(fb, CONTENT_X, 80, CONTENT_W, card_h, 10, 2, INK_BLACK);
    text_draw_wrap(fb, &FONT_14B, CONTENT_X + 10, 88, CONTENT_W - 20, 4, 3, q, INK_BLACK);
    ui_meta_add(meta, "question_card", CONTENT_X, 80, CONTENT_W, card_h, -1);
    text_draw(fb, &FONT_11, CONTENT_X, 226, "Edit in Companion App", INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 226, text_width(&FONT_11, "Edit in Companion App"), FONT_11.line_h, -1);
    ui_hint_t h[] = {{ICON_CHECK, "Confirm"}, {ICON_ARROW, "Dismiss"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_sleep(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    int err = m->state == UI_STATE_ERROR_RECOVERABLE;
    ui_chrome_mascot(fb, m, PIP_EXPR_SLEEP, err ? "Hmm!" : "Zzz", meta);
    headline(fb, &FONT_24B, 44, err ? "Hiccup" : "Resting", meta);
    if (m->clock_valid) {
        char t[8];
        snprintf(t, sizeof t, "%02u:%02u", (unsigned)m->hh, (unsigned)m->mm);
        text_draw(fb, &FONT_64, CONTENT_X, 80, t, INK_BLACK);
        ui_meta_add(meta, "timer_digits", CONTENT_X, 88, text_width(&FONT_64, t), FONT_64.line_h - 22, -1);
    }
    char buf[48];
    if (err) {
        snprintf(buf, sizeof buf, "%s", m->toast[0] ? m->toast : "Reconnect USB to resync");
    } else if (m->next_alarm_hhmm[0]) {
        snprintf(buf, sizeof buf, "Next alarm %s", m->next_alarm_hhmm);
    } else {
        snprintf(buf, sizeof buf, "No alarms set");
    }
    text_draw_fit(fb, &FONT_14B, CONTENT_X, 184, CONTENT_W, buf, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 184, CONTENT_W, FONT_14B.line_h, -1);
    ui_hint_t h[] = {{-1, "Press any key to wake"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
