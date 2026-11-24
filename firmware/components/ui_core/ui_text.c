#include <string.h>

#include "ui_draw.h"

int font_next_code(const char **s)
{
    const unsigned char *p = (const unsigned char *)*s;
    if (!*p) {
        return 0;
    }
    unsigned cp;
    int n;
    if (p[0] < 0x80) {
        cp = p[0];
        n = 1;
    } else if ((p[0] & 0xE0) == 0xC0 && p[1]) {
        cp = ((p[0] & 0x1Fu) << 6) | (p[1] & 0x3Fu);
        n = 2;
    } else if ((p[0] & 0xF0) == 0xE0 && p[1] && p[2]) {
        cp = ((p[0] & 0x0Fu) << 12) | ((p[1] & 0x3Fu) << 6) | (p[2] & 0x3Fu);
        n = 3;
    } else {
        cp = '?';
        n = 1;
        while (p[n] && (p[n] & 0xC0) == 0x80) {
            n++;
        }
    }
    *s += n;
    switch (cp) {
    case 0x00B7: return 127;
    case 0x2014: return 128;
    case 0x2026: return 129;
    case 0x00B0: return 130; /* degree sign */
    case 0x2013: return '-';
    case 0x2019: return '\'';
    default: return cp < 127 ? (int)cp : '?';
    }
}

static const font_glyph_t *glyph(const font_t *f, int code)
{
    if (code < f->first || code >= f->first + f->count) {
        code = '?';
        if (code < f->first || code >= f->first + f->count) {
            return NULL;
        }
    }
    return &f->glyphs[code - f->first];
}

static int draw_glyph(rlcd_fb_t *fb, const font_t *f, int x, int y, int code, ink_t ink)
{
    const font_glyph_t *g = glyph(f, code);
    if (!g) {
        return 0;
    }
    if (fb && g->w && g->h) {
        fb_blit_mask(fb, x + g->x_off, y + g->y_off, f->bits + g->offset, g->w, g->h, (g->w + 7) / 8, ink);
    }
    return g->adv;
}

static int width_n(const font_t *f, const char *s, size_t nbytes)
{
    const char *end = s + nbytes;
    int w = 0;
    while (s < end && *s) {
        w += draw_glyph(NULL, f, 0, 0, font_next_code(&s), INK_BLACK);
    }
    return w;
}

int text_width(const font_t *f, const char *s) { return width_n(f, s, strlen(s)); }

static int draw_n(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, size_t nbytes, ink_t ink)
{
    const char *end = s + nbytes;
    int x0 = x;
    while (s < end && *s) {
        x += draw_glyph(fb, f, x, y, font_next_code(&s), ink);
    }
    return x - x0;
}

int text_draw(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ink_t ink)
{
    return draw_n(fb, f, x, y, s, strlen(s), ink);
}

int text_draw_bold(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ink_t ink)
{
    draw_n(fb, f, x + 1, y, s, strlen(s), ink);
    return draw_n(fb, f, x, y, s, strlen(s), ink) + 1;
}

/* Longest prefix (in bytes) of s that fits max_w, preferring a word boundary. */
static size_t fit_prefix(const font_t *f, const char *s, size_t len, int max_w, int word_break)
{
    size_t best = 0, last_space = 0;
    const char *p = s;
    int w = 0;
    while ((size_t)(p - s) < len && *p) {
        const char *q = p;
        int code = font_next_code(&q);
        if (code == ' ') {
            last_space = (size_t)(p - s);
        }
        int gw = draw_glyph(NULL, f, 0, 0, code, INK_BLACK);
        if (w + gw > max_w) {
            if (word_break && last_space > 0) {
                return last_space;
            }
            return best;
        }
        w += gw;
        p = q;
        best = (size_t)(p - s);
    }
    return best;
}

int text_draw_fit(rlcd_fb_t *fb, const font_t *f, int x, int y, int max_w, const char *s, ink_t ink)
{
    size_t len = strlen(s);
    if (text_width(f, s) <= max_w) {
        text_draw(fb, f, x, y, s, ink);
        return 0;
    }
    int ell = text_width(f, "...");
    size_t n = fit_prefix(f, s, len, max_w - ell, 1);
    while (n > 0 && s[n - 1] == ' ') {
        n--;
    }
    int w = draw_n(fb, f, x, y, s, n, ink);
    text_draw(fb, f, x + w, y, "...", ink);
    return 1;
}

int text_draw_wrap(rlcd_fb_t *fb, const font_t *f, int x, int y, int max_w, int max_lines, int line_gap,
                   const char *s, ink_t ink)
{
    int lines = 0;
    while (*s && lines < max_lines) {
        while (*s == ' ') {
            s++;
        }
        const char *nl = strchr(s, '\n');
        size_t seg = nl ? (size_t)(nl - s) : strlen(s);
        int ly = y + lines * (f->line_h + line_gap);
        if (lines == max_lines - 1) {
            char tmp[160];
            size_t rest = strlen(s);
            size_t n = rest < sizeof(tmp) - 1 ? rest : sizeof(tmp) - 1;
            memcpy(tmp, s, n);
            tmp[n] = 0;
            if (nl && (size_t)(nl - s) < n) {
                tmp[nl - s] = 0;
            }
            text_draw_fit(fb, f, x, ly, max_w, tmp, ink);
            return lines + 1;
        }
        size_t n = fit_prefix(f, s, seg, max_w, 1);
        if (n == 0) {
            n = fit_prefix(f, s, seg, max_w, 0);
            if (n == 0) {
                break;
            }
        }
        draw_n(fb, f, x, ly, s, n, ink);
        lines++;
        s += n;
        if (nl && s == nl) {
            s++;
        }
    }
    return lines;
}
