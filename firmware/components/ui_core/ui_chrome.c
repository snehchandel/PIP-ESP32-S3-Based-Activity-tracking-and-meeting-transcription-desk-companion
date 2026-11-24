/* Shared screen chrome: top micro-bar, mascot stage, state pill, inverted status bar. */
#include <stdio.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

int ui_meta_add(ui_meta_t *meta, const char *name, int x, int y, int w, int h, int parent)
{
    if (!meta || meta->n >= UI_META_MAX) {
        return -1;
    }
    ui_box_t *b = &meta->boxes[meta->n];
    b->name = name;
    b->r.x = (int16_t)x;
    b->r.y = (int16_t)y;
    b->r.w = (int16_t)w;
    b->r.h = (int16_t)h;
    b->parent = parent;
    return meta->n++;
}

void ui_fmt_mmss(char *out, uint32_t ms)
{
    uint32_t s = (ms + 999u) / 1000u; /* round up so 0:00 only shows when truly done */
    if (s > 5999u) {
        s = 5999u;
    }
    snprintf(out, 8, "%02u:%02u", (unsigned)(s / 60u), (unsigned)(s % 60u));
}

void ui_inverted_pill(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ui_meta_t *meta,
                      const char *name)
{
    int w = text_width(f, s) + 14;
    int h = f->line_h + 2;
    fb_fill_rrect(fb, x, y, w, h, h / 2, INK_BLACK);
    text_draw(fb, f, x + 7, y + 1, s, INK_WHITE);
    ui_meta_add(meta, name, x, y, w, h, -1);
}

/* one reading: [icon] 23° 41%  laid out right-to-left; returns the new right edge */
static int reading(rlcd_fb_t *fb, int rx, int16_t c10, uint8_t hum, int icon, int weather_code, uint32_t ms)
{
    char t[12], h[8];
    snprintf(t, sizeof t, "%d\xC2\xB0", (c10 + (c10 >= 0 ? 5 : -5)) / 10);
    snprintf(h, sizeof h, "%u%%", (unsigned)hum);
    rx -= text_width(&FONT_11, h);
    text_draw(fb, &FONT_11, rx, 14, h, INK_BLACK);
    rx -= text_width(&FONT_16B, t) + 3;
    text_draw(fb, &FONT_16B, rx, 8, t, INK_BLACK);
    if (weather_code >= 0) {
        rx -= 26;
        ui_weather_icon(fb, rx, 5, weather_code, ms);
    } else {
        rx -= UI_ICON_SIZE + 3;
        fb_icon(fb, rx, 8, (ui_icon_t)icon, INK_BLACK);
    }
    return rx;
}

void ui_chrome_top(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    int x = UI_MARGIN;
    char buf[24];
    if (m->clock_valid) { /* big, bold clock: readable from across the desk */
        snprintf(buf, sizeof buf, "%02u:%02u", (unsigned)m->hh, (unsigned)m->mm);
        x += text_draw_bold(fb, &FONT_24B, x, 3, buf, INK_BLACK) + 8;
    }
    /* link status lives in the bottom bar only */
    ui_meta_add(meta, "top_left", UI_MARGIN, 3, x - UI_MARGIN, 29, -1);
    /* right cluster, right-to-left: outdoor weather (animated), indoor sensor, next alarm (if room) */
    int rx = RLCD_W - UI_MARGIN, x_right = rx, left_limit = x + 8;
    if (m->out_valid) {
        rx = reading(fb, rx, m->out_temp_c10, m->out_hum, 0, m->out_code, m->anim_ms) - 8;
    }
    if (m->in_valid) {
        rx = reading(fb, rx, m->in_temp_c10, m->in_hum, ICON_HOME, -1, 0) - 8;
    }
    if (m->next_alarm_hhmm[0]) {
        int w = text_width(&FONT_12B, m->next_alarm_hhmm) + UI_ICON_SIZE + 3;
        if (rx - w >= left_limit) {
            rx -= text_width(&FONT_12B, m->next_alarm_hhmm);
            text_draw(fb, &FONT_12B, rx, 10, m->next_alarm_hhmm, INK_BLACK);
            rx -= UI_ICON_SIZE + 3;
            fb_icon(fb, rx, 8, ICON_BELL, INK_BLACK);
        }
    }
    if (rx < x_right) {
        ui_meta_add(meta, "top_right", rx, 5, x_right - rx, 26, -1);
    }
    fb_hline(fb, UI_MARGIN, TOPBAR_RULE_Y, RLCD_W - 2 * UI_MARGIN, 1, INK_BLACK);
}

