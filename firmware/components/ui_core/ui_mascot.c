/* Draws the PIP rig on its stage: body parts back-to-front by depth, live eyes and mouth, held / floor /
 * flying props, animated emote symbols and the glass glare when PIP presses against the screen. Everything
 * is clipped to the stage: the left column on most screens, the whole world on the idle screen. */
#include <math.h>
#include <stdio.h>

#include "ui_layout.h"
#include "ui_props.h"
#include "ui_render.h"

#define PI_F 3.14159265f

const ui_stage_t UI_STAGE_COLUMN = {STAGE_X, ZONE_TOP + 1, STAGE_W, BAR_Y - ZONE_TOP - 1, STAGE_CX, STAGE_FY, 0};
const ui_stage_t UI_STAGE_WORLD = {WORLD_X, ZONE_TOP + 1, WORLD_W, BAR_Y - ZONE_TOP - 1, STAGE_CX, STAGE_FY, BOARD_X};

static const ui_stage_t *g_stage = &UI_STAGE_COLUMN;
static bool g_hidden; /* slides: pages render without PIP, PIP is drawn once on top */

void ui_mascot_hide(bool hidden) { g_hidden = hidden; }

const ui_stage_t *ui_stage_current(void) { return g_stage; }

static float SX(float x) { return (float)g_stage->cx + x; }
static float SY(float y) { return (float)g_stage->fy + y; }
static int ri(float v) { return (int)lroundf(v); }

/* ---- eyes & mouth (white on the black visor) ------------------------------------------------ */
static void eye(rlcd_fb_t *fb, int style, float cx, float cy, float w, float s, float lid, float lookx, float looky,
                int side)
{
    float open = 1.0f - (lid > 1.0f ? 1.0f : (lid < 0.0f ? 0.0f : lid));
    if (open < 0.2f && style != EYE_HAPPY && style != EYE_CLOSED) {
        fb_line_f(fb, cx - w * 0.6f, cy + 2.0f * s, cx + w * 0.6f, cy + 2.0f * s, 2.5f * s, INK_WHITE);
        return;
    }
    switch (style) {
    case EYE_HAPPY: fb_arc(fb, ri(cx), ri(cy + 4.0f * s), ri(7.0f * s), 200, 340, ri(3.0f * s), INK_WHITE); break;
    case EYE_CLOSED: fb_arc(fb, ri(cx), ri(cy - 3.0f * s), ri(7.0f * s), 25, 155, ri(3.0f * s), INK_WHITE); break;
    case EYE_WIDE: {
        float r = 6.5f * s;
        int ry = ri(r * open);
        fb_fill_ellipse(fb, ri(cx), ri(cy), ri(r * (w / (8.0f * s))), ry < 1 ? 1 : ry, INK_WHITE);
        fb_disc_f(fb, cx + lookx * 2.5f * s, cy + looky * 2.5f * s, 2.2f * s, INK_BLACK);
        break;
    }
    case EYE_STAR: {
        float r = 7.0f * s;
        fb_fill_triangle(fb, ri(cx - r), ri(cy), ri(cx), ri(cy - 2.0f * s), ri(cx + r), ri(cy), INK_WHITE);
        fb_fill_triangle(fb, ri(cx - r), ri(cy), ri(cx), ri(cy + 2.0f * s), ri(cx + r), ri(cy), INK_WHITE);
        fb_fill_triangle(fb, ri(cx), ri(cy - r), ri(cx - 2.0f * s), ri(cy), ri(cx), ri(cy + r), INK_WHITE);
        fb_fill_triangle(fb, ri(cx), ri(cy - r), ri(cx + 2.0f * s), ri(cy), ri(cx), ri(cy + r), INK_WHITE);
        break;
    }
    case EYE_HEART: {
        float r = 3.2f * s;
        fb_disc_f(fb, cx - r, cy - r * 0.4f, r, INK_WHITE);
        fb_disc_f(fb, cx + r, cy - r * 0.4f, r, INK_WHITE);
        fb_fill_triangle(fb, ri(cx - 2.0f * r), ri(cy), ri(cx + 2.0f * r), ri(cy), ri(cx), ri(cy + 2.4f * r), INK_WHITE);
        break;
    }
    case EYE_ANGLED: {
        float h = 13.0f * s * open;
        fb_fill_rrect(fb, ri(cx - w / 2.0f), ri(cy - h / 2.0f), ri(w), ri(h), ri(2.5f * s), INK_WHITE);
        float in = side < 0 ? 1.0f : -1.0f; /* inner corner gets the determined brow */
        fb_fill_triangle(fb, ri(cx - w / 2.0f - 1.0f), ri(cy - h / 2.0f - 1.0f), ri(cx + w / 2.0f + 1.0f),
                         ri(cy - h / 2.0f - 1.0f), ri(cx + in * w / 2.0f), ri(cy - h / 2.0f + 5.0f * s), INK_BLACK);
        break;
    }
    default: { /* EYE_PILL */
        float h = 14.0f * s * open;
        if (h < 3.0f) h = 3.0f;
        fb_fill_rrect(fb, ri(cx - w / 2.0f), ri(cy - h / 2.0f), ri(w), ri(h), ri(fminf(w, h) / 2.0f), INK_WHITE);
        break;
    }
    }
}

