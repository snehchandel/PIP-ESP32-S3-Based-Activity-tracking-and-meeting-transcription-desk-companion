/* Prop drawings for the PIP stage (1-bit, isometric where it helps the sense of space). */
#include "ui_props.h"

#include <math.h>
#include <string.h>

#include "ui_draw.h"
#include "ui_layout.h"
#include "ui_render.h"

#define PI_F 3.14159265f
#define TAU_F 6.2831853f

static int ri(float v) { return (int)lroundf(v); }

static void ring_disc(rlcd_fb_t *fb, float x, float y, float r, float t)
{
    fb_disc_f(fb, x, y, r, INK_BLACK);
    if (r - t >= 1.0f) {
        fb_disc_f(fb, x, y, r - t, INK_WHITE);
    }
}

static void ball(rlcd_fb_t *fb, float x, float y, float r, float spin)
{
    ring_disc(fb, x, y, r, 2.0f);
    float a = spin * 3.0f;
    fb_line_f(fb, x + cosf(a) * r * 0.8f, y + sinf(a) * r * 0.8f, x - cosf(a) * r * 0.8f, y - sinf(a) * r * 0.8f, 2.0f,
              INK_BLACK);
    fb_disc_f(fb, x - r * 0.35f, y - r * 0.35f, r * 0.18f + 0.5f, INK_BLACK);
}

void ui_iso_cube(rlcd_fb_t *fb, float x, float y, float a, bool ribbon)
{
    float H = a * 1.15f, h = a * 0.5f;
    int tx[4] = {ri(x), ri(x + a), ri(x), ri(x - a)}, ty[4] = {ri(y - H - h), ri(y - H), ri(y - H + h), ri(y - H)};
    int lx[4] = {ri(x - a), ri(x), ri(x), ri(x - a)}, ly[4] = {ri(y - H), ri(y - H + h), ri(y + h), ri(y)};
    int rx[4] = {ri(x), ri(x + a), ri(x + a), ri(x)}, ry[4] = {ri(y - H + h), ri(y - H), ri(y), ri(y + h)};
    fb_fill_quad(fb, lx, ly, INK_WHITE);
    fb_fill_quad(fb, rx, ry, INK_WHITE);
    fb_fill_quad(fb, tx, ty, INK_WHITE);
    fb_fill_quad_pat(fb, lx, ly, 1);
    fb_fill_quad_pat(fb, rx, ry, 3);
    const int *xs[3] = {tx, lx, rx}, *ys[3] = {ty, ly, ry};
    for (int f = 0; f < 3; f++) {
        for (int i = 0; i < 4; i++) {
            int j = (i + 1) % 4;
            fb_line(fb, xs[f][i], ys[f][i], xs[f][j], ys[f][j], 1, INK_BLACK);
        }
    }
    if (ribbon) {
        fb_line_f(fb, x - a * 0.5f, y - H - h * 0.5f, x + a * 0.5f, y - H + h * 0.5f, 2.0f, INK_BLACK);
        fb_line_f(fb, x + a * 0.5f, y - H - h * 0.5f, x - a * 0.5f, y - H + h * 0.5f, 2.0f, INK_BLACK);
        fb_line_f(fb, x - a * 0.5f, y - H + h * 0.5f, x - a * 0.5f, y + h * 0.5f, 2.0f, INK_BLACK);
        fb_line_f(fb, x + a * 0.5f, y - H + h * 0.5f, x + a * 0.5f, y + h * 0.5f, 2.0f, INK_BLACK);
    }
}

