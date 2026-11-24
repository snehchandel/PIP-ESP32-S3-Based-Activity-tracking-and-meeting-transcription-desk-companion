/* Screens 07-11: step done, daily tasks, alarm, needs confirmation, standalone sleep. */
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
    headline(fb, &FONT_32B, 40, "Step Done!", meta);
    const char *done = m->done_title[0] ? m->done_title : "Step complete";
    int n = text_draw_wrap(fb, &FONT_16, CONTENT_X, 86, CONTENT_W, 2, 2, done, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 86, CONTENT_W, n * 21, -1);
    if (m->next_step_title[0]) {
        text_draw(fb, &FONT_14, CONTENT_X, 150, "Up next:", INK_BLACK);
        char buf[96];
        snprintf(buf, sizeof buf, "%s (%um)", m->next_step_title, (unsigned)m->next_step_min);
        int k = text_draw_wrap(fb, &FONT_16B, CONTENT_X, 170, CONTENT_W, 2, 2, buf, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 150, CONTENT_W, 20 + k * 21, -1);
        ui_hint_t h[] = {{ICON_PLAY, "Next"}, {ICON_CHECK, "Rest"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    } else {
        const char *fin = "All steps finished. Well done.";
        text_draw_wrap(fb, &FONT_16B, CONTENT_X, 150, CONTENT_W, 2, 2, fin, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 150, CONTENT_W, 42, -1);
        ui_hint_t h[] = {{ICON_CHECK, "ok"}};
        ui_chrome_bar(fb, m, h, 1, meta);
    }
}

static void checkbox(rlcd_fb_t *fb, int x, int y, int checked)
{
    fb_rect(fb, x, y, 18, 18, 2, INK_BLACK);
    if (checked) {
        fb_line(fb, x + 4, y + 9, x + 7, y + 13, 2, INK_BLACK);
        fb_line(fb, x + 7, y + 13, x + 14, y + 4, 2, INK_BLACK);
    }
}

void ui_screen_daily(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_READY, "Today", meta);
    const char *date = m->date_label[0] ? m->date_label : "Today";
    headline(fb, &FONT_24B, 32, date, meta);
    fb_hline(fb, CONTENT_X, 64, CONTENT_W, 2, INK_BLACK);
    int y = 76;
    if (m->today_count == 0) {
        text_draw_wrap(fb, &FONT_16, CONTENT_X, y, CONTENT_W, 2, 2, "Nothing scheduled today. Breathe.", INK_BLACK);
        ui_meta_add(meta, "checklist_rows", CONTENT_X, y, CONTENT_W, 42, -1);
    } else {
        int rows = m->today_count > UI_AGENDA_MAX ? UI_AGENDA_MAX : m->today_count;
        for (int i = 0; i < rows; i++) {
            const agenda_item_t *it = &m->today[i];
            int ry = y + i * 34;
            checkbox(fb, CONTENT_X, ry, it->done);
            char buf[56];
            if (it->hhmm[0]) {
                snprintf(buf, sizeof buf, "%s %s", it->hhmm, it->title);
            } else {
                snprintf(buf, sizeof buf, "%s", it->title);
            }
            text_draw_fit(fb, &FONT_16, CONTENT_X + 28, ry - 1, CONTENT_W - 28, buf, INK_BLACK);
        }
        ui_meta_add(meta, "checklist_rows", CONTENT_X, y, CONTENT_W, rows * 34 - 14, -1);
    }
    char sum[48];
    snprintf(sum, sizeof sum, "Tomorrow: %u items \xC2\xB7 Parked: %u", (unsigned)m->tomorrow_count,
             (unsigned)m->parked_count);
    text_draw_fit(fb, &FONT_14, CONTENT_X, 224, CONTENT_W, sum, INK_BLACK);
    ui_meta_add(meta, "summary_text", CONTENT_X, 224, CONTENT_W, FONT_14.line_h, -1);
    ui_hint_t h[] = {{ICON_ARROW, "Focus"}, {ICON_CYCLE, "2x: Back"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_alarm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_ALARM, "Alarm!", meta);
    char pill[24];
    snprintf(pill, sizeof pill, "ALARM \xC2\xB7 %s", m->alarm_hhmm[0] ? m->alarm_hhmm : "--:--");
    ui_inverted_pill(fb, &FONT_16B, CONTENT_X, 38, pill, meta, "alarm_pill");
    const char *title = m->alarm_title[0] ? m->alarm_title : "Alarm";
    int n = text_draw_wrap(fb, &FONT_24B, CONTENT_X, 76, CONTENT_W, 2, 2, title, INK_BLACK);
    text_draw_wrap(fb, &FONT_24B, CONTENT_X + 1, 76, CONTENT_W, 2, 2, title, INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 76, CONTENT_W, n * 31, -1);
    fb_icon(fb, CONTENT_X, 180, m->alarm_audio ? ICON_MIC : ICON_BELL, INK_BLACK);
    text_draw(fb, &FONT_16, CONTENT_X + 26, 179, m->alarm_audio ? "Voice" : "Chime", INK_BLACK);
    ui_meta_add(meta, "audio_indicator", CONTENT_X, 179, 80, 19, -1);
    ui_hint_t h[] = {{-1, "KEY: +5m Snooze"}, {-1, "2x/BOOT: Dismiss"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_confirm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "Check", meta);
    headline(fb, &FONT_24B, 44, "Confirm Time", meta);
    const char *q = m->clarification[0] ? m->clarification : "Is this time right?";
    int n = text_draw_wrap(fb, &FONT_16B, CONTENT_X, 88, CONTENT_W, 3, 3, q, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 88, CONTENT_W, n * 22, -1);
    text_draw(fb, &FONT_14, CONTENT_X, 206, "Edit in Companion App", INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 206, text_width(&FONT_14, "Edit in Companion App"), 17, -1);
    ui_hint_t h[] = {{ICON_CHECK, "Confirm"}, {ICON_ARROW, "Dismiss"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_sleep(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    int err = m->state == UI_STATE_ERROR_RECOVERABLE;
    ui_chrome_mascot(fb, m, PIP_EXPR_SLEEP, err ? "Hmm!" : "Zzz", meta);
    headline(fb, &FONT_32B, 38, err ? "Hiccup" : "Resting", meta);
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
    text_draw_fit(fb, &FONT_16, CONTENT_X, 184, CONTENT_W, buf, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 184, CONTENT_W, FONT_16.line_h, -1);
    ui_hint_t h[] = {{-1, "Press any key to wake"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
