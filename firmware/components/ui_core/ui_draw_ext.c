/* Extra 1-bit primitives: ellipses, dithered tones for isometric shading, quads, float helpers. */
#include <math.h>

#include "ui_draw.h"

int fb_pat(int pat, int x, int y)
{
    switch (pat) {
    case 0: return 1;
    case 1: return ((x ^ y) & 1) == 0;
    case 2: return (x & 1) == 0 && (y & 1) == 0;
    case 3: return (x & 3) == 0 && (y & 1) == 0 && (((x >> 2) ^ (y >> 1)) & 1) == 0;
    case 4: return ((x + y) & 3) == 0;
    default: return 0;
    }
}

static void span(rlcd_fb_t *fb, int x0, int x1, int y, int pat, ink_t ink)
{
    for (int x = x0; x <= x1; x++) {
        if (pat < 0) {
            fb_set(fb, x, y, ink);
        } else if (fb_pat(pat, x, y)) {
            fb_set(fb, x, y, INK_BLACK);
        }
    }
}

static void ellipse_fill(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, int pat, ink_t ink)
{
    if (rx <= 0 || ry <= 0) {
        return;
    }
    for (int dy = -ry; dy <= ry; dy++) {
        float f = 1.0f - (float)(dy * dy) / (float)(ry * ry);
        int hw = (int)lroundf((float)rx * sqrtf(f > 0.0f ? f : 0.0f));
        span(fb, cx - hw, cx + hw, cy + dy, pat, ink);
    }
}

void fb_fill_ellipse(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, ink_t ink)
{
    ellipse_fill(fb, cx, cy, rx, ry, -1, ink);
}

void fb_fill_ellipse_pat(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, int pat)
{
    ellipse_fill(fb, cx, cy, rx, ry, pat, INK_BLACK);
}

void fb_ellipse(rlcd_fb_t *fb, int cx, int cy, int rx, int ry, int thick, ink_t ink)
{
    if (rx <= 0 || ry <= 0) {
        return;
    }
    int irx = rx - thick, iry = ry - thick;
    for (int dy = -ry; dy <= ry; dy++) {
        for (int dx = -rx; dx <= rx; dx++) {
            float o = (float)(dx * dx) / (float)(rx * rx) + (float)(dy * dy) / (float)(ry * ry);
            float i = (irx > 0 && iry > 0) ? (float)(dx * dx) / (float)(irx * irx) + (float)(dy * dy) / (float)(iry * iry)
                                           : 2.0f;
            if (o <= 1.0f && i > 1.0f) {
                fb_set(fb, cx + dx, cy + dy, ink);
            }
        }
    }
}

static int edge(int ax, int ay, int bx, int by, int px, int py) { return (bx - ax) * (py - ay) - (by - ay) * (px - ax); }

void fb_fill_triangle_pat(rlcd_fb_t *fb, int x0, int y0, int x1, int y1, int x2, int y2, int pat)
{
    int minx = x0 < x1 ? (x0 < x2 ? x0 : x2) : (x1 < x2 ? x1 : x2);
    int maxx = x0 > x1 ? (x0 > x2 ? x0 : x2) : (x1 > x2 ? x1 : x2);
    int miny = y0 < y1 ? (y0 < y2 ? y0 : y2) : (y1 < y2 ? y1 : y2);
    int maxy = y0 > y1 ? (y0 > y2 ? y0 : y2) : (y1 > y2 ? y1 : y2);
    int area = edge(x0, y0, x1, y1, x2, y2);
    if (area == 0) {
        return;
    }
    for (int y = miny; y <= maxy; y++) {
        for (int x = minx; x <= maxx; x++) {
            int w0 = edge(x1, y1, x2, y2, x, y), w1 = edge(x2, y2, x0, y0, x, y), w2 = edge(x0, y0, x1, y1, x, y);
            bool in = (area > 0 && w0 >= 0 && w1 >= 0 && w2 >= 0) || (area < 0 && w0 <= 0 && w1 <= 0 && w2 <= 0);
            if (in && fb_pat(pat, x, y)) {
                fb_set(fb, x, y, INK_BLACK);
            }
        }
    }
}

void fb_fill_quad(rlcd_fb_t *fb, const int *xs, const int *ys, ink_t ink)
{
    fb_fill_triangle(fb, xs[0], ys[0], xs[1], ys[1], xs[2], ys[2], ink);
    fb_fill_triangle(fb, xs[0], ys[0], xs[2], ys[2], xs[3], ys[3], ink);
}

void fb_fill_quad_pat(rlcd_fb_t *fb, const int *xs, const int *ys, int pat)
{
    fb_fill_triangle_pat(fb, xs[0], ys[0], xs[1], ys[1], xs[2], ys[2], pat);
    fb_fill_triangle_pat(fb, xs[0], ys[0], xs[2], ys[2], xs[3], ys[3], pat);
}

static int ri(float v) { return (int)lroundf(v); }

void fb_line_f(rlcd_fb_t *fb, float x0, float y0, float x1, float y1, float thick, ink_t ink)
{
    int t = ri(thick);
    fb_line(fb, ri(x0), ri(y0), ri(x1), ri(y1), t < 1 ? 1 : t, ink);
}

void fb_disc_f(rlcd_fb_t *fb, float cx, float cy, float r, ink_t ink)
{
    int rr = ri(r);
    fb_fill_circle(fb, ri(cx), ri(cy), rr < 1 ? 1 : rr, ink);
}

void fb_box_f(rlcd_fb_t *fb, float x0, float y0, float x1, float y1, float r, float thick, ink_t fill)
{
    int ax = ri(x0), ay = ri(y0), w = ri(x1) - ax, h = ri(y1) - ay, rr = ri(r), t = ri(thick);
    if (w < 2 || h < 2) {
        return;
    }
    fb_fill_rrect(fb, ax, ay, w, h, rr, INK_BLACK);
    if (fill == INK_WHITE && w > 2 * t && h > 2 * t) {
        fb_fill_rrect(fb, ax + t, ay + t, w - 2 * t, h - 2 * t, rr > t ? rr - t : 0, INK_WHITE);
    }
}