static void alarm_clock(rlcd_fb_t *fb, float x, float y, float r, float t, bool ringing)
{
    float j = ringing ? 1.6f * sinf(t * 45.0f) : 0.0f;
    x += j;
    fb_disc_f(fb, x - r * 0.75f, y - r * 0.85f, r * 0.42f, INK_BLACK);
    fb_disc_f(fb, x + r * 0.75f, y - r * 0.85f, r * 0.42f, INK_BLACK);
    fb_line_f(fb, x - r * 0.6f, y + r * 0.7f, x - r * 0.9f, y + r * 1.15f, 2.0f, INK_BLACK);
    fb_line_f(fb, x + r * 0.6f, y + r * 0.7f, x + r * 0.9f, y + r * 1.15f, 2.0f, INK_BLACK);
    ring_disc(fb, x, y, r, 2.0f);
    float a = t * 0.8f;
    fb_line_f(fb, x, y, x + cosf(a) * r * 0.65f, y + sinf(a) * r * 0.65f, 1.5f, INK_BLACK);
    fb_line_f(fb, x, y, x, y - r * 0.5f, 2.0f, INK_BLACK);
    if (ringing) {
        for (int sgn = -1; sgn <= 1; sgn += 2) {
            for (int k = 0; k < 2; k++) {
                float xx = x + (float)sgn * (r + 4.0f + (float)k * 4.0f);
                fb_line_f(fb, xx, y - r * 0.6f + j, xx + (float)sgn * 2.0f, y - r * 0.2f - j, 1.5f, INK_BLACK);
            }
        }
    }
}