static void mouth(rlcd_fb_t *fb, int m, float cx, float cy, float s)
{
    switch (m) {
    case MOUTH_SMILE: fb_arc(fb, ri(cx), ri(cy - 4.0f * s), ri(5.0f * s), 30, 150, ri(2.0f * s), INK_WHITE); break;
    case MOUTH_GRIN:
        fb_fill_triangle(fb, ri(cx - 6.0f * s), ri(cy - 1.0f * s), ri(cx + 6.0f * s), ri(cy - 1.0f * s), ri(cx),
                         ri(cy + 4.0f * s), INK_WHITE);
        fb_fill_rect(fb, ri(cx - 6.0f * s), ri(cy - 2.0f * s), ri(12.0f * s) + 1, ri(2.0f * s), INK_WHITE);
        break;
    case MOUTH_O: fb_ellipse(fb, ri(cx), ri(cy), ri(3.5f * s), ri(4.0f * s), ri(1.6f * s) < 1 ? 1 : ri(1.6f * s), INK_WHITE); break;
    case MOUTH_FLAT: fb_line_f(fb, cx - 5.0f * s, cy, cx + 5.0f * s, cy, 2.0f * s, INK_WHITE); break;
    case MOUTH_WAVY:
        for (int i = 0; i < 4; i++) {
            float x0 = cx - 6.0f * s + (float)i * 3.0f * s;
            fb_line_f(fb, x0, cy + ((i & 1) ? 1.5f : -1.5f) * s, x0 + 3.0f * s, cy + ((i & 1) ? -1.5f : 1.5f) * s, 1.6f * s,
                      INK_WHITE);
        }
        break;
    default: break;
    }
}

/* ---- body parts ----------------------------------------------------------------------------- */
static void arm(rlcd_fb_t *fb, const pip_rig_t *r, int i)
{
    float s = r->s;
    float sx = SX(r->shoulder[i].x), sy = SY(r->shoulder[i].y), hx = SX(r->hand[i].x), hy = SY(r->hand[i].y);
    fb_line_f(fb, sx, sy, hx, hy, 6.0f * s, INK_BLACK);
    fb_disc_f(fb, hx, hy, 5.0f * s, INK_BLACK);
}

static void ear(rlcd_fb_t *fb, const pip_rig_t *r, int i, bool phones)
{
    float s = r->s, x = SX(r->ear[i].x), y = SY(r->ear[i].y), z = r->ear_z[i];
    float rad = (phones ? 9.0f : 7.0f) * s;
    if (z > 0.3f) { /* ear turned toward you: seen edge-on as a narrow knob, not a round "eye" */
        float k = 1.0f - z * 0.75f;
        fb_fill_ellipse(fb, ri(x), ri(y), ri(rad * (k < 0.3f ? 0.3f : k)), ri(rad), INK_BLACK);
        return;
    }
    fb_disc_f(fb, x, y, rad, INK_BLACK);
    fb_disc_f(fb, x, y, (phones ? 3.5f : 2.5f) * s, INK_WHITE);
}

static void legs(rlcd_fb_t *fb, const pip_rig_t *r)
{
    float s = r->s;
    for (int i = 0; i < 2; i++) {
        float fx = SX(r->foot[i].x), fy = SY(r->foot[i].y);
        if (r->sitting) { /* legs stick out toward you, feet in front of the body */
            float side = i == 0 ? -1.0f : 1.0f;
            float sx = SX(r->bx) + side * 11.0f * s, sy = SY(r->b_bot) + 1.0f * s;
            fb_fill_rect(fb, ri(sx - 4.0f * s), ri(sy - 6.0f * s), ri(8.0f * s), ri(7.0f * s), INK_BLACK);
            fb_fill_ellipse(fb, ri(sx), ri(sy + 2.0f * s), ri(7.0f * s), ri(5.0f * s), INK_BLACK);
            fb_fill_ellipse(fb, ri(sx), ri(sy + 1.0f * s), ri(3.0f * s), ri(2.0f * s), INK_WHITE);
            continue;
        }
        float top = SY(r->b_bot) - 2.0f;
        fb_fill_rect(fb, ri(fx - r->leg_w / 2.0f), ri(top), ri(r->leg_w), ri(fy - top), INK_BLACK);
        fb_fill_ellipse(fb, ri(fx), ri(fy), ri(7.5f * s), ri(4.0f * s), INK_BLACK);
    }
}

