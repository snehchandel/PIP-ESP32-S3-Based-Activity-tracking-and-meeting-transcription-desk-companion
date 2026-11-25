/* Screens 12-14: voice activity picker, error screen and meeting recording. */
#include <stdio.h>
#include <string.h>

#include "ui_layout.h"
#include "ui_render.h"

/* "Meeting" has no icon of its own: two heads and shoulders, drawn in the row's ink */
static void people_glyph(rlcd_fb_t *fb, int x, int y, ink_t ink)
{
    fb_fill_circle(fb, x + 5, y + 5, 3, ink);
    fb_fill_circle(fb, x + 13, y + 5, 3, ink);
    fb_fill_rrect(fb, x, y + 10, 10, 7, 3, ink);
    fb_fill_rrect(fb, x + 8, y + 10, 10, 7, 3, ink);
}

void ui_screen_voice_pick(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    static const int icons[UI_VOICE_CHOICES] = {ICON_CYCLE, ICON_MIC, ICON_PLAY, ICON_BELL, -1};
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "", meta);
    text_draw_bold(fb, &FONT_20B, CONTENT_X, 40, "What's it about?", INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 40, text_width(&FONT_20B, "What's it about?") + 1, FONT_20B.line_h, -1);
    const int row_h = 29, gap = 5, y0 = 68;
    for (int i = 0; i < UI_VOICE_CHOICES; i++) {
        int y = y0 + i * (row_h + gap);
        bool sel = i == m->voice_choice;
        if (sel) {
            fb_fill_rrect(fb, CONTENT_X, y, CONTENT_W, row_h, 10, INK_BLACK);
        } else {
            fb_rrect(fb, CONTENT_X, y, CONTENT_W, row_h, 10, 2, INK_BLACK);
        }
        ink_t ink = sel ? INK_WHITE : INK_BLACK;
        int iy = y + (row_h - UI_ICON_SIZE) / 2;
        if (icons[i] >= 0) {
            fb_icon(fb, CONTENT_X + 12, iy, (ui_icon_t)icons[i], ink);
        } else {
            people_glyph(fb, CONTENT_X + 12, iy, ink);
        }
        text_draw(fb, &FONT_16B, CONTENT_X + 40, y + (row_h - FONT_16B.line_h) / 2, ui_voice_choice_label((uint8_t)i), ink);
    }
    int list_h = UI_VOICE_CHOICES * (row_h + gap) - gap;
    ui_meta_add(meta, "choice_list", CONTENT_X, y0, CONTENT_W, list_h, -1);
    if (m->wake_label[0]) { /* hands-free: the wake word again starts talking about the highlighted option */
        char tip[48];
        snprintf(tip, sizeof tip, "Say \"%s\" again to talk", m->wake_label);
        int yt = y0 + list_h + 3;
        text_draw_fit(fb, &FONT_12B, CONTENT_X, yt, CONTENT_W, tip, INK_BLACK);
        ui_meta_add(meta, "wake_tip", CONTENT_X, yt, CONTENT_W, FONT_12B.line_h, -1);
    }
    ui_hint_t h[] = {{ICON_ARROW, "Next"}, {ICON_MIC, m->voice_choice == UI_VOICE_MEETING ? "Hold: record" : "Hold: talk"},
                     {-1, "BOOT: back"}};
    ui_chrome_bar(fb, m, h, 3, meta);
}

/* Recording a meeting: elapsed time, a blinking REC dot and the live level. The PC stores and transcribes it. */
void ui_screen_meeting(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "Meeting", meta);
    uint32_t el = m->listen_elapsed_s;
    if (el % 2u == 0u) {
        fb_fill_circle(fb, CONTENT_X + 8, 52, 7, INK_BLACK);
    } else {
        fb_fill_circle(fb, CONTENT_X + 8, 52, 7, INK_BLACK);
        fb_fill_circle(fb, CONTENT_X + 8, 52, 5, INK_WHITE);
    }
    const char *head = "Recording meeting";
    text_draw_bold(fb, &FONT_20B, CONTENT_X + 22, 41, head, INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 41, 22 + text_width(&FONT_20B, head) + 1, FONT_20B.line_h, -1);
    char t[12];
    const font_t *tf = &FONT_64;
    if (el >= 3600u) {
        snprintf(t, sizeof t, "%u:%02u:%02u", (unsigned)(el / 3600u), (unsigned)(el / 60u % 60u), (unsigned)(el % 60u));
        tf = &FONT_32B;
    } else {
        snprintf(t, sizeof t, "%02u:%02u", (unsigned)(el / 60u), (unsigned)(el % 60u));
    }
    int tw = text_width(tf, t), tx = CONTENT_X + (CONTENT_W - tw) / 2, ty = tf == &FONT_64 ? 62 : 82;
    text_draw(fb, tf, tx, ty, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", tx, ty + (tf == &FONT_64 ? 8 : 0), tw, tf == &FONT_64 ? FONT_64.line_h - 22 : tf->line_h, -1);
    /* compact live level: 12 thin bars */
    const int bw = 12, bgap = 7, base = 182;
    for (int i = 0; i < 12; i++) {
        int h = 6 + i * 2;
        int x = CONTENT_X + 8 + i * (bw + bgap);
        if (i < (int)m->audio_level * 12 / 8) {
            fb_fill_rect(fb, x, base - h, bw, h, INK_BLACK);
        } else {
            fb_rect(fb, x, base - h, bw, h, 1, INK_BLACK);
        }
    }
    ui_meta_add(meta, "level_meter", CONTENT_X + 8, base - 28, 12 * bw + 11 * bgap, 28, -1);
    const char *tip = m->link == LINK_TETHERED ? "Saved on your PC as it goes. The transcript is ready in the PIP app."
                                               : "PC link lost - reconnecting. Keep talking.";
    int n = text_draw_wrap(fb, &FONT_12, CONTENT_X, 194, CONTENT_W, 3, 2, tip, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 194, CONTENT_W, n * (FONT_12.line_h + 2), -1);
    ui_hint_t h[] = {{ICON_MIC, "Hold KEY: end meeting"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_error(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "", meta);
    fb_icon(fb, CONTENT_X, 46, ICON_WARN, INK_BLACK);
    const char *title = m->error_title[0] ? m->error_title : "Something went wrong";
    int n = text_draw_wrap(fb, &FONT_20B, CONTENT_X + 24, 42, CONTENT_W - 24, 2, 0, title, INK_BLACK);
    text_draw_wrap(fb, &FONT_20B, CONTENT_X + 25, 42, CONTENT_W - 24, 2, 0, title, INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 42, CONTENT_W, n * FONT_20B.line_h, -1);
    int y = 42 + n * FONT_20B.line_h + 12;
    const char *text = m->error_text[0] ? m->error_text : "Press any button to continue.";
    int k = text_draw_wrap(fb, &FONT_14, CONTENT_X, y, CONTENT_W, 5, 2, text, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, y, CONTENT_W, k * (FONT_14.line_h + 2), -1);
    ui_hint_t h[] = {{ICON_CHECK, "Press any button to dismiss"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