void ui_prop_floor(rlcd_fb_t *fb, const mascot_pose_t *p, float x, float y)
{
    float t = p->fp_t;
    switch (p->floor_prop) {
    case PROP_BALL: ball(fb, x, y - 7.0f, 7.0f, 0.0f); break;
    case PROP_PENCIL:
        fb_line_f(fb, x - 9.0f, y + 1.0f, x + 7.0f, y - 4.0f, 3.0f, INK_BLACK);
        fb_fill_triangle(fb, ri(x + 7.0f), ri(y - 6.0f), ri(x + 7.0f), ri(y - 2.0f), ri(x + 12.0f), ri(y - 5.0f), INK_BLACK);
        break;
    case PROP_TELESCOPE: {
        float px = x, py = y - 26.0f, dir = x >= (float)ui_stage_current()->cx ? 1.0f : -1.0f;
        fb_line_f(fb, px, py, x - 9.0f, y, 2.0f, INK_BLACK);
        fb_line_f(fb, px, py, x + 9.0f, y, 2.0f, INK_BLACK);
        fb_line_f(fb, px, py, x + 2.0f, y + 4.0f, 2.0f, INK_BLACK);
        float ca = cosf(t), sa = sinf(t);
        float bx = px - dir * ca * 12.0f, by = py - sa * 12.0f, fx = px + dir * ca * 16.0f, fy = py + sa * 16.0f;
        fb_line_f(fb, bx, by, fx, fy, 8.0f, INK_BLACK);
        fb_line_f(fb, bx + dir * ca * 3.0f, by + sa * 3.0f, fx - dir * ca * 3.0f, fy - sa * 3.0f, 2.0f, INK_WHITE);
        fb_disc_f(fb, fx, fy, 5.0f, INK_BLACK);
        fb_disc_f(fb, fx, fy, 2.5f, INK_WHITE);
        break;
    }
    case PROP_PLANT: {
        int pot_x[4] = {ri(x - 9.0f), ri(x + 9.0f), ri(x + 6.0f), ri(x - 6.0f)}, pot_y[4] = {ri(y - 14.0f), ri(y - 14.0f), ri(y), ri(y)};
        fb_fill_quad(fb, pot_x, pot_y, INK_WHITE);
        fb_fill_quad_pat(fb, pot_x, pot_y, 1);
        fb_fill_rect(fb, ri(x - 10.0f), ri(y - 16.0f), 21, 3, INK_BLACK);
        int leaves = (int)t;
        float top = y - 18.0f - 5.0f * (float)leaves;
        fb_line_f(fb, x, y - 15.0f, x, top, 2.0f, INK_BLACK);
        for (int i = 0; i < leaves; i++) {
            float ly = y - 20.0f - 5.0f * (float)i, side = (i & 1) ? 1.0f : -1.0f;
            fb_fill_ellipse(fb, ri(x + side * 5.0f), ri(ly), 5, 2, INK_BLACK);
        }
        fb_fill_ellipse(fb, ri(x), ri(top - 2.0f), 3, 4, INK_BLACK);
        break;
    }
    case PROP_BLOCKS: {
        const float a = 7.0f, H = a * 1.15f;
        if (t >= 10.0f) { /* tower fell over */
            ui_iso_cube(fb, x - 12.0f, y + 2.0f, a, false);
            ui_iso_cube(fb, x + 10.0f, y + 4.0f, a, false);
            ui_iso_cube(fb, x - 2.0f, y - 6.0f, a, false);
            ui_iso_cube(fb, x + 20.0f, y - 4.0f, a, false);
            break;
        }
        int n = (int)t;
        float wob = (t - (float)n) > 0.01f ? (t - (float)n - 0.5f) * 4.0f : 0.0f;
        for (int i = 0; i < n && i < 6; i++) {
            ui_iso_cube(fb, x + wob * (float)i, y - H * (float)i, a, false);
        }
        break;
    }
    case PROP_LAPTOP: {
        int bx[4] = {ri(x - 18.0f), ri(x + 18.0f), ri(x + 14.0f), ri(x - 14.0f)}, by[4] = {ri(y), ri(y), ri(y - 7.0f), ri(y - 7.0f)};
        fb_fill_quad(fb, bx, by, INK_WHITE);
        for (int i = 0; i < 4; i++) {
            fb_line(fb, bx[i], by[i], bx[(i + 1) % 4], by[(i + 1) % 4], 2, INK_BLACK);
        }
        fb_fill_rrect(fb, ri(x - 14.0f), ri(y - 30.0f), 29, 24, 3, INK_BLACK); /* lid, seen from behind */
        float glow = fmodf(t, 2.0f) < 1.0f ? 3.0f : 2.0f;
        fb_disc_f(fb, x, y - 18.0f, glow, INK_WHITE);
        break;
    }
    case PROP_GIFT: {
        float lift = t * 14.0f;
        ui_iso_cube(fb, x, y, 14.0f, true);
        if (lift > 0.5f) { /* lid pops off */
            int lx[4] = {ri(x), ri(x + 12.0f), ri(x), ri(x - 12.0f)};
            int base = ri(y - 11.0f * 1.15f - lift);
            int ly[4] = {base - 6, base, base + 6, base};
            fb_fill_quad(fb, lx, ly, INK_WHITE);
            fb_fill_quad_pat(fb, lx, ly, 2);
            for (int i = 0; i < 4; i++) {
                fb_line(fb, lx[i], ly[i], lx[(i + 1) % 4], ly[(i + 1) % 4], 1, INK_BLACK);
            }
        }
        break;
    }
    case PROP_CLOCK: alarm_clock(fb, x, y - 12.0f, 10.0f, t, true); break;
    default: break;
    }
}