static void body(rlcd_fb_t *fb, const pip_rig_t *r)
{
    float s = r->s;
    fb_box_f(fb, SX(r->bx - r->bw / 2.0f), SY(r->b_top), SX(r->bx + r->bw / 2.0f), SY(r->b_bot), 10.0f * s, 3.0f * s,
             INK_WHITE);
    if (r->chest_vis) { /* little power light */
        fb_disc_f(fb, SX(r->chest.x), SY(r->chest.y), 5.0f * s, INK_BLACK);
        fb_disc_f(fb, SX(r->chest.x) - 1.5f * s, SY(r->chest.y) - 1.5f * s, 1.6f * s, INK_WHITE);
    }
    if (r->back_vis) { /* battery hatch with vents */
        float bx = SX(r->back.x), by = SY(r->back.y);
        fb_rrect(fb, ri(bx - 9.0f * s), ri(by - 8.0f * s), ri(18.0f * s), ri(16.0f * s), ri(3.0f * s), ri(2.0f * s) < 1 ? 1 : ri(2.0f * s),
                 INK_BLACK);
        for (int k = -1; k <= 1; k++) {
            fb_line_f(fb, bx - 5.0f * s, by + (float)k * 4.0f * s, bx + 5.0f * s, by + (float)k * 4.0f * s, 1.5f * s, INK_BLACK);
        }
    }
    /* neck */
    fb_fill_rect(fb, ri(SX(r->hx - 7.0f * s)), ri(SY(r->b_top) - 3.0f * s), ri(14.0f * s), ri(4.0f * s) + 1, INK_BLACK);
}

static void head(rlcd_fb_t *fb, const pip_rig_t *r, const mascot_pose_t *p)
{
    float s = r->s;
    /* antenna first so the head covers its base */
    fb_line_f(fb, SX(r->ant_base.x), SY(r->ant_base.y), SX(r->ant_tip.x), SY(r->ant_tip.y), 3.0f * s, INK_BLACK);
    fb_disc_f(fb, SX(r->ant_tip.x), SY(r->ant_tip.y), 5.0f * s, INK_BLACK);
    fb_disc_f(fb, SX(r->ant_tip.x) - 1.5f * s, SY(r->ant_tip.y) - 1.5f * s, 1.7f * s, INK_WHITE);
    fb_box_f(fb, SX(r->hx - r->hw / 2.0f), SY(r->h_top), SX(r->hx + r->hw / 2.0f), SY(r->h_bot), 16.0f * s, 3.0f * s,
             INK_WHITE);
    if (r->visor) {
        fb_fill_rrect(fb, ri(SX(r->v_l)), ri(SY(r->v_top)), ri(r->v_r - r->v_l), ri(r->v_bot - r->v_top), ri(9.0f * s),
                      INK_BLACK);
        for (int i = 0; i < 2; i++) {
            if (r->eye_vis[i]) {
                eye(fb, p->eyes, SX(r->eye[i].x), SY(r->eye[i].y), r->eye_w[i], s, p->lid, p->look_x, p->look_y,
                    i == 0 ? -1 : 1);
            }
        }
        float mx = SX(r->hx + r->face_dx * 0.9f + p->look_x * 1.5f * s), my = SY(r->v_bot - 6.0f * s);
        if (mx > SX(r->v_l) + 6.0f * s && mx < SX(r->v_r) - 6.0f * s) {
            mouth(fb, p->mouth, mx, my, s);
        }
    } else { /* back of the head: a little panel */
        float bx = SX(r->hx - r->face_dx), by = SY((r->h_top + r->h_bot) / 2.0f);
        fb_rrect(fb, ri(bx - 11.0f * s), ri(by - 8.0f * s), ri(22.0f * s), ri(16.0f * s), ri(4.0f * s), ri(2.0f * s) < 1 ? 1 : ri(2.0f * s),
                 INK_BLACK);
        fb_disc_f(fb, bx, by, 2.5f * s, INK_BLACK);
    }
}

static void headphones_band(rlcd_fb_t *fb, const pip_rig_t *r)
{
    float s = r->s;
    float cx = SX(r->hx), top = SY(r->h_top);
    fb_arc(fb, ri(cx), ri(top + 22.0f * s), ri(r->hw / 2.0f + 2.0f * s), 200, 340, ri(3.0f * s), INK_BLACK);
}