/* the ground PIP stands on in its column: a short floor line that fades out at both ends */
static void column_floor(rlcd_fb_t *fb)
{
    fb_hline(fb, STAGE_X + 14, FLOOR_Y, STAGE_W - 28, 2, INK_BLACK);
    for (int x = STAGE_X + 4; x < STAGE_X + 14; x += 3) {
        fb_set(fb, x, FLOOR_Y, INK_BLACK);
        fb_set(fb, STAGE_X + STAGE_W - 1 - (x - STAGE_X), FLOOR_Y, INK_BLACK);
    }
}

void ui_chrome_mascot(rlcd_fb_t *fb, const ui_model_t *m, int expr, const char *label, ui_meta_t *meta)
{
    /* PIP stands in the left column and looks toward the text. */
    (void)label;
    (void)expr;
    column_floor(fb);
    ui_draw_mascot(fb, &m->pose);
    ui_meta_add(meta, "mascot_stage", MASCOT_X, MASCOT_Y, MASCOT_W, MASCOT_H, -1);
}

static void battery_glyph(rlcd_fb_t *fb, int x, int y, const ui_model_t *m)
{
    fb_rect(fb, x, y, 22, 12, 2, INK_WHITE);
    fb_fill_rect(fb, x + 22, y + 3, 2, 6, INK_WHITE);
    if (m->batt_valid) {
        int fill = (int)m->batt_pct * 16 / 100;
        fb_fill_rect(fb, x + 3, y + 3, fill, 6, INK_WHITE);
    }
}

void ui_chrome_bar(rlcd_fb_t *fb, const ui_model_t *m, const ui_hint_t *hints, int n, ui_meta_t *meta)
{
    const font_t *f = &FONT_12B;
    fb_fill_rect(fb, 0, BAR_Y, RLCD_W, BAR_H, INK_BLACK);
    int bar = ui_meta_add(meta, "bottom_bar", 0, BAR_Y, RLCD_W, BAR_H, -1);
    int ty = BAR_Y + (BAR_H - f->line_h) / 2;
    int iy = BAR_Y + (BAR_H - UI_ICON_SIZE) / 2;
    int x = UI_MARGIN + 2;
    for (int i = 0; i < n; i++) {
        if (hints[i].icon >= 0) {
            fb_icon(fb, x, iy, (ui_icon_t)hints[i].icon, INK_WHITE);
            x += UI_ICON_SIZE + 5;
        }
        x += text_draw(fb, f, x, ty, hints[i].label, INK_WHITE) + 12;
    }
    ui_meta_add(meta, "bar_hints", UI_MARGIN, ty, x - UI_MARGIN - 12, f->line_h, bar);

    /* right cluster: link state, battery glyph, percentage */
    char pct[8];
    if (m->batt_valid) {
        snprintf(pct, sizeof pct, "%u%%", (unsigned)m->batt_pct);
    } else {
        snprintf(pct, sizeof pct, "--%%");
    }
    int pw = text_width(f, pct);
    int rx = RLCD_W - UI_MARGIN - 2 - pw;
    text_draw(fb, f, rx, ty, pct, INK_WHITE);
    rx -= 30;
    battery_glyph(fb, rx, BAR_Y + (BAR_H - 12) / 2, m);
    rx -= 26;
    fb_icon(fb, rx, iy, m->link == LINK_TETHERED ? ICON_LINK : ICON_LINK_OFF, INK_WHITE);
    if (m->link != LINK_TETHERED) {
        rx -= text_width(&FONT_11, "OFFLINE") + 4;
        text_draw(fb, &FONT_11, rx, BAR_Y + (BAR_H - FONT_11.line_h) / 2, "OFFLINE", INK_WHITE);
    }
    ui_meta_add(meta, "bar_status", rx, iy, RLCD_W - UI_MARGIN - rx, UI_ICON_SIZE, bar);
}

void ui_progress(rlcd_fb_t *fb, int x, int y, int w, int h, uint32_t done, uint32_t total, ui_meta_t *meta)
{
    fb_rrect(fb, x, y, w, h, h / 2, 2, INK_BLACK);
    if (total > 0) {
        uint64_t inner = (uint64_t)(w - 6) * (done > total ? total : done) / total;
        if (inner > 0) {
            fb_fill_rrect(fb, x + 3, y + 3, (int)inner, h - 6, (h - 6) / 2, INK_BLACK);
        }
    }
    ui_meta_add(meta, "progress_bar", x, y, w, h, -1);
}
