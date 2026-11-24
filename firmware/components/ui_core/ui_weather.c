/* Animated 24x24 weather icons for the header (outdoor conditions synced from the PC).
 * out_code: 0 sun, 1 cloud, 2 rain, 3 snow, 4 storm, 5 fog, 6 sun+cloud, 7 moon, 8 moon+cloud, 9 drizzle. */
#include <math.h>

#include "ui_render.h"

#define PI_F 3.14159265f

static int ri(float v) { return (int)lroundf(v); }

static void sun(rlcd_fb_t *fb, float cx, float cy, float r, float t)
{
    fb_disc_f(fb, cx, cy, r, INK_BLACK);
    float rot = t * 0.6f, pulse = 1.0f + 0.25f * sinf(t * 3.0f);
    for (int k = 0; k < 8; k++) {
        float a = rot + (float)k * PI_F / 4.0f;
        fb_line_f(fb, cx + cosf(a) * (r + 2.0f), cy + sinf(a) * (r + 2.0f), cx + cosf(a) * (r + 2.0f + 3.0f * pulse),
                  cy + sinf(a) * (r + 2.0f + 3.0f * pulse), 2.0f, INK_BLACK);
    }
}

static void moon(rlcd_fb_t *fb, float cx, float cy, float r, float t)
{
    fb_disc_f(fb, cx, cy, r, INK_BLACK);
    fb_disc_f(fb, cx + r * 0.55f, cy - r * 0.35f, r * 0.85f, INK_WHITE);
    for (int k = 0; k < 2; k++) { /* twinkling stars */
        float tw = 0.5f + 0.5f * sinf(t * 2.5f + (float)k * 2.1f);
        float sx = cx + (k == 0 ? 8.0f : 3.0f), sy = cy + (k == 0 ? -6.0f : 6.0f), len = 1.0f + 2.0f * tw;
        fb_line_f(fb, sx - len, sy, sx + len, sy, 1.0f, INK_BLACK);
        fb_line_f(fb, sx, sy - len, sx, sy + len, 1.0f, INK_BLACK);
    }
}

/* white cloud with a black outline; (cx, cy) = centre of its flat bottom */
static void cloud(rlcd_fb_t *fb, float cx, float cy, float k)
{
    float b[3][3] = {{-6.0f, -4.0f, 4.5f}, {0.0f, -7.0f, 6.0f}, {6.0f, -4.0f, 4.5f}};
    for (int i = 0; i < 3; i++) fb_disc_f(fb, cx + b[i][0] * k, cy + b[i][1] * k, (b[i][2] + 1.6f) * k, INK_BLACK);
    fb_fill_rrect(fb, ri(cx - 11.5f * k), ri(cy - 5.0f * k), ri(23.0f * k), ri(6.6f * k), ri(3.0f * k), INK_BLACK);
    for (int i = 0; i < 3; i++) fb_disc_f(fb, cx + b[i][0] * k, cy + b[i][1] * k, b[i][2] * k, INK_WHITE);
    fb_fill_rrect(fb, ri(cx - 10.0f * k), ri(cy - 4.0f * k), ri(20.0f * k), ri(3.6f * k), ri(2.0f * k), INK_WHITE);
}

void ui_weather_icon(rlcd_fb_t *fb, int x, int y, int code, uint32_t ms)
{
    float t = (float)ms / 1000.0f;
    float cx = (float)x + 12.0f, cy = (float)y + 12.0f;
    float drift = 1.2f * sinf(t * 0.9f);
    switch (code) {
    case 0: sun(fb, cx, cy, 5.5f, t); break;
    case 7: moon(fb, cx - 1.0f, cy, 8.0f, t); break;
    case 6:
        sun(fb, cx - 4.0f, cy - 4.0f, 4.5f, t);
        cloud(fb, cx + 3.0f + drift, cy + 9.0f, 0.75f);
        break;
    case 8:
        moon(fb, cx - 4.0f, cy - 4.0f, 6.5f, t);
        cloud(fb, cx + 3.0f + drift, cy + 9.0f, 0.75f);
        break;
    case 1:
        cloud(fb, cx + drift - 4.0f, cy + 1.0f, 0.6f);
        cloud(fb, cx - drift * 0.6f + 1.0f, cy + 8.0f, 0.9f);
        break;
    case 2:
    case 9: {
        cloud(fb, cx + drift * 0.5f, cy + 2.0f, 0.95f);
        for (int k = 0; k < 3; k++) {
            float ph = fmodf(t * (code == 2 ? 1.8f : 1.1f) + (float)k * 0.37f, 1.0f);
            float dx = cx - 7.0f + (float)k * 7.0f, dy = cy + 4.0f + 8.0f * ph;
            if (code == 2) {
                fb_line_f(fb, dx, dy, dx - 1.5f, dy + 4.0f, 2.0f, INK_BLACK);
            } else {
                fb_disc_f(fb, dx, dy + 2.0f, 1.0f, INK_BLACK);
            }
        }
        break;
    }
    case 3:
        cloud(fb, cx + drift * 0.5f, cy + 2.0f, 0.95f);
        for (int k = 0; k < 3; k++) {
            float ph = fmodf(t * 0.6f + (float)k * 0.33f, 1.0f);
            float fx = cx - 7.0f + (float)k * 7.0f + 1.5f * sinf(t * 2.0f + (float)k), fy = cy + 5.0f + 7.0f * ph;
            fb_line_f(fb, fx - 2.0f, fy, fx + 2.0f, fy, 1.0f, INK_BLACK);
            fb_line_f(fb, fx, fy - 2.0f, fx, fy + 2.0f, 1.0f, INK_BLACK);
        }
        break;
    case 4:
        cloud(fb, cx + drift * 0.5f, cy + 2.0f, 0.95f);
        if (fmodf(t, 1.7f) < 1.2f || fmodf(t, 0.2f) < 0.1f) { /* flickering bolt */
            fb_fill_triangle(fb, ri(cx + 1.0f), ri(cy + 2.0f), ri(cx - 4.0f), ri(cy + 8.0f), ri(cx), ri(cy + 8.0f), INK_BLACK);
            fb_fill_triangle(fb, ri(cx + 2.0f), ri(cy + 6.0f), ri(cx - 2.0f), ri(cy + 13.0f), ri(cx + 4.0f), ri(cy + 6.0f), INK_BLACK);
        }
        break;
    case 5:
    default:
        for (int k = 0; k < 4; k++) {
            float off = 3.0f * sinf(t * 0.8f + (float)k * 1.3f);
            fb_line_f(fb, cx - 9.0f + off, cy - 6.0f + (float)k * 4.5f, cx + 7.0f + off, cy - 6.0f + (float)k * 4.5f, 2.0f,
                      INK_BLACK);
        }
        break;
    }
}