/* ---- emotes: animated symbols near the head ------------------------------------------------- */
static void heart(rlcd_fb_t *fb, float x, float y, float r)
{
    fb_disc_f(fb, x - r * 0.55f, y, r * 0.6f, INK_BLACK);
    fb_disc_f(fb, x + r * 0.55f, y, r * 0.6f, INK_BLACK);
    fb_fill_triangle(fb, ri(x - r * 1.1f), ri(y + r * 0.2f), ri(x + r * 1.1f), ri(y + r * 0.2f), ri(x), ri(y + r * 1.4f),
                     INK_BLACK);
}

static void star4(rlcd_fb_t *fb, float x, float y, float r)
{
    if (r < 1.0f) return;
    float w = r * 0.28f + 0.6f;
    fb_fill_triangle(fb, ri(x - r), ri(y), ri(x), ri(y - w), ri(x + r), ri(y), INK_BLACK);
    fb_fill_triangle(fb, ri(x - r), ri(y), ri(x), ri(y + w), ri(x + r), ri(y), INK_BLACK);
    fb_fill_triangle(fb, ri(x), ri(y - r), ri(x - w), ri(y), ri(x), ri(y + r), INK_BLACK);
    fb_fill_triangle(fb, ri(x), ri(y - r), ri(x + w), ri(y), ri(x), ri(y + r), INK_BLACK);
}

static void note(rlcd_fb_t *fb, float x, float y)
{
    fb_fill_ellipse(fb, ri(x), ri(y), 4, 3, INK_BLACK);
    fb_line_f(fb, x + 3.0f, y, x + 3.0f, y - 12.0f, 2.0f, INK_BLACK);
    fb_line_f(fb, x + 3.0f, y - 12.0f, x + 8.0f, y - 8.0f, 2.0f, INK_BLACK);
}

static void glyph(rlcd_fb_t *fb, const font_t *f, float x, float y, const char *s)
{
    int w = text_width(f, s);
    /* white halo keeps the symbol readable over anything */
    for (int dx = -1; dx <= 1; dx++) {
        for (int dy = -1; dy <= 1; dy++) {
            text_draw(fb, f, ri(x) - w / 2 + dx, ri(y) + dy, s, INK_WHITE);
        }
    }
    text_draw_bold(fb, f, ri(x) - w / 2, ri(y), s, INK_BLACK);
}