static void book(rlcd_fb_t *fb, float mx, float my, float s, float turn)
{
    float w = 16.0f * s, h = 12.0f * s;
    int lx[4] = {ri(mx - w), ri(mx), ri(mx), ri(mx - w)}, ly[4] = {ri(my - h * 0.6f), ri(my - h * 0.4f), ri(my + h * 0.6f), ri(my + h * 0.4f)};
    int rx[4] = {ri(mx), ri(mx + w), ri(mx + w), ri(mx)}, ry[4] = {ri(my - h * 0.4f), ri(my - h * 0.6f), ri(my + h * 0.4f), ri(my + h * 0.6f)};
    fb_fill_quad(fb, lx, ly, INK_WHITE);
    fb_fill_quad(fb, rx, ry, INK_WHITE);
    for (int i = 0; i < 4; i++) {
        fb_line(fb, lx[i], ly[i], lx[(i + 1) % 4], ly[(i + 1) % 4], 2, INK_BLACK);
        fb_line(fb, rx[i], ry[i], rx[(i + 1) % 4], ry[(i + 1) % 4], 2, INK_BLACK);
    }
    for (int k = 1; k <= 2; k++) {
        float yy = my - h * 0.35f + (float)k * h * 0.3f;
        fb_line_f(fb, mx - w * 0.8f, yy - 1.0f, mx - w * 0.2f, yy, 1.0f, INK_BLACK);
        fb_line_f(fb, mx + w * 0.2f, yy, mx + w * 0.8f, yy - 1.0f, 1.0f, INK_BLACK);
    }
    float f = turn - floorf(turn);
    if (f > 0.05f && f < 0.95f) { /* a page sweeping over */
        float ex = mx + w * cosf(PI_F * f);
        fb_line_f(fb, mx, my - h * 0.4f, ex, my - h * 0.5f - 4.0f * s * sinf(PI_F * f), 2.0f, INK_BLACK);
        fb_line_f(fb, mx, my + h * 0.6f, ex, my + h * 0.5f - 4.0f * s * sinf(PI_F * f), 2.0f, INK_BLACK);
        fb_line_f(fb, ex, my - h * 0.5f - 4.0f * s * sinf(PI_F * f), ex, my + h * 0.5f - 4.0f * s * sinf(PI_F * f), 2.0f,
                  INK_BLACK);
    }
}

static void calendar(rlcd_fb_t *fb, float mx, float my, float s, float page)
{
    float w = 32.0f * s, h = 28.0f * s, x0 = mx - w / 2.0f, y0 = my - h;
    fb_box_f(fb, x0, y0, x0 + w, y0 + h, 3.0f * s, 2.0f, INK_WHITE);
    fb_fill_rect(fb, ri(x0), ri(y0), ri(w), ri(7.0f * s), INK_BLACK);
    fb_disc_f(fb, x0 + w * 0.3f, y0 + 1.0f, 1.8f * s, INK_WHITE);
    fb_disc_f(fb, x0 + w * 0.7f, y0 + 1.0f, 1.8f * s, INK_WHITE);
    int today = ((int)page * 5 + 3) % 12;
    for (int r = 0; r < 3; r++) {
        for (int c = 0; c < 4; c++) {
            float cx = x0 + 4.0f * s + (float)c * 7.0f * s, cy = y0 + 10.0f * s + (float)r * 5.5f * s;
            if (r * 4 + c == today) {
                fb_fill_rect(fb, ri(cx - 1.0f), ri(cy - 1.0f), ri(5.0f * s), ri(4.5f * s), INK_BLACK);
            } else {
                fb_fill_rect(fb, ri(cx), ri(cy), 2, 2, INK_BLACK);
            }
        }
    }
}

