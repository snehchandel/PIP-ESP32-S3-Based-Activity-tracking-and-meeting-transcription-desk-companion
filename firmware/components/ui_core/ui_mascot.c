/* Draws PIP: eyeless sprite + live procedural eyes (blink / glance / look-at-text) at the animated pose. */
#include "ui_layout.h"
#include "ui_render.h"

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

/* One eye centred at (cx, cy). sign: +1 left eye, -1 right eye (angled brows slant inward). */
static void eye(rlcd_fb_t *fb, eye_style_t st, int cx, int cy, int h, int sign, uint8_t lid)
{
    int open = 8 - (lid > 8 ? 8 : lid);
    if (open <= 2 || ((st == EYE_HAPPY || st == EYE_CLOSED) && lid >= 4)) {
        fb_fill_rrect(fb, cx - 5, cy - 1, 11, 3, 1, INK_WHITE); /* lid closed: a calm line */
        return;
    }
    switch (st) {
    case EYE_PILL: {
        int hh = h * open / 8;
        hh = hh < 4 ? 4 : hh;
        fb_fill_rrect(fb, cx - 4, cy - hh / 2, 8, hh, hh / 2 < 4 ? hh / 2 : 4, INK_WHITE);
        break;
    }
    case EYE_HAPPY: fb_arc(fb, cx, cy + 5, 8, 200, 340, 4, INK_WHITE); break;
    case EYE_CLOSED: fb_arc(fb, cx, cy - 5, 8, 25, 155, 4, INK_WHITE); break;
    case EYE_ANGLED: {
        int hh = h * open / 8;
        int bottom = cy + h / 2, top_in = bottom - hh + 4, top_out = bottom - hh - 1;
        int xo = cx - 5 * sign, xi = cx + 5 * sign;
        int x0 = xo < xi ? xo : xi;
        fb_fill_rect(fb, x0, top_in, 11, bottom - top_in + 1, INK_WHITE);
        if (top_out < top_in) {
            fb_fill_triangle(fb, xo, top_out, xi, top_in, xo, top_in, INK_WHITE); /* determined brow slant */
        }
        break;
    }
    }
}

void ui_draw_mascot(rlcd_fb_t *fb, int x, int y, pip_expr_t e, const mascot_pose_t *p)
{
    int ox = x + p->dx, oy = y + p->dy;
    fb_blit_mask(fb, ox, oy, mascot_bits(e), MASCOT_W, MASCOT_H, 15, INK_BLACK);
    eye_style_t st;
    int dx, dy, h, lx, ly, rx, ry;
    mascot_eye_spec(e, &st, &dx, &dy, &h);
    mascot_eye_anchors(&lx, &ly, &rx, &ry);
    int lookx = clampi(p->look_x, -4, 4), looky = clampi(p->look_y, -3, 3);
    eye(fb, st, ox + lx + dx + lookx, oy + ly + dy + looky, h, 1, p->lid);
    eye(fb, st, ox + rx + dx + lookx, oy + ry + dy + looky, h, -1, p->lid);
}