static void emote(rlcd_fb_t *fb, const pip_rig_t *r, const mascot_pose_t *p)
{
    float t = p->emote_t, s = r->s;
    float side = p->yaw < -20.0f ? -1.0f : 1.0f;
    if (side > 0.0f && g_stage->text_x && SX(r->hx + r->hw / 2.0f) + 36.0f > (float)g_stage->text_x && !p->behind) {
        side = -1.0f; /* next to the message board: emote on the other side */
    }
    float ex = SX(r->hx + side * (r->hw / 2.0f + 2.0f)), ey = SY(r->h_top) - 2.0f;
    switch (p->emote) {
    case EMOTE_FOCUS: { /* three lines that shoot out in turn */
        for (int i = 0; i < 3; i++) {
            float ph = fmodf(t * 1.6f + (float)i * 0.25f, 1.0f);
            float len = 4.0f + 9.0f * sinf(PI_F * ph);
            float a = (-60.0f + (float)i * 35.0f) * PI_F / 180.0f;
            float x0 = ex - side * 4.0f + side * cosf(a) * 6.0f, y0 = ey + 10.0f + sinf(a) * 6.0f;
            fb_line_f(fb, x0, y0, x0 + side * cosf(a) * len, y0 + sinf(a) * len, 2.5f, INK_BLACK);
        }
        break;
    }
    case EMOTE_IDEA: {
        float bob = 2.0f * sinf(t * 5.0f);
        float bx = ex + side * 4.0f, by = ey - 10.0f + bob;
        fb_disc_f(fb, bx, by, 7.0f, INK_BLACK);
        fb_disc_f(fb, bx, by, 4.5f, INK_WHITE);
        fb_fill_rect(fb, ri(bx - 3.0f), ri(by + 6.0f), 7, 5, INK_BLACK);
        if (fmodf(t, 0.6f) < 0.4f) {
            for (int k = 0; k < 5; k++) {
                float a = (-160.0f + (float)k * 35.0f) * PI_F / 180.0f;
                fb_line_f(fb, bx + cosf(a) * 10.0f, by + sinf(a) * 10.0f, bx + cosf(a) * 14.0f, by + sinf(a) * 14.0f, 2.0f,
                          INK_BLACK);
            }
        }
        break;
    }
    case EMOTE_HEART:
        for (int i = 0; i < 2; i++) {
            float ph = fmodf(t * 0.7f + (float)i * 0.5f, 1.0f);
            heart(fb, ex + side * (2.0f + 6.0f * sinf(ph * 6.0f)), ey + 6.0f - 34.0f * ph, 3.0f + 3.0f * sinf(PI_F * ph));
        }
        break;
    case EMOTE_ZZZ:
        for (int i = 0; i < 3; i++) {
            float ph = fmodf(t * 0.4f + (float)i / 3.0f, 1.0f);
            const font_t *f = ph < 0.33f ? &FONT_11 : (ph < 0.66f ? &FONT_14B : &FONT_20B);
            glyph(fb, f, ex + side * (4.0f + 14.0f * ph), ey - 8.0f - 40.0f * ph, "z");
        }
        break;
    case EMOTE_QUESTION:
        glyph(fb, &FONT_24B, ex + side * 6.0f + 2.5f * sinf(t * 6.0f), ey - 22.0f, "?");
        break;
    case EMOTE_EXCLAIM:
        glyph(fb, &FONT_24B, ex + side * 6.0f, ey - 22.0f - 6.0f * fabsf(sinf(t * 8.0f)), "!");
        break;
    case EMOTE_MUSIC:
        for (int i = 0; i < 2; i++) {
            float ph = fmodf(t * 0.5f + (float)i * 0.5f, 1.0f);
            note(fb, ex + side * (4.0f + 18.0f * ph), ey + 2.0f - 30.0f * ph + 4.0f * sinf(ph * 9.0f));
        }
        break;
    case EMOTE_SWEAT: {
        float ph = fmodf(t * 0.8f, 1.0f);
        float x = SX(r->hx - side * (r->hw / 2.0f - 2.0f)), y = SY(r->h_top) + 6.0f * s + 18.0f * s * ph;
        fb_fill_triangle(fb, ri(x), ri(y - 6.0f), ri(x - 4.0f), ri(y + 2.0f), ri(x + 4.0f), ri(y + 2.0f), INK_BLACK);
        fb_disc_f(fb, x, y + 2.0f, 4.0f, INK_BLACK);
        fb_disc_f(fb, x - 1.0f, y + 2.0f, 1.4f, INK_WHITE);
        break;
    }
    case EMOTE_SPARKLE:
        for (int i = 0; i < 3; i++) {
            float ph = fmodf(t * 1.3f + (float)i * 0.33f, 1.0f);
            float ox = (i == 0 ? 2.0f : (i == 1 ? 16.0f : 8.0f)) * side, oy = (i == 0 ? -4.0f : (i == 1 ? -18.0f : 8.0f));
            star4(fb, ex + ox, ey + oy, 6.0f * sinf(PI_F * ph));
        }
        break;
    case EMOTE_DOTS: {
        float bx = ex + side * 12.0f, by = ey - 14.0f;
        fb_fill_ellipse(fb, ri(bx), ri(by), 17, 11, INK_BLACK);
        fb_fill_ellipse(fb, ri(bx), ri(by), 15, 9, INK_WHITE);
        fb_disc_f(fb, ex + side * 1.0f, ey - 1.0f, 3.0f, INK_BLACK);
        fb_disc_f(fb, ex + side * 1.0f, ey - 1.0f, 1.5f, INK_WHITE);
        int n = 1 + ((int)(t * 2.5f)) % 3;
        for (int i = 0; i < n; i++) {
            fb_disc_f(fb, bx - 7.0f + (float)i * 7.0f, by, 2.0f, INK_BLACK);
        }
        break;
    }
    case EMOTE_KNOCK: {
        float hx = SX(r->hand[side > 0 ? 1 : 0].x), hy = SY(r->hand[side > 0 ? 1 : 0].y);
        for (int k = 0; k < 3; k++) {
            float a = (-50.0f + (float)k * 50.0f) * PI_F / 180.0f;
            fb_line_f(fb, hx + side * cosf(a) * 9.0f, hy + sinf(a) * 9.0f, hx + side * cosf(a) * 16.0f, hy + sinf(a) * 16.0f,
                      2.5f, INK_BLACK);
        }
        glyph(fb, &FONT_12B, hx + side * 14.0f, hy - 30.0f, "tok");
        break;
    }
    case EMOTE_ALARM:
        for (int sgn = -1; sgn <= 1; sgn += 2) {
            float x = SX(r->hx + (float)sgn * (r->hw / 2.0f + 6.0f)), y = SY(r->h_top) + 8.0f;
            for (int k = 0; k < 3; k++) {
                float jit = (fmodf(t * 10.0f, 1.0f) < 0.5f) ? 1.5f : -1.5f;
                fb_line_f(fb, x + (float)sgn * (float)k * 5.0f, y + jit + (float)k * 4.0f, x + (float)sgn * ((float)k * 5.0f + 6.0f),
                          y - 8.0f + jit + (float)k * 4.0f, 2.0f, INK_BLACK);
            }
        }
        glyph(fb, &FONT_20B, ex + side * 6.0f, ey - 22.0f + 2.0f * sinf(t * 25.0f), "!!");
        break;
    case EMOTE_SOUND: {
        float x = SX(r->ear[side > 0 ? 1 : 0].x) + side * 10.0f * s, y = SY(r->ear[0].y);
        for (int k = 0; k < 3; k++) {
            float ph = fmodf(t * 1.5f + (float)k / 3.0f, 1.0f);
            int rad = ri(6.0f + 14.0f * ph);
            int a0 = side > 0 ? 300 : 120, a1 = side > 0 ? 420 : 240;
            if (ph < 0.85f) fb_arc(fb, ri(x + side * 4.0f), ri(y), rad, a0, a1, 2, INK_BLACK);
        }
        break;
    }
    default: break;
    }
}