static void held_one(rlcd_fb_t *fb, int prop, const mascot_pose_t *p, const pip_rig_t *r, float hx, float hy, float side,
                     int cx, int fy)
{
    float s = r->s, t = p->held_t;
    switch (prop) {
    case PROP_BALL: ball(fb, hx, hy - 6.0f * s, 6.0f * s, t); break;
    case PROP_MUG: {
        fb_box_f(fb, hx - 5.0f * s, hy - 12.0f * s, hx + 6.0f * s, hy + 1.0f * s, 2.0f, 2.0f, INK_WHITE);
        fb_arc(fb, ri(hx - 6.0f * s), ri(hy - 6.0f * s), ri(3.5f * s), 90, 270, 2, INK_BLACK);
        for (int k = 0; k < 2; k++) {
            float ph = fmodf(t * 0.8f + (float)k * 0.5f, 1.0f);
            float sx = hx - 1.0f * s + (float)k * 4.0f * s, sy = hy - 15.0f * s - 10.0f * ph;
            fb_line_f(fb, sx, sy, sx + 2.0f * sinf(ph * 9.0f), sy - 5.0f, 1.5f, INK_BLACK);
        }
        break;
    }
    case PROP_WATERCAN: {
        float tilt = t * 0.8f;
        fb_box_f(fb, hx - 4.0f * s, hy - 4.0f * s, hx + 10.0f * s, hy + 8.0f * s, 2.0f, 2.0f, INK_WHITE);
        float sx = hx + 10.0f * s, sy = hy - 1.0f * s;
        float ex = sx + side * cosf(tilt) * 11.0f * s, ey = sy - cosf(tilt + 0.8f) * 9.0f * s + sinf(tilt) * 6.0f * s;
        if (side < 0) {
            sx = hx - 4.0f * s;
            ex = sx - cosf(tilt) * 11.0f * s;
        }
        fb_line_f(fb, sx, sy, ex, ey, 2.5f, INK_BLACK);
        if (t > 0.3f) {
            float ph = fmodf((float)ui_stage_current()->fy + p->held_t * 997.0f, 1.0f);
            for (int k = 0; k < 4; k++) {
                float dy = fmodf(((float)k * 7.0f + ph * 7.0f + t * 30.0f), 28.0f);
                fb_disc_f(fb, ex + side * 2.0f, ey + 3.0f + dy, 1.2f, INK_BLACK);
            }
        }
        break;
    }
    case PROP_DUMBBELL:
        fb_line_f(fb, hx - 8.0f * s, hy, hx + 8.0f * s, hy, 3.0f, INK_BLACK);
        fb_fill_rrect(fb, ri(hx - 11.0f * s), ri(hy - 5.0f * s), ri(5.0f * s), ri(10.0f * s), 1, INK_BLACK);
        fb_fill_rrect(fb, ri(hx + 6.0f * s), ri(hy - 5.0f * s), ri(5.0f * s), ri(10.0f * s), 1, INK_BLACK);
        break;
    case PROP_YOYO: {
        float yx, yy;
        if (p->sign == 1) {
            yx = hx + 24.0f * s * cosf(t * TAU_F);
            yy = hy + 24.0f * s * sinf(t * TAU_F);
        } else if (p->sign == 2) {
            yx = hx + side * (10.0f + 8.0f * sinf(t * 2.0f)) * s;
            yy = (float)fy + p->y - 5.0f;
        } else {
            yx = hx;
            yy = hy + 8.0f + 28.0f * s * fabsf(sinf(t * PI_F));
        }
        fb_line_f(fb, hx, hy, yx, yy, 1.0f, INK_BLACK);
        fb_disc_f(fb, yx, yy, 5.0f * s, INK_BLACK);
        fb_disc_f(fb, yx + cosf(t * 12.0f) * 2.0f * s, yy + sinf(t * 12.0f) * 2.0f * s, 1.5f * s, INK_WHITE);
        break;
    }
    case PROP_PLANE: {
        float nx = hx + side * 10.0f * s, ny = hy - 8.0f * s;
        fb_fill_triangle(fb, ri(nx), ri(ny), ri(hx - side * 6.0f * s), ri(hy - 2.0f * s), ri(hx - side * 2.0f * s), ri(hy + 4.0f * s),
                         INK_BLACK);
        fb_line_f(fb, nx, ny, hx - side * 3.0f * s, hy + 1.0f * s, 1.0f, INK_WHITE);
        break;
    }
    case PROP_KITE: fb_disc_f(fb, hx, hy, 3.5f * s, INK_BLACK); break;
    case PROP_BROOM: {
        float bx = hx + side * 10.0f * s + p->held_t * 4.0f, by = (float)fy + p->y + 2.0f;
        fb_line_f(fb, hx, hy - 10.0f * s, bx, by - 8.0f, 2.5f, INK_BLACK);
        int tx = ri(bx), ty = ri(by - 9.0f);
        fb_fill_triangle_pat(fb, tx - 2, ty, tx + 2, ty, tx + ri(side * 10.0f), ri(by), 0);
        fb_fill_triangle_pat(fb, tx - 2, ty, tx - ri(side * 6.0f), ri(by), tx + ri(side * 10.0f), ri(by), 1);
        break;
    }
    case PROP_CLOCK: alarm_clock(fb, hx, hy - 8.0f * s, 7.0f * s, t, p->emote == EMOTE_EXCLAIM); break;
    case PROP_SIGN: {
        float top = hy - 28.0f * s;
        fb_line_f(fb, hx, hy + 2.0f, hx, top, 2.5f, INK_BLACK);
        const char *txt = mascot_sign_text(p->sign);
        const font_t *f = text_width(&FONT_12B, txt) <= 52 ? &FONT_12B : &FONT_11;
        int tw = text_width(f, txt);
        float w = (float)(tw > 44 ? tw : 44) + 10.0f, h = 22.0f;
        float x0 = hx - w / 2.0f, y0 = top - h + 4.0f;
        fb_box_f(fb, x0, y0, x0 + w, y0 + h, 4.0f, 2.0f, INK_WHITE);
        text_draw(fb, f, ri(hx) - tw / 2, ri(y0 + (h - (float)f->line_h) / 2.0f), txt, INK_BLACK);
        break;
    }
    case PROP_UMBRELLA: {
        float ux = hx, uy = hy - 34.0f * s, R = 26.0f * s;
        float tw = fmodf(t * 2.0f, TAU_F);
        for (int k = 0; k < 6; k++) { /* canopy fan */
            float a0 = PI_F + (float)k * PI_F / 6.0f, a1 = a0 + PI_F / 6.0f;
            int pat = ((k + (int)(tw * 2.0f)) & 1) ? 0 : 1;
            fb_fill_triangle(fb, ri(ux), ri(uy), ri(ux + cosf(a0) * R), ri(uy + sinf(a0) * R * 0.75f), ri(ux + cosf(a1) * R),
                             ri(uy + sinf(a1) * R * 0.75f), INK_WHITE);
            fb_fill_triangle_pat(fb, ri(ux), ri(uy), ri(ux + cosf(a0) * R), ri(uy + sinf(a0) * R * 0.75f), ri(ux + cosf(a1) * R),
                                 ri(uy + sinf(a1) * R * 0.75f), pat);
            fb_line_f(fb, ux + cosf(a0) * R, uy + sinf(a0) * R * 0.75f, ux + cosf(a1) * R, uy + sinf(a1) * R * 0.75f, 2.0f,
                      INK_BLACK);
        }
        fb_line_f(fb, ux - R, uy, ux + R, uy, 2.0f, INK_BLACK);
        fb_line_f(fb, ux, uy, hx, hy + 6.0f * s, 2.0f, INK_BLACK);
        fb_line_f(fb, ux, uy - R * 0.75f, ux, uy - R * 0.75f - 4.0f, 2.0f, INK_BLACK);
        /* rain everywhere except under the canopy */
        for (int i = 0; i < 18; i++) {
            const ui_stage_t *st = ui_stage_current();
            float rx0 = ux - 72.0f + fmodf((float)i * 37.0f, 144.0f); /* a shower that follows PIP */
            float ry0 = (float)ZONE_TOP + fmodf((float)i * 53.0f + t * 90.0f, (float)(st->fy - ZONE_TOP));
            if (rx0 > ux - R && rx0 < ux + R && ry0 > uy - R) {
                continue;
            }
            fb_line_f(fb, rx0, ry0, rx0 - 2.0f, ry0 + 6.0f, 1.0f, INK_BLACK);
        }
        break;
    }
    case PROP_PENCIL:
        fb_line_f(fb, hx - 2.0f, hy + 4.0f, hx + side * 8.0f, hy - 8.0f, 2.5f, INK_BLACK);
        break;
    case PROP_WRENCH: {
        float a = -0.8f + 0.5f * sinf(t * 6.0f);
        float ex = hx + side * cosf(a) * 14.0f * s, ey = hy + sinf(a) * 14.0f * s;
        fb_line_f(fb, hx, hy, ex, ey, 3.0f, INK_BLACK);
        fb_disc_f(fb, ex, ey, 4.5f * s, INK_BLACK);
        fb_disc_f(fb, ex + side * 2.0f, ey - 1.0f, 2.0f * s, INK_WHITE);
        break;
    }
    default: break;
    }
}

