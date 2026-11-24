#include "ui_draw.h"

#include <string.h>

static int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

void fb_clear(rlcd_fb_t *fb, ink_t ink) { memset(fb->px, ink == INK_BLACK ? 0xFF : 0x00, RLCD_FB_BYTES); }

void fb_set(rlcd_fb_t *fb, int x, int y, ink_t ink)
{
    if (x < 0 || y < 0 || x >= RLCD_W || y >= RLCD_H) {
        return;
    }
    uint8_t *b = &fb->px[y * RLCD_STRIDE + (x >> 3)];
    uint8_t m = (uint8_t)(0x80u >> (x & 7));
    if (ink == INK_BLACK) {
        *b = (uint8_t)(*b | m);
    } else {
        *b = (uint8_t)(*b & (uint8_t)~m);
    }
}

int fb_get(const rlcd_fb_t *fb, int x, int y)
{
    if (x < 0 || y < 0 || x >= RLCD_W || y >= RLCD_H) {
        return 0;
    }
    return (fb->px[y * RLCD_STRIDE + (x >> 3)] >> (7 - (x & 7))) & 1;
}

void fb_fill_rect(rlcd_fb_t *fb, int x, int y, int w, int h, ink_t ink)
{
    int x0 = clampi(x, 0, RLCD_W), x1 = clampi(x + w, 0, RLCD_W);
    int y0 = clampi(y, 0, RLCD_H), y1 = clampi(y + h, 0, RLCD_H);
    for (int yy = y0; yy < y1; yy++) {
        for (int xx = x0; xx < x1; xx++) {
            fb_set(fb, xx, yy, ink);
        }
    }
}

void fb_hline(rlcd_fb_t *fb, int x, int y, int w, int thick, ink_t ink) { fb_fill_rect(fb, x, y, w, thick, ink); }
void fb_vline(rlcd_fb_t *fb, int x, int y, int h, int thick, ink_t ink) { fb_fill_rect(fb, x, y, thick, h, ink); }

void fb_rect(rlcd_fb_t *fb, int x, int y, int w, int h, int t, ink_t ink)
{
    fb_fill_rect(fb, x, y, w, t, ink);
    fb_fill_rect(fb, x, y + h - t, w, t, ink);
    fb_fill_rect(fb, x, y, t, h, ink);
    fb_fill_rect(fb, x + w - t, y, t, h, ink);
}

/* inside test for a rounded rectangle, using integer squared distance to corner centres */
static int in_rrect(int px, int py, int x, int y, int w, int h, int r)
{
    if (px < x || py < y || px >= x + w || py >= y + h) {
        return 0;
    }
    int cx = px < x + r ? x + r : (px >= x + w - r ? x + w - r - 1 : px);
    int cy = py < y + r ? y + r : (py >= y + h - r ? y + h - r - 1 : py);
    int dx = px - cx, dy = py - cy;
    return dx * dx + dy * dy <= r * r;
}

void fb_fill_rrect(rlcd_fb_t *fb, int x, int y, int w, int h, int r, ink_t ink)
{
    for (int yy = y; yy < y + h; yy++) {
        for (int xx = x; xx < x + w; xx++) {
            if (in_rrect(xx, yy, x, y, w, h, r)) {
                fb_set(fb, xx, yy, ink);
            }
        }
    }
}

void fb_rrect(rlcd_fb_t *fb, int x, int y, int w, int h, int r, int t, ink_t ink)
{
    int ri = r - t < 0 ? 0 : r - t;
    for (int yy = y; yy < y + h; yy++) {
        for (int xx = x; xx < x + w; xx++) {
            if (in_rrect(xx, yy, x, y, w, h, r) && !in_rrect(xx, yy, x + t, y + t, w - 2 * t, h - 2 * t, ri)) {
                fb_set(fb, xx, yy, ink);
            }
        }
    }
}

void fb_fill_circle(rlcd_fb_t *fb, int cx, int cy, int r, ink_t ink)
{
    for (int dy = -r; dy <= r; dy++) {
        for (int dx = -r; dx <= r; dx++) {
            if (dx * dx + dy * dy <= r * r) {
                fb_set(fb, cx + dx, cy + dy, ink);
            }
        }
    }
}

void fb_line(rlcd_fb_t *fb, int x0, int y0, int x1, int y1, int thick, ink_t ink)
{
    int dx = x1 > x0 ? x1 - x0 : x0 - x1, sx = x0 < x1 ? 1 : -1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0, sy = y0 < y1 ? 1 : -1;
    int err = dx + dy;
    int r = thick / 2;
    for (;;) {
        if (thick <= 1) {
            fb_set(fb, x0, y0, ink);
        } else {
            fb_fill_circle(fb, x0, y0, r, ink);
        }
        if (x0 == x1 && y0 == y1) {
            break;
        }
        int e2 = 2 * err;
        if (e2 >= dy) {
            err += dy;
            x0 += sx;
        }
        if (e2 <= dx) {
            err += dx;
            y0 += sy;
        }
    }
}

void fb_blit_mask(rlcd_fb_t *fb, int x, int y, const uint8_t *bits, int w, int h, int stride, ink_t ink)
{
    for (int r = 0; r < h; r++) {
        const uint8_t *row = bits + r * stride;
        for (int c = 0; c < w; c++) {
            if (row[c >> 3] & (0x80u >> (c & 7))) {
                fb_set(fb, x + c, y + r, ink);
            }
        }
    }
}

void fb_blit_opaque(rlcd_fb_t *fb, int x, int y, const uint8_t *bits, int w, int h, int stride)
{
    for (int r = 0; r < h; r++) {
        const uint8_t *row = bits + r * stride;
        for (int c = 0; c < w; c++) {
            fb_set(fb, x + c, y + r, (row[c >> 3] & (0x80u >> (c & 7))) ? INK_BLACK : INK_WHITE);
        }
    }
}

void fb_icon(rlcd_fb_t *fb, int x, int y, ui_icon_t icon, ink_t ink)
{
    fb_blit_mask(fb, x, y, ui_icons[icon], UI_ICON_SIZE, UI_ICON_SIZE, UI_ICON_STRIDE, ink);
}