/* glass: diagonal glare streaks inverted over whatever is behind them */
static void glass(rlcd_fb_t *fb, float g)
{
    if (g < 0.15f) {
        return;
    }
    int len = ri(60.0f * g);
    for (int k = 0; k < 2; k++) {
        int x0 = ri(SX(-58.0f)) + k * 14, y0 = ZONE_TOP + 22 + k * 6;
        for (int i = 0; i < len; i++) {
            for (int w = 0; w < (k == 0 ? 4 : 2); w++) {
                int x = x0 + i + w, y = y0 + i;
                fb_set(fb, x, y, fb_get(fb, x, y) ? INK_WHITE : INK_BLACK);
            }
        }
    }
}

/* ---- easter eggs: PIP's relatives (original designs) and the smoke puff that swaps them in ---------------- */
static uint32_t hash_u(uint32_t x)
{
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    return x;
}

/* "PIP Mk.0": a boxy wind-up tin toy - blocky shoes, riveted body with a dial, accordion arms, grille mouth,
 * and a turning key on its side */
static void form_tin(rlcd_fb_t *fb, float x, float y, float t, float lean)
{
    float hx = x + lean;
    fb_fill_rect(fb, ri(x - 18.0f), ri(y - 6.0f), 14, 6, INK_BLACK);
    fb_fill_rect(fb, ri(x + 4.0f), ri(y - 6.0f), 14, 6, INK_BLACK);
    fb_box_f(fb, x - 13.0f, y - 15.0f, x - 6.0f, y - 5.0f, 1.0f, 2.0f, INK_WHITE);
    fb_box_f(fb, x + 6.0f, y - 15.0f, x + 13.0f, y - 5.0f, 1.0f, 2.0f, INK_WHITE);
    for (int sd = -1; sd <= 1; sd += 2) { /* accordion arms, swinging stiffly */
        float swing = 4.0f * sinf(t * 6.0f + (float)sd);
        float ax = x + (float)sd * 21.0f, ay = y - 46.0f;
        for (int k = 0; k < 4; k++) {
            float x0 = ax + (float)sd * (2.5f * (float)k), y0 = ay + 6.0f * (float)k + swing * (float)k / 4.0f;
            float x1 = ax + (float)sd * (2.5f * (float)(k + 1)) + (float)sd * ((k & 1) ? -3.0f : 3.0f);
            fb_line_f(fb, x0, y0, x1, y0 + 6.0f + swing / 4.0f, 2.0f, INK_BLACK);
        }
        float cx = ax + (float)sd * 11.0f, cy = ay + 27.0f + swing;
        fb_arc(fb, ri(cx), ri(cy), 4, sd > 0 ? 300 : 120, sd > 0 ? 420 : 240, 2, INK_BLACK); /* claw */
    }
    fb_box_f(fb, x - 21.0f, y - 52.0f, x + 21.0f, y - 14.0f, 3.0f, 3.0f, INK_WHITE);
    for (int k = 0; k < 4; k++) { /* rivets */
        fb_fill_rect(fb, ri(x + ((k & 1) ? 15.0f : -17.0f)), ri(y + ((k & 2) ? -20.0f : -48.0f)), 2, 2, INK_BLACK);
    }
    fb_ellipse(fb, ri(x), ri(y - 38.0f), 7, 7, 2, INK_BLACK); /* dial */
    float na = t * 2.0f;
    fb_line_f(fb, x, y - 38.0f, x + 5.0f * cosf(na), y - 38.0f + 5.0f * sinf(na), 1.5f, INK_BLACK);
    for (int k = 0; k < 3; k++) {
        fb_fill_rect(fb, ri(x - 9.0f + (float)k * 7.0f), ri(y - 26.0f), 4, 4, INK_BLACK);
    }
    float kw = 7.0f * fabsf(cosf(t * 5.0f)) + 1.0f; /* the wind-up key turns */
    fb_line_f(fb, x + 21.0f, y - 34.0f, x + 29.0f, y - 34.0f, 3.0f, INK_BLACK);
    fb_fill_triangle(fb, ri(x + 29.0f), ri(y - 34.0f), ri(x + 36.0f), ri(y - 34.0f - kw), ri(x + 36.0f), ri(y - 34.0f + kw),
                     INK_BLACK);
    fb_fill_rect(fb, ri(hx - 5.0f), ri(y - 57.0f), 10, 6, INK_BLACK); /* neck */
    fb_box_f(fb, hx - 19.0f, y - 89.0f, hx + 19.0f, y - 56.0f, 2.0f, 3.0f, INK_WHITE);
    for (int sd = -1; sd <= 1; sd += 2) {
        float ex = hx + (float)sd * 8.0f, ey = y - 77.0f;
        fb_ellipse(fb, ri(ex), ri(ey), 6, 6, 2, INK_BLACK);
        fb_disc_f(fb, ex + 1.5f * sinf(t * 3.0f), ey, 2.2f, INK_BLACK);
    }
    fb_rect(fb, ri(hx - 10.0f), ri(y - 67.0f), 21, 7, 1, INK_BLACK); /* grille */
    for (int k = 1; k < 5; k++) {
        fb_vline(fb, ri(hx - 10.0f + (float)k * 4.0f), ri(y - 67.0f), 7, 1, INK_BLACK);
    }
    fb_line_f(fb, hx, y - 89.0f, hx, y - 99.0f, 2.0f, INK_BLACK);
    fb_disc_f(fb, hx, y - 101.0f, 3.5f, INK_BLACK);
}

