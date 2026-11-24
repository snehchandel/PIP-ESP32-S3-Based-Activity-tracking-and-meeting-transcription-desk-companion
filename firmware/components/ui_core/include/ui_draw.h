/* Portable 1-bit drawing primitives (pure C99, zero ESP-IDF dependency). */
#ifndef UI_DRAW_H
#define UI_DRAW_H

#include <stdbool.h>
#include <stdint.h>

#include "font.h"
#include "icons.h"
#include "rlcd_fb.h"

typedef struct {
    int16_t x, y, w, h;
} ui_rect_t;

void fb_clear(rlcd_fb_t *fb, ink_t ink);
void fb_set(rlcd_fb_t *fb, int x, int y, ink_t ink);
int fb_get(const rlcd_fb_t *fb, int x, int y);
void fb_fill_rect(rlcd_fb_t *fb, int x, int y, int w, int h, ink_t ink);
void fb_hline(rlcd_fb_t *fb, int x, int y, int w, int thick, ink_t ink);
void fb_vline(rlcd_fb_t *fb, int x, int y, int h, int thick, ink_t ink);
void fb_rect(rlcd_fb_t *fb, int x, int y, int w, int h, int thick, ink_t ink);
void fb_fill_rrect(rlcd_fb_t *fb, int x, int y, int w, int h, int r, ink_t ink);
void fb_rrect(rlcd_fb_t *fb, int x, int y, int w, int h, int r, int thick, ink_t ink);
void fb_fill_circle(rlcd_fb_t *fb, int cx, int cy, int r, ink_t ink);
void fb_line(rlcd_fb_t *fb, int x0, int y0, int x1, int y1, int thick, ink_t ink);
/* Thick circular arc. Angles in degrees, 0 = 3 o'clock, increasing clockwise (screen y down). */
void fb_arc(rlcd_fb_t *fb, int cx, int cy, int r, int a0, int a1, int thick, ink_t ink);
void fb_fill_triangle(rlcd_fb_t *fb, int x0, int y0, int x1, int y1, int x2, int y2, ink_t ink);
void fb_invert(rlcd_fb_t *fb);

/* Clip window for every primitive (default: whole screen). */
void fb_clip(int x, int y, int w, int h);
void fb_clip_reset(void);

/* 1-bit tones for shading: 0 solid, 1 = 50 % checker, 2 = 25 %, 3 = 12 %, 4 = diagonal hatch */
int fb_pat(int pat, int x, int y);
void fb_fill_ellipse(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, ink_t ink);
void fb_fill_ellipse_pat(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, int pat);
void fb_ellipse(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, int thick, ink_t ink);
void fb_fill_triangle_pat(rlcd_fb_t *fb, int x0, int y0, int x1, int y1, int x2, int y2, int pat);
void fb_fill_quad(rlcd_fb_t *fb, const int *xs, const int *ys, ink_t ink);
void fb_fill_quad_pat(rlcd_fb_t *fb, const int *xs, const int *ys, int pat);
/* Float-coordinate conveniences used by the mascot renderer. */
void fb_line_f(rlcd_fb_t *fb, float x0, float y0, float x1, float y1, float thick, ink_t ink);
void fb_disc_f(rlcd_fb_t *fb, float cx, float cy, float r, ink_t ink);
/* Outlined rounded box: black border of `thick` px, interior `fill` (INK_WHITE / INK_BLACK). */
void fb_box_f(rlcd_fb_t *fb, float x0, float y0, float x1, float y1, float r, float thick, ink_t fill);

/* Mask blit: every set bit draws `ink`; clear bits leave the canvas untouched. */
void fb_blit_mask(rlcd_fb_t *fb, int x, int y, const uint8_t *bits, int w, int h, int stride, ink_t ink);
/* Opaque blit: set bit = black, clear bit = white. */
void fb_blit_opaque(rlcd_fb_t *fb, int x, int y, const uint8_t *bits, int w, int h, int stride);
void fb_icon(rlcd_fb_t *fb, int x, int y, ui_icon_t icon, ink_t ink);

/* Text: (x, y) is the top-left of the line box. Returns advance width in px. */
int text_width(const font_t *f, const char *s);
int text_draw(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ink_t ink);
/* Draw `s` limited to max_w pixels; truncates at a word boundary and appends "..." if
 * needed. Returns 1 if truncated. */
int text_draw_fit(rlcd_fb_t *fb, const font_t *f, int x, int y, int max_w, const char *s, ink_t ink);
/* Word-wrap into at most max_lines lines of width max_w; last line gets "..." if cut.
 * Returns number of lines drawn. */
int text_draw_wrap(rlcd_fb_t *fb, const font_t *f, int x, int y, int max_w, int max_lines,
                   int line_gap, const char *s, ink_t ink);
/* Bold header weight: draws text twice offset 1px horizontally. */
int text_draw_bold(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ink_t ink);

#endif
