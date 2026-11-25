/* Screens 01-06: idle (PIP's full-screen world), listening, thinking, focus running, paused, break. */
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

static int centered_x(const font_t *f, const char *s) { return CONTENT_X + (CONTENT_W - text_width(f, s)) / 2; }

static int headline(rlcd_fb_t *fb, const font_t *f, const char *s, int y, bool center, ui_meta_t *meta)
{
    int x = center ? centered_x(f, s) : CONTENT_X;
    text_draw_bold(fb, f, x, y, s, INK_BLACK);
    ui_meta_add(meta, "primary_text", x, y, text_width(f, s) + 1, f->line_h, -1);
    return y + f->line_h;
}

static void big_timer(rlcd_fb_t *fb, uint32_t ms, int y, ui_meta_t *meta)
{
    char t[8];
    ui_fmt_mmss(t, ms);
    int w = text_width(&FONT_64, t);
    int x = CONTENT_X + (CONTENT_W - w) / 2;
    text_draw(fb, &FONT_64, x, y, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", x, y + 8, w, FONT_64.line_h - 22, -1);
}

static void step_title_block(rlcd_fb_t *fb, const ui_model_t *m, const font_t *f, int y, int lines, ui_meta_t *meta)
{
    int n = text_draw_wrap(fb, f, CONTENT_X, y, CONTENT_W, lines, 2, m->step_title, INK_BLACK);
    ui_meta_add(meta, "step_title", CONTENT_X, y, CONTENT_W, n * (f->line_h + 2), -1);
}

/* ---- idle: PIP's world -------------------------------------------------------------------- */
typedef char board_geometry_guard_t[(BOARD_X - STAGE_CX == (int)PIP_BOARD_DX) ? 1 : -1];

/* the room: a little space station - porthole with a ringed planet, a blinking wall terminal with a scope, a
 * conduit, deck plates with a hazard edge. Line art only, so the board text stays the loudest thing. */
static uint32_t mix32(uint32_t x)
{
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

static void hazard(rlcd_fb_t *fb, int x, int y, int w, int h)
{
    for (int yy = y; yy < y + h; yy++) {
        for (int xx = x; xx < x + w; xx++) {
            if (((xx + yy) % 6 + 6) % 6 < 3) {
                fb_set(fb, xx, yy, INK_BLACK);
            }
        }
    }
}

static void porthole(rlcd_fb_t *fb, int cx, int cy, uint32_t ms)
{
    fb_fill_circle(fb, cx, cy, 25, INK_BLACK);
    fb_fill_circle(fb, cx, cy, 21, INK_WHITE);
    fb_arc(fb, cx, cy, 18, 0, 360, 1, INK_BLACK);
    for (int k = 0; k < 8; k++) { /* rivets */
        float a = (float)k * 0.785398f + 0.39f;
        fb_fill_rect(fb, cx + (int)lroundf(23.0f * cosf(a)), cy + (int)lroundf(23.0f * sinf(a)), 2, 2, INK_WHITE);
    }
    static const int8_t sx[7] = {-11, -4, 9, -13, 3, 12, -6}, sy[7] = {-9, -13, -10, 4, -4, 2, 11};
    for (int i = 0; i < 7; i++) { /* stars, one or two twinkling */
        int x = cx + sx[i], y = cy + sy[i];
        fb_set(fb, x, y, INK_BLACK);
        if ((mix32((uint32_t)i * 977u + ms / 700u) & 7u) == 0u) {
            fb_set(fb, x - 1, y, INK_BLACK);
            fb_set(fb, x + 1, y, INK_BLACK);
            fb_set(fb, x, y - 1, INK_BLACK);
            fb_set(fb, x, y + 1, INK_BLACK);
        }
    }
    uint32_t ph = ms % 9000u; /* a shooting star every 9 s */
    if (ph < 500u) {
        int u = (int)ph * 22 / 500;
        fb_line(fb, cx - 12 + u, cy - 12 + u / 3, cx - 16 + u, cy - 13 + u / 3, 1, INK_BLACK);
    }
    int px = cx + 4, py = cy + 4; /* ringed planet: ring behind, planet, then the ring's front half */
    fb_ellipse(fb, px, py, 14, 4, 1, INK_BLACK);
    fb_fill_circle(fb, px, py, 7, INK_BLACK);
    fb_fill_circle(fb, px, py, 6, INK_WHITE);
    fb_fill_ellipse_pat(fb, px + 2, py + 2, 4, 4, 1); /* shaded side */
    for (int dx = -14; dx <= 14; dx++) {
        float u = (float)dx / 14.0f;
        int dy = (int)lroundf(4.0f * sqrtf(1.0f - u * u));
        fb_set(fb, px + dx, py + dy, INK_BLACK);
        fb_set(fb, px + dx, py + dy - 1, INK_WHITE);
    }
}

static void terminal(rlcd_fb_t *fb, int x, int y, uint32_t ms)
{
    const int w = 40, h = 62;
    fb_fill_rect(fb, x, y, w, h, INK_WHITE);
    fb_rect(fb, x, y, w, h, 1, INK_BLACK);
    fb_fill_rect(fb, x, y, w, 6, INK_BLACK);
    for (int i = 0; i < 3; i++) {
        fb_fill_rect(fb, x + 4 + i * 5, y + 2, 2, 2, INK_WHITE);
    }
    for (int r = 0; r < 3; r++) { /* status lights */
        for (int c = 0; c < 5; c++) {
            int lx = x + 5 + c * 7, ly = y + 10 + r * 7;
            if (mix32((uint32_t)(r * 5 + c) * 131u + ms / 450u + (uint32_t)c) & 1u) {
                fb_fill_rect(fb, lx, ly, 4, 4, INK_BLACK);
            } else {
                fb_rect(fb, lx, ly, 4, 4, 1, INK_BLACK);
            }
        }
    }
    int sx = x + 4, sy = y + 34, sw = w - 8, sh = 22; /* scope */
    fb_fill_rect(fb, sx, sy, sw, sh, INK_BLACK);
    for (int i = 1; i < sw - 1; i++) {
        float ph = (float)i * 0.45f + (float)ms * 0.006f;
        int wy = sy + sh / 2 + (int)lroundf(6.0f * sinf(ph) * (0.6f + 0.4f * sinf(ph * 0.31f)));
        fb_set(fb, sx + i, wy, INK_WHITE);
        fb_set(fb, sx + i, wy + 1, INK_WHITE);
    }
    for (int i = 2; i < sw; i += 6) { /* graticule */
        fb_set(fb, sx + i, sy + sh / 2, INK_WHITE);
    }
}

static void world_backdrop(rlcd_fb_t *fb, uint32_t ms)
{
    /* wall: a panel seam with rivets, a conduit from the terminal down into the deck */
    for (int x = WORLD_X + 2; x < BOARD_X; x += 3) {
        fb_set(fb, x, 128, INK_BLACK);
    }
    for (int x = 18; x < BOARD_X; x += 40) {
        fb_fill_rect(fb, x, 124, 2, 2, INK_BLACK);
        fb_fill_rect(fb, x, 131, 2, 2, INK_BLACK);
    }
    const int px = 124;
    fb_vline(fb, px, 112, FLOOR_Y - 112, 1, INK_BLACK);
    fb_vline(fb, px + 5, 112, FLOOR_Y - 112, 1, INK_BLACK);
    for (int y = 140; y < FLOOR_Y - 8; y += 34) {
        fb_fill_rect(fb, px - 2, y, 10, 4, INK_BLACK);
    }
    porthole(fb, 42, 78, ms);
    terminal(fb, 104, 50, ms);
    /* deck: lip, plates in gentle perspective, rivets, a hazard-striped edge */
    fb_hline(fb, WORLD_X, FLOOR_Y, WORLD_W, 2, INK_BLACK);
    fb_hline(fb, WORLD_X, FLOOR_Y + 3, WORLD_W, 1, INK_BLACK);
    const int y0 = FLOOR_Y + 4, y1 = BAR_Y - 7, vx = 200, vy = -260, seam = y0 + 7;
    for (int x = -60; x <= 460; x += 40) {
        for (int y = y0 + 1; y <= y1; y += 2) {
            int qx = vx + (x - vx) * (y - vy) / (y1 - vy);
            if (qx >= WORLD_X && qx < WORLD_X + WORLD_W) {
                fb_set(fb, qx, y, INK_BLACK);
            }
        }
        int rx = vx + (x - vx) * (seam - vy) / (y1 - vy) + 20;
        if (rx >= WORLD_X + 1 && rx < WORLD_X + WORLD_W - 2) {
            fb_fill_rect(fb, rx, seam - 1, 2, 2, INK_BLACK);
        }
    }
    for (int x = WORLD_X + 1; x < WORLD_X + WORLD_W; x += 3) {
        fb_set(fb, x, seam, INK_BLACK);
    }
    fb_hline(fb, WORLD_X, BAR_Y - 6, WORLD_W, 1, INK_BLACK);
    hazard(fb, WORLD_X, BAR_Y - 4, WORLD_W, 3);
}

/* drawn over PIP: the airlock pillar at the left edge, where PIP fetches its props from */
static void world_foreground(rlcd_fb_t *fb, const ui_model_t *m)
{
    const int x = WORLD_X, w = 9, top = 116;
    fb_fill_rect(fb, x, top, w, FLOOR_Y - top, INK_WHITE);
    fb_rect(fb, x, top, w, FLOOR_Y - top, 1, INK_BLACK);
    hazard(fb, x + 2, top + 2, w - 4, FLOOR_Y - top - 4);
    fb_fill_rect(fb, x, top - 6, w + 3, 6, INK_BLACK);
    bool busy = m->pose.x < PIP_WORLD_L + 10.0f; /* PIP is at the hatch */
    int lx = x + 5, ly = top - 12;
    fb_fill_circle(fb, lx, ly, 4, INK_BLACK);
    if (!busy || (m->anim_ms / 250u) % 2u) {
        fb_fill_circle(fb, lx, ly, 2, INK_WHITE);
    }
}

/* octagonal (chamfered) panel shapes */
static void chamfer_fill(rlcd_fb_t *fb, int x, int y, int w, int h, int c, ink_t ink)
{
    fb_fill_rect(fb, x + c, y, w - 2 * c, h, ink);
    fb_fill_rect(fb, x, y + c, w, h - 2 * c, ink);
    fb_fill_triangle(fb, x, y + c, x + c, y, x + c, y + c, ink);
    fb_fill_triangle(fb, x + w - 1, y + c, x + w - 1 - c, y, x + w - 1 - c, y + c, ink);
    fb_fill_triangle(fb, x, y + h - 1 - c, x + c, y + h - 1, x + c, y + h - 1 - c, ink);
    fb_fill_triangle(fb, x + w - 1, y + h - 1 - c, x + w - 1 - c, y + h - 1, x + w - 1 - c, y + h - 1 - c, ink);
}

static void chamfer_outline(rlcd_fb_t *fb, int x, int y, int w, int h, int c, int t)
{
    int r = x + w - 1, b = y + h - 1;
    fb_hline(fb, x + c, y, w - 2 * c, t, INK_BLACK);
    fb_hline(fb, x + c, b - t + 1, w - 2 * c, t, INK_BLACK);
    fb_vline(fb, x, y + c, h - 2 * c, t, INK_BLACK);
    fb_vline(fb, r - t + 1, y + c, h - 2 * c, t, INK_BLACK);
    for (int k = 0; k < t; k++) {
        fb_line(fb, x + k, y + c, x + c, y + k, 1, INK_BLACK);
        fb_line(fb, r - k, y + c, r - c, y + k, 1, INK_BLACK);
        fb_line(fb, x + k, b - c, x + c, b - k, 1, INK_BLACK);
        fb_line(fb, r - k, b - c, r - c, b - k, 1, INK_BLACK);
    }
}

/* the message board is a holo-monitor: chamfered bezel, status tab, on a telescopic pedestal */
static void board_panel(rlcd_fb_t *fb, int x, int y, int w, int h, uint32_t ms)
{
    chamfer_fill(fb, x + 3, y + 3, w, h, 12, INK_BLACK); /* drop shadow */
    chamfer_fill(fb, x, y, w, h, 12, INK_WHITE);
    chamfer_outline(fb, x, y, w, h, 12, 2);
    chamfer_outline(fb, x + 4, y + 4, w - 8, h - 8, 9, 1);
    /* status tab on the top edge: three lights, one blinking */
    int tx = x + w - 84;
    fb_fill_triangle(fb, tx - 6, y + 1, tx, y - 4, tx, y + 1, INK_BLACK);
    fb_fill_rect(fb, tx, y - 4, 52, 5, INK_BLACK);
    fb_fill_triangle(fb, tx + 52, y - 4, tx + 58, y + 1, tx + 52, y + 1, INK_BLACK);
    for (int i = 0; i < 3; i++) {
        if (i < 2 || (ms / 600u) % 2u) {
            fb_fill_rect(fb, tx + 8 + i * 8, y - 2, 4, 2, INK_WHITE);
        }
    }
    for (int i = 0; i < 4; i++) { /* signal bars */
        fb_fill_rect(fb, tx + 36 + i * 3, y - 1 - i, 2, 1 + i, INK_WHITE);
    }
}

static void board_stand(rlcd_fb_t *fb)
{
    /* two short, stubby legs with foot pads: the panel hovers just above the deck */
    for (int k = 0; k < 2; k++) {
        int lx = k == 0 ? BOARD_X + 30 : BOARD_R - 30 - 11;
        int top = BOARD_B - 3;
        fb_fill_rect(fb, lx, top, 11, FLOOR_Y - top - 2, INK_WHITE);
        fb_vline(fb, lx, top, FLOOR_Y - top - 2, 2, INK_BLACK);
        fb_vline(fb, lx + 9, top, FLOOR_Y - top - 2, 2, INK_BLACK);
        fb_hline(fb, lx + 2, top + 8, 7, 1, INK_BLACK); /* piston ring */
        int bx[4] = {lx - 6, lx + 17, lx + 14, lx - 3}, by[4] = {FLOOR_Y, FLOOR_Y, FLOOR_Y - 5, FLOOR_Y - 5};
        fb_fill_quad(fb, bx, by, INK_BLACK);
    }
}

typedef struct {
    char msg[128];
    int msg_lines;
    int today_rows; /* open items today */
    int up_rows;    /* coming up: the next days */
    bool footer;    /* date line at the bottom of the board */
} board_t;

static int agenda_open(const ui_model_t *m)
{
    int n = 0;
    for (int i = 0; i < m->today_count; i++) {
        n += !m->today[i].done;
    }
    return n;
}

#define BOARD_TX (BOARD_X + BOARD_PAD)
#define BOARD_TW (BOARD_R - BOARD_PAD - BOARD_TX)
#define BOARD_HEAD_Y (BOARD_Y + 7)
#define BOARD_ROW_H (FONT_12.line_h + 1)
#define BOARD_SEC_H (FONT_11.line_h + 1)
#define BOARD_FOOT_Y (BOARD_B - 7 - FONT_11.line_h)
#define BOARD_LIST_B (BOARD_B - 5)

/* lay the board out: today's open items, then what's coming up (at least one row of it when there is any),
 * then the date if there is room left */
static void board_layout(const ui_model_t *m, board_t *b)
{
    if (m->has_active_step) {
        snprintf(b->msg, sizeof b->msg, "Next: %s (%um)", m->step_title, (unsigned)((m->remaining_ms + 59999u) / 60000u));
    } else {
        snprintf(b->msg, sizeof b->msg, "%s",
                 m->link == LINK_TETHERED ? "Hold KEY and tell me what's on your mind."
                                          : "Plan tasks in the PIP app, then focus here.");
    }
    b->msg_lines = text_draw_wrap(NULL, &FONT_12B, 0, 0, BOARD_TW, 3, 2, b->msg, INK_BLACK);
    int y = BOARD_HEAD_Y + FONT_24B.line_h + 3 + b->msg_lines * (FONT_12B.line_h + 2);
    int open = agenda_open(m), up = m->upcoming_count;
    b->today_rows = b->up_rows = 0;
    if (open > 0) {
        y += 6 + BOARD_SEC_H;
        int reserve = up > 0 ? 4 + BOARD_SEC_H + BOARD_ROW_H : 0;
        int fit = (BOARD_LIST_B - y - reserve) / BOARD_ROW_H;
        b->today_rows = open < fit ? open : (fit > 1 ? fit : 1);
        y += b->today_rows * BOARD_ROW_H;
    }
    int gap = open > 0 ? 4 : 6;
    if (up > 0 && y + gap + BOARD_SEC_H + BOARD_ROW_H <= BOARD_LIST_B) {
        y += gap + BOARD_SEC_H;
        int fit = (BOARD_LIST_B - y) / BOARD_ROW_H;
        b->up_rows = up < fit ? up : fit;
        y += b->up_rows * BOARD_ROW_H;
    }
    b->footer = m->date_label[0] && y + 3 <= BOARD_FOOT_Y;
}

/* "TODAY -------------- +2 more" */
static void section_head(rlcd_fb_t *fb, int y, const char *label, int more)
{
    int lw = text_width(&FONT_11, label), mw = 0;
    text_draw(fb, &FONT_11, BOARD_TX, y, label, INK_BLACK);
    if (more > 0) { /* the rest is one double press away */
        char buf[24];
        snprintf(buf, sizeof buf, "+%d more", more);
        mw = text_width(&FONT_11, buf) + 6;
        text_draw(fb, &FONT_11, BOARD_TX + BOARD_TW - mw + 6, y, buf, INK_BLACK);
    }
    fb_hline(fb, BOARD_TX + lw + 6, y + 7, BOARD_TW - lw - 6 - mw, 1, INK_BLACK);
}

/* free-standing holo-monitor on short legs: PIP can walk behind it (only its feet show underneath) */
static void board_draw(rlcd_fb_t *fb, const ui_model_t *m, const board_t *b, ui_meta_t *meta)
{
    const int x = BOARD_X, w = BOARD_R - BOARD_X, h = BOARD_B - BOARD_Y;
    board_stand(fb);
    board_panel(fb, x, BOARD_Y, w, h, m->anim_ms);
    int board = ui_meta_add(meta, "board", x, BOARD_Y, w + 3, h + 3, -1);

    int y = BOARD_HEAD_Y;
    int hw = text_draw_bold(fb, &FONT_24B, BOARD_TX, y, "Let's Focus!", INK_BLACK);
    if ((m->anim_ms / 530u) % 2u == 0u) { /* terminal cursor */
        fb_fill_rect(fb, BOARD_TX + hw + 3, y + 5, 9, FONT_24B.ascent - 3, INK_BLACK);
    }
    ui_meta_add(meta, "primary_text", BOARD_TX, y, text_width(&FONT_24B, "Let's Focus!") + 1, FONT_24B.line_h, board);
    y += FONT_24B.line_h + 3;
    int n = text_draw_wrap(fb, &FONT_12B, BOARD_TX, y, BOARD_TW, 3, 2, b->msg, INK_BLACK);
    ui_meta_add(meta, "secondary_text", BOARD_TX, y, BOARD_TW, n * (FONT_12B.line_h + 2), board);
    y += n * (FONT_12B.line_h + 2);
    if (b->today_rows > 0) {
        y += 6;
        int y0 = y;
        section_head(fb, y, "TODAY", agenda_open(m) - b->today_rows);
        y += BOARD_SEC_H;
        int shown = 0;
        for (int i = 0; i < m->today_count && shown < b->today_rows; i++) {
            const agenda_item_t *it = &m->today[i];
            if (it->done) {
                continue;
            }
            text_draw(fb, &FONT_12B, BOARD_TX, y, it->hhmm[0] ? it->hhmm : "any", INK_BLACK);
            text_draw_fit(fb, &FONT_12, BOARD_TX + 44, y, BOARD_TW - 44, it->title, INK_BLACK);
            y += BOARD_ROW_H;
            shown++;
        }
        ui_meta_add(meta, "agenda_preview", BOARD_TX, y0, BOARD_TW, y - y0, board);
    }
    if (b->up_rows > 0) {
        y += b->today_rows > 0 ? 4 : 6;
        int y0 = y;
        section_head(fb, y, "COMING UP", m->upcoming_count - b->up_rows);
        y += BOARD_SEC_H;
        for (int i = 0; i < b->up_rows; i++) {
            const upcoming_item_t *it = &m->upcoming[i];
            text_draw(fb, &FONT_12B, BOARD_TX, y, it->day, INK_BLACK);
            int tx = BOARD_TX + 32;
            text_draw(fb, &FONT_12, tx, y, it->hhmm[0] ? it->hhmm : "any", INK_BLACK);
            tx += 40;
            text_draw_fit(fb, &FONT_12, tx, y, BOARD_TX + BOARD_TW - tx, it->title, INK_BLACK);
            y += BOARD_ROW_H;
        }
        ui_meta_add(meta, "upcoming_preview", BOARD_TX, y0, BOARD_TW, y - y0, board);
    }
    if (b->footer) {
        text_draw(fb, &FONT_11, BOARD_TX, BOARD_FOOT_Y, m->date_label, INK_BLACK);
        ui_meta_add(meta, "date_text", BOARD_TX, BOARD_FOOT_Y, text_width(&FONT_11, m->date_label), FONT_11.line_h, board);
    }
}

void ui_screen_idle(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    world_backdrop(fb, m->anim_ms);
    board_t b;
    board_layout(m, &b);
    /* depth: PIP behind the board is drawn first and covered by it */
    if (m->pose.behind) {
        ui_draw_mascot_on(fb, &m->pose, &UI_STAGE_WORLD);
    }
    board_draw(fb, m, &b, meta);
    if (!m->pose.behind) {
        ui_draw_mascot_on(fb, &m->pose, &UI_STAGE_WORLD);
    }
    world_foreground(fb, m);
    ui_meta_add(meta, "mascot_stage", MASCOT_X, MASCOT_Y, MASCOT_W, MASCOT_H, -1);
    if (m->has_active_step) {
        ui_hint_t h[] = {{ICON_ARROW, "Start"}, {ICON_CYCLE, "2x: Calendar"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    } else {
        ui_hint_t h[] = {{ICON_MIC, "Hold: Talk"}, {ICON_CYCLE, "2x: Calendar"}};
        ui_chrome_bar(fb, m, h, 2, meta);
    }
}

void ui_screen_listening(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_LISTENING, "Listening", meta);
    headline(fb, &FONT_24B, "Listening...", 44, false, meta);
    char t1[8], t2[8], buf[48];
    ui_fmt_mmss(t1, (uint32_t)m->listen_elapsed_s * 1000u);
    ui_fmt_mmss(t2, (uint32_t)(m->listen_max_s ? m->listen_max_s : 60) * 1000u);
    snprintf(buf, sizeof buf, "%s \xC2\xB7 %s / %s", m->voice_auto ? "What's it about?" : ui_voice_choice_label(m->voice_choice),
             t1, t2);
    text_draw(fb, &FONT_14B, CONTENT_X, 80, buf, INK_BLACK);
    ui_meta_add(meta, "secondary_text", CONTENT_X, 80, text_width(&FONT_14B, buf), FONT_14B.line_h, -1);
    /* 10 discrete level bars, graded heights, filled up to the live level */
    const int bw = 16, gap = 7, base = 200;
    for (int i = 0; i < 10; i++) {
        int h = 14 + i * 8;
        int x = CONTENT_X + i * (bw + gap);
        if (i < (int)m->audio_level * 10 / 8) {
            fb_fill_rect(fb, x, base - h, bw, h, INK_BLACK);
        } else {
            fb_rect(fb, x, base - h, bw, h, 2, INK_BLACK);
        }
    }
    ui_meta_add(meta, "level_meter", CONTENT_X, base - 86, 10 * bw + 9 * gap, 86, -1);
    const char *tip = m->voice_auto ? "Say \"Meeting\", \"Alarms\", \"Calendar\"... then talk."
                                    : "Say it the way you'd tell a friend.";
    text_draw_fit(fb, &FONT_12, CONTENT_X, 214, CONTENT_W, tip, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 214, CONTENT_W, FONT_12.line_h, -1);
    ui_hint_t h[] = {{ICON_MIC, m->voice_auto ? "Stay quiet for the menu" : "Release KEY to send"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

void ui_screen_thinking(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_THINKING, "Thinking", meta);
    headline(fb, &FONT_24B, "Planning...", 44, false, meta);
    /* 3-stage pipeline: done = filled dot, current = ring + dot, pending = ring */
    int cur = m->state == UI_STATE_TRANSCRIBING ? 0 : 1;
    const char *labels[3] = {cur == 0 ? "Transcribing..." : "Heard you",
                             m->thinking_stage[0] && cur == 1 ? m->thinking_stage : "Breaking into steps",
                             "Ready to focus"};
    for (int i = 0; i < 3; i++) {
        int y = 92 + i * 32, cx = CONTENT_X + 9, cy = y + 8;
        fb_fill_circle(fb, cx, cy, 8, INK_BLACK);
        if (i >= cur) {
            fb_fill_circle(fb, cx, cy, 5, INK_WHITE);
            if (i == cur) {
                fb_fill_circle(fb, cx, cy, 3, INK_BLACK);
            }
        }
        if (i < 2) {
            fb_vline(fb, cx - 1, cy + 10, 12, 2, INK_BLACK);
        }
        text_draw_fit(fb, i <= cur ? &FONT_14B : &FONT_14, CONTENT_X + 26, y, CONTENT_W - 26, labels[i], INK_BLACK);
    }
    ui_meta_add(meta, "stage_list", CONTENT_X, 92, CONTENT_W, 3 * 32 - 14, -1);
    ui_hint_t h[] = {{-1, "Please wait"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}

/* Time you can feel: a disc in the corner of PIP's stage that shrinks clockwise as the step runs out (like a kitchen
 * time timer), with the minutes left underneath. Drawn over a white halo so PIP can walk behind it. */
static void focus_pie(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    int stage = meta ? meta->n - 1 : -1; /* nested in mascot_stage (added just before) */
    uint32_t total = m->step_total_ms ? m->step_total_ms : m->remaining_ms;
    uint32_t rem = m->remaining_ms > total ? total : m->remaining_ms;
    float frac = total ? (float)rem / (float)total : 0.0f;
    const int cx = STAGE_X + 31, cy = ZONE_TOP + 31, r = 26;
    fb_fill_circle(fb, cx, cy, r + 3, INK_WHITE);
    fb_fill_circle(fb, cx, cy, r, INK_BLACK);
    fb_fill_circle(fb, cx, cy, r - 2, INK_WHITE);
    const int ri = r - 4;
    float lim = frac * 6.2831853f;
    for (int dy = -ri; dy <= ri; dy++) {
        for (int dx = -ri; dx <= ri; dx++) {
            if (dx * dx + dy * dy > ri * ri) {
                continue;
            }
            float a = atan2f((float)dx, (float)-dy); /* 0 at 12 o'clock, clockwise on screen */
            if (a < 0.0f) {
                a += 6.2831853f;
            }
            if (a <= lim && frac > 0.0f) {
                fb_set(fb, cx + dx, cy + dy, INK_BLACK);
            }
        }
    }
    for (int q = 0; q < 4; q++) { /* quarter ticks on the rim */
        int tx = q == 1 ? 1 : (q == 3 ? -1 : 0), ty = q == 0 ? -1 : (q == 2 ? 1 : 0);
        fb_fill_circle(fb, cx + tx * (r - 1), cy + ty * (r - 1), 1, INK_WHITE);
    }
    char lbl[12];
    uint32_t min = (rem + 59999u) / 60000u;
    if (rem < 60000u) {
        snprintf(lbl, sizeof lbl, "%us", (unsigned)((rem + 999u) / 1000u));
    } else {
        snprintf(lbl, sizeof lbl, "%u min", (unsigned)min);
    }
    int lw = text_width(&FONT_12B, lbl), ly = cy + r + 4;
    fb_fill_rect(fb, cx - lw / 2 - 2, ly - 1, lw + 4, FONT_12B.line_h + 2, INK_WHITE);
    text_draw(fb, &FONT_12B, cx - lw / 2, ly, lbl, INK_BLACK);
    ui_meta_add(meta, "focus_pie", cx - r - 3, cy - r - 3, 2 * r + 7, 2 * r + 7 + FONT_12B.line_h + 4, stage);
}

void ui_screen_focus(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_WORKING, "Focus", meta);
    focus_pie(fb, m, meta);
    big_timer(fb, m->remaining_ms, 34, meta);
    char badge[96];
    if (m->is_starter) {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 Starter", (unsigned)m->step_index, (unsigned)m->step_total);
    } else {
        snprintf(badge, sizeof badge, "Step %u/%u \xC2\xB7 %s", (unsigned)m->step_index, (unsigned)m->step_total,
                 m->task_title[0] ? m->task_title : "Focus Time");
    }
    ui_inverted_pill(fb, &FONT_12B, CONTENT_X, 112, badge, meta, "step_badge");
    step_title_block(fb, m, &FONT_14B, 136, 3, meta);
    if (m->next_step_title[0]) {
        char nx[80];
        snprintf(nx, sizeof nx, "Then: %s", m->next_step_title);
        text_draw_fit(fb, &FONT_11, CONTENT_X, 198, CONTENT_W, nx, INK_BLACK);
        ui_meta_add(meta, "next_step", CONTENT_X, 198, CONTENT_W, FONT_11.line_h, -1);
    }
    uint32_t total = m->step_total_ms ? m->step_total_ms : m->remaining_ms;
    ui_progress(fb, CONTENT_X, 228, CONTENT_W, 14, total - (m->remaining_ms > total ? total : m->remaining_ms), total,
                meta);
    ui_hint_t h[] = {{ICON_PAUSE, "Pause"}, {ICON_CHECK, "Done"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_paused(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Paused", meta);
    focus_pie(fb, m, meta);
    big_timer(fb, m->remaining_ms, 34, meta);
    ui_inverted_pill(fb, &FONT_12B, CONTENT_X, 112, "Paused", meta, "step_badge");
    step_title_block(fb, m, &FONT_14, 136, 3, meta);
    const char *calm = "No rush \xE2\x80\x94 resume anytime";
    text_draw(fb, &FONT_12, CONTENT_X, 222, calm, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, 222, text_width(&FONT_12, calm), FONT_12.line_h, -1);
    ui_hint_t h[] = {{ICON_PLAY, "Resume"}, {-1, "BOOT hold: Split \xC2\xB7 2x: Park"}};
    ui_chrome_bar(fb, m, h, 2, meta);
}

void ui_screen_break(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta)
{
    ui_chrome_top(fb, m, meta);
    ui_chrome_mascot(fb, m, PIP_EXPR_PAUSED, "Break", meta);
    int y = headline(fb, &FONT_24B, "Take a Break!", 48, true, meta) + 12;
    char t[8];
    ui_fmt_mmss(t, m->break_remaining_ms);
    text_draw(fb, &FONT_64, centered_x(&FONT_64, t), y - 8, t, INK_BLACK);
    ui_meta_add(meta, "timer_digits", centered_x(&FONT_64, t), y, text_width(&FONT_64, t), FONT_64.line_h - 22, -1);
    const char *cue = "Stretch, sip some water, look far away.";
    int n = text_draw_wrap(fb, &FONT_12, CONTENT_X, y + 70, CONTENT_W, 2, 2, cue, INK_BLACK);
    ui_meta_add(meta, "calm_text", CONTENT_X, y + 70, CONTENT_W, n * (FONT_12.line_h + 2), -1);
    ui_hint_t h[] = {{ICON_CHECK, "ok"}};
    ui_chrome_bar(fb, m, h, 1, meta);
}