/* "PIP-1960": a cabinet computer - tape reels, a field of status lamps, and a printer slot */
static void form_mainframe(rlcd_fb_t *fb, float x, float y, float t)
{
    fb_fill_rect(fb, ri(x - 38.0f), ri(y - 4.0f), 77, 4, INK_BLACK); /* plinth */
    fb_box_f(fb, x - 34.0f, y - 106.0f, x + 34.0f, y - 3.0f, 2.0f, 2.0f, INK_WHITE);
    fb_fill_rect(fb, ri(x - 34.0f), ri(y - 106.0f), 69, 8, INK_BLACK);
    for (int k = 0; k < 4; k++) {
        fb_fill_rect(fb, ri(x - 28.0f + (float)k * 6.0f), ri(y - 103.0f), 2, 2, INK_WHITE);
    }
    for (int sd = -1; sd <= 1; sd += 2) { /* tape reels */
        float rx = x + (float)sd * 16.0f, ry = y - 80.0f, ang = t * (sd < 0 ? 3.0f : 3.6f);
        fb_ellipse(fb, ri(rx), ri(ry), 13, 13, 2, INK_BLACK);
        for (int k = 0; k < 3; k++) {
            float a = ang + (float)k * 2.0944f;
            fb_line_f(fb, rx, ry, rx + 10.0f * cosf(a), ry + 10.0f * sinf(a), 2.0f, INK_BLACK);
        }
        fb_disc_f(fb, rx, ry, 3.0f, INK_BLACK);
    }
    fb_hline(fb, ri(x - 16.0f), ri(y - 66.0f), 33, 1, INK_BLACK);
    for (int row = 0; row < 2; row++) { /* status lamps */
        for (int k = 0; k < 7; k++) {
            int lx = ri(x - 28.0f + (float)k * 8.5f), ly = ri(y - 58.0f + (float)row * 7.0f);
            if (hash_u((uint32_t)(row * 7 + k) * 2654435761u + (uint32_t)(t * 4.0f)) & 1u) {
                fb_fill_rect(fb, lx, ly, 4, 4, INK_BLACK);
            } else {
                fb_rect(fb, lx, ly, 4, 4, 1, INK_BLACK);
            }
        }
    }
    fb_fill_rect(fb, ri(x - 14.0f), ri(y - 40.0f), 29, 3, INK_BLACK); /* printer slot */
    float len = fminf(30.0f, fmaxf(0.0f, (t - 2.0f) * 14.0f));
    if (len > 1.0f) {
        fb_fill_rect(fb, ri(x - 12.0f), ri(y - 37.0f), 25, ri(len), INK_WHITE);
        fb_rect(fb, ri(x - 12.0f), ri(y - 37.0f), 25, ri(len), 1, INK_BLACK);
        if (len > 18.0f) {
            int tw = text_width(&FONT_12B, "HI!");
            text_draw(fb, &FONT_12B, ri(x) - tw / 2, ri(y - 37.0f + len - 16.0f), "HI!", INK_BLACK);
        }
    }
}