void ui_prop_held(rlcd_fb_t *fb, const mascot_pose_t *p, const pip_rig_t *r, int cx, int fy, bool two_handed_pass)
{
    float s = r->s;
    float lx = (float)cx + r->hand[0].x, ly = (float)fy + r->hand[0].y;
    float rx = (float)cx + r->hand[1].x, ry = (float)fy + r->hand[1].y;
    float mx = (lx + rx) / 2.0f, my = (ly + ry) / 2.0f;
    bool juggle = p->held == PROP_BALL && p->held_l == PROP_BALL;
    if (two_handed_pass) {
        switch (p->held) {
        case PROP_BOOK: book(fb, mx, my - 2.0f * s, s, p->held_t); break;
        case PROP_CALENDAR: calendar(fb, mx, my + 2.0f * s, s, p->held_t); break;
        case PROP_GUITAR: {
            float gx = mx + 4.0f * s, gy = my + 4.0f * s;
            fb_line_f(fb, gx, gy, lx - 8.0f * s, ly - 6.0f * s, 3.0f, INK_BLACK);
            ring_disc(fb, gx + 4.0f * s, gy + 3.0f * s, 9.0f * s, 2.0f);
            ring_disc(fb, gx - 3.0f * s, gy - 2.0f * s, 6.5f * s, 2.0f);
            fb_disc_f(fb, gx, gy, 2.5f * s, INK_BLACK);
            break;
        }
        default: break;
        }
        return;
    }
    if (juggle) { /* three-ball cascade between the hands */
        for (int i = 0; i < 3; i++) {
            float ph = fmodf(p->held_t + (float)i / 3.0f, 1.0f);
            float bx = mx + 30.0f * s * cosf(ph * TAU_F), by = my - 6.0f * s - 78.0f * s * fabsf(sinf(ph * PI_F));
            ball(fb, bx, by, 5.0f * s, p->held_t + (float)i);
        }
        return;
    }
    if (p->held != PROP_BOOK && p->held != PROP_CALENDAR && p->held != PROP_GUITAR) {
        held_one(fb, p->held, p, r, rx, ry, 1.0f, cx, fy);
    }
    if (p->held_l != PROP_HEADPHONES) {
        held_one(fb, p->held_l, p, r, lx, ly, -1.0f, cx, fy);
    }
}

