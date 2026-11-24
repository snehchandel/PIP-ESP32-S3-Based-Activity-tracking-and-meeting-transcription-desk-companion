/* Screens 12-13: voice activity picker and error screen. */
#include <stdio.h>
#include <string.h>

#include "ui_layout.h"
#include "ui_render.h"

void ui_screen_voice_pick(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    static const int icons[UI_VOICE_CHOICES] = {ICON_CYCLE, ICON_MIC, ICON_PLAY, ICON_BELL};
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "", meta);
    text_draw_bold(fb, &FONT_20B, CONTENT_X, 42, "What's it about?", INK_BLACK);
    ui_meta_add(meta, "primary_text", CONTENT_X, 42, text_width(&FONT_20B, "What's it about?") + 1, FONT_20B.line_h, -1);
    const int row_h = 36, y0 = 74;
    for (int i = 0; i < UI_VOICE_CHOICES; i++) {
        int y = y0 + i * (row_h + 9);
        bool sel = i == m->voice_choice;
        if (sel) {
            fb_fill_rrect(fb, CONTENT_X, y, CONTENT_W, row_h, 12, INK_BLACK);
        } else {
            fb_rrect(fb, CONTENT_X, y, CONTENT_W, row_h, 12, 2, INK_BLACK);
        }
        ink_t ink = sel ? INK_WHITE : INK_BLACK;
        fb_icon(fb, CONTENT_X + 12, y + (row_h - UI_ICON_SIZE) / 2, (ui_icon_t)icons[i], ink);
        text_draw(fb, &FONT_16B, CONTENT_X + 40, y + (row_h - FONT_16B.line_h) / 2, ui_voice_choice_label((uint8_t)i), ink);
    }
    ui_meta_add(meta, "choice_list", CONTENT_X, y0, CONTENT_W, UI_VOICE_CHOICES * (row_h + 9) - 9, -1);
    ui_hint_t h[] = {{ICON_ARROW, "Next"}, {ICON_MIC, "Hold: talk"}, {-1, "BOOT: back"}};
    ui_chrome_bar(fb, m, h, 3, meta);
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