/* a round cloud of smoke that hides the swap */
static void puff(rlcd_fb_t *fb, float cx, float cy, float a)
{
    if (a < 0.05f) {
        return;
    }
    a = a > 1.0f ? 1.0f : a;
    for (int k = 0; k < 8; k++) {
        float ang = (float)k * 0.785f + 0.3f, rr = 14.0f + 18.0f * a;
        float px = cx + cosf(ang) * rr, py = cy + sinf(ang) * rr * 1.3f, rad = 6.0f + 11.0f * a;
        fb_disc_f(fb, px, py, rad + 2.0f, INK_BLACK);
        fb_disc_f(fb, px, py, rad, INK_WHITE);
    }
    fb_disc_f(fb, cx, cy, 16.0f + 18.0f * a, INK_WHITE);
    for (int k = 0; k < 4; k++) { /* sparkle specks */
        float ang = (float)k * 1.57f + a * 3.0f;
        fb_fill_rect(fb, ri(cx + cosf(ang) * 10.0f * a), ri(cy + sinf(ang) * 12.0f * a), 2, 2, INK_BLACK);
    }
}

void ui_draw_mascot_on(rlcd_fb_t *fb, const mascot_pose_t *p, const ui_stage_t *st)
{
    if (g_hidden) {
        return;
    }
    g_stage = st;
    fb_clip(st->x, st->y, st->w, st->h);
    pip_rig_t r;
    mascot_rig(p, &r);
    /* shadow stays on the floor and shrinks as PIP leaves it */
    float air = p->y < 0.0f ? -p->y : 0.0f;
    float sh = 1.0f / (1.0f + air / 40.0f);
    if (p->y < 26.0f) {
        fb_fill_ellipse_pat(fb, ri(SX(p->x)), ri(SY(p->y > 0.0f ? p->y : 0.0f) + 2.0f), ri(25.0f * r.s * sh), ri(5.0f * r.s * sh), 1);
    }
    if (p->form == PIP_FORM_TIN || p->form == PIP_FORM_MAINFRAME) {
        if (p->form == PIP_FORM_TIN) {
            form_tin(fb, SX(p->x), SY(p->y), p->form_t, p->lean);
        } else {
            form_mainframe(fb, SX(p->x), SY(p->y), p->form_t);
        }
        if (p->emote) {
            emote(fb, &r, p);
        }
        puff(fb, SX(p->x), SY(p->y) - 55.0f, p->puff);
        fb_clip_reset();
        g_stage = &UI_STAGE_COLUMN;
        return;
    }
    bool fp_behind = p->floor_prop && p->fp_y < p->y;
    /* hands on the keyboard: the laptop goes under the arms, not over them */
    bool fp_under_hands = p->floor_prop == PROP_LAPTOP && p->grip > 0.5f && !fp_behind;
    if (fp_behind) {
        ui_prop_floor(fb, p, SX(p->fp_x), SY(p->fp_y) - p->fp_lift);
    }
    bool phones = p->held_l == PROP_HEADPHONES;
    for (int i = 0; i < 2; i++) {
        if (r.ear_z[i] < 0.0f) ear(fb, &r, i, phones);
    }
    for (int i = 0; i < 2; i++) {
        if (r.arm_z[i] < 0.0f) arm(fb, &r, i);
    }
    if (!r.sitting) legs(fb, &r);
    body(fb, &r);
    if (r.sitting) legs(fb, &r);
    head(fb, &r, p);
    if (phones) headphones_band(fb, &r);
    for (int i = 0; i < 2; i++) {
        if (r.ear_z[i] >= 0.0f) ear(fb, &r, i, phones);
    }
    ui_prop_held(fb, p, &r, st->cx, st->fy, true); /* props that sit behind the near arm */
    if (fp_under_hands) {
        ui_prop_floor(fb, p, SX(p->fp_x), SY(p->fp_y) - p->fp_lift);
    }
    for (int i = 0; i < 2; i++) {
        if (r.arm_z[i] >= 0.0f) arm(fb, &r, i);
    }
    ui_prop_held(fb, p, &r, st->cx, st->fy, false);
    if (p->floor_prop && !fp_behind && !fp_under_hands) {
        ui_prop_floor(fb, p, SX(p->fp_x), SY(p->fp_y) - p->fp_lift);
    }
    if (p->obj) {
        ui_prop_flying(fb, p, &r, st->cx, st->fy);
    }
    if (p->emote) {
        emote(fb, &r, p);
    }
    glass(fb, p->glass);
    puff(fb, SX(p->x), SY(p->y) - 55.0f, p->puff);
    fb_clip_reset();
    g_stage = &UI_STAGE_COLUMN;
}

void ui_draw_mascot(rlcd_fb_t *fb, const mascot_pose_t *p) { ui_draw_mascot_on(fb, p, &UI_STAGE_COLUMN); }