void ui_prop_flying(rlcd_fb_t *fb, const mascot_pose_t *p, const pip_rig_t *r, int cx, int fy)
{
    float x = (float)cx + p->obj_x, y = (float)fy + p->obj_y, t = p->obj_t, s = r->s;
    float rx = (float)cx + r->hand[1].x, ry = (float)fy + r->hand[1].y;
    switch (p->obj) {
    case PROP_BALL: ball(fb, x, y, 7.0f, t); break;
    case PROP_PLANE: {
        float dirx = cosf(fabsf(t)) * (t < 0.0f ? -1.0f : 1.0f), diry = -sinf(fabsf(t)) * 0.8f;
        float n = sqrtf(dirx * dirx + diry * diry);
        dirx /= n;
        diry /= n;
        float px = -diry, py = dirx;
        fb_fill_triangle(fb, ri(x + dirx * 10.0f), ri(y + diry * 10.0f), ri(x - dirx * 7.0f + px * 6.0f), ri(y - diry * 7.0f + py * 6.0f),
                         ri(x - dirx * 7.0f - px * 6.0f), ri(y - diry * 7.0f - py * 6.0f), INK_BLACK);
        fb_line_f(fb, x + dirx * 9.0f, y + diry * 9.0f, x - dirx * 6.0f, y - diry * 6.0f, 1.0f, INK_WHITE);
        break;
    }
    case PROP_BALLOON: {
        float bx = rx + 6.0f * s + 3.0f * sinf(t * 1.3f), by = ry - 46.0f * s + 2.0f * sinf(t * 2.0f);
        for (int k = 0; k < 6; k++) { /* wavy string */
            float u0 = (float)k / 6.0f, u1 = (float)(k + 1) / 6.0f;
            fb_line_f(fb, rx + (bx - rx) * u0 + 2.0f * sinf(u0 * 9.0f + t * 3.0f), ry + (by + 12.0f * s - ry) * u0,
                      rx + (bx - rx) * u1 + 2.0f * sinf(u1 * 9.0f + t * 3.0f), ry + (by + 12.0f * s - ry) * u1, 1.0f, INK_BLACK);
        }
        fb_fill_ellipse(fb, ri(bx), ri(by), ri(11.0f * s), ri(13.0f * s), INK_BLACK);
        fb_fill_ellipse(fb, ri(bx), ri(by), ri(9.0f * s), ri(11.0f * s), INK_WHITE);
        fb_fill_ellipse_pat(fb, ri(bx), ri(by), ri(9.0f * s), ri(11.0f * s), 2);
        fb_fill_ellipse(fb, ri(bx - 3.0f * s), ri(by - 4.0f * s), ri(2.0f * s), ri(3.0f * s), INK_WHITE);
        fb_fill_triangle(fb, ri(bx), ri(by + 12.0f * s), ri(bx - 3.0f), ri(by + 16.0f * s), ri(bx + 3.0f), ri(by + 16.0f * s),
                         INK_BLACK);
        break;
    }
    case PROP_KITE: {
        /* string with a gentle sag */
        float mx = (rx + x) / 2.0f, my = (ry + y) / 2.0f + 10.0f;
        fb_line_f(fb, rx, ry, mx, my, 1.0f, INK_BLACK);
        fb_line_f(fb, mx, my, x, y + 14.0f, 1.0f, INK_BLACK);
        int kx[4] = {ri(x), ri(x + 10.0f), ri(x), ri(x - 10.0f)}, ky[4] = {ri(y - 13.0f), ri(y), ri(y + 14.0f), ri(y)};
        fb_fill_quad(fb, kx, ky, INK_WHITE);
        int hx[4] = {kx[0], kx[1], ri(x), kx[3]}, hy[4] = {ky[0], ky[1], ri(y), ky[3]};
        fb_fill_quad_pat(fb, hx, hy, 1);
        for (int i = 0; i < 4; i++) {
            fb_line(fb, kx[i], ky[i], kx[(i + 1) % 4], ky[(i + 1) % 4], 2, INK_BLACK);
        }
        fb_line(fb, kx[0], ky[0], kx[2], ky[2], 1, INK_BLACK);
        fb_line(fb, kx[1], ky[1], kx[3], ky[3], 1, INK_BLACK);
        for (int k = 1; k <= 3; k++) { /* tail bows */
            float tx = x + 6.0f * sinf(t * 3.0f + (float)k), ty = y + 14.0f + (float)k * 8.0f;
            fb_fill_triangle(fb, ri(tx - 4.0f), ri(ty - 2.0f), ri(tx), ri(ty), ri(tx - 4.0f), ri(ty + 2.0f), INK_BLACK);
            fb_fill_triangle(fb, ri(tx + 4.0f), ri(ty - 2.0f), ri(tx), ri(ty), ri(tx + 4.0f), ri(ty + 2.0f), INK_BLACK);
        }
        break;
    }
    default: break;
    }
}
