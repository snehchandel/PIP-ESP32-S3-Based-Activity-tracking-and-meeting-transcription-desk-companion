#include "mascot.h"

#include <math.h>
#include <string.h>

#include "pip_sprites.h"

typedef char pip_sprite_count_guard_t[(PIP_SPRITE_COUNT == PIP_EXPR_COUNT) ? 1 : -1];

const uint8_t *mascot_bits(pip_expr_t e)
{
    return pip_sprites[(unsigned)e < PIP_EXPR_COUNT ? e : PIP_EXPR_READY];
}

void mascot_eye_spec(pip_expr_t e, eye_style_t *style, int *dx, int *dy, int *h)
{
    const int8_t *s = pip_eye_spec[(unsigned)e < PIP_EXPR_COUNT ? e : PIP_EXPR_READY];
    *style = (eye_style_t)s[0];
    *dx = s[1];
    *dy = s[2];
    *h = s[3];
}

void mascot_eye_anchors(int *lx, int *ly, int *rx, int *ry)
{
    *lx = PIP_EYE_L_X;
    *ly = PIP_EYE_L_Y;
    *rx = PIP_EYE_R_X;
    *ry = PIP_EYE_R_Y;
}

const char *mascot_expr_name(pip_expr_t e)
{
    static const char *const names[PIP_EXPR_COUNT] = {"READY",  "LISTENING", "THINKING", "WORKING",
                                                      "PAUSED", "DONE",      "ALARM",    "SLEEP"};
    return (unsigned)e < PIP_EXPR_COUNT ? names[e] : "READY";
}

/* ---- easing helpers (t in permille) ---------------------------------------------------- */
static float ease(float x) { return x <= 0 ? 0 : (x >= 1 ? 1 : x * x * (3 - 2 * x)); } /* smoothstep */
static int8_t r8(float v) { return (int8_t)lroundf(v); }

/* 0 -> peak -> 0 hold shape: rise over [0,a], hold, fall over [b,1] */
static float hold(float t, float a, float b) { return t < a ? ease(t / a) : (t > b ? ease((1 - t) / (1 - b)) : 1); }

mascot_pose_t mascot_event_pose(anim_kind_t k, int t_permille)
{
    mascot_pose_t p;
    memset(&p, 0, sizeof p);
    float t = (float)t_permille / 1000.0f;
    switch (k) {
    case ANIM_BLINK: p.lid = (uint8_t)lroundf(8.0f * (1.0f - fabsf(2.0f * t - 1.0f))); break;
    case ANIM_DOUBLE_BLINK: {
        float u = t < 0.5f ? t * 2 : (t - 0.5f) * 2;
        p.lid = (uint8_t)lroundf(8.0f * (1.0f - fabsf(2.0f * u - 1.0f)));
        break;
    }
    case ANIM_GLANCE_TEXT: {
        float g = hold(t, 0.18f, 0.80f);
        p.look_x = r8(4 * g);
        p.look_y = r8(1 * g);
        break;
    }
    case ANIM_LOOK_AROUND:
        if (t < 0.45f) {
            p.look_x = r8(-4 * hold(t / 0.45f, 0.3f, 0.75f));
        } else {
            p.look_x = r8(4 * hold((t - 0.45f) / 0.55f, 0.3f, 0.75f));
        }
        break;
    case ANIM_LOOK_UP: {
        float g = hold(t, 0.2f, 0.75f);
        p.look_x = r8(2 * g);
        p.look_y = r8(-3 * g);
        break;
    }
    case ANIM_HOP: p.dy = r8(-6.0f * sinf(3.14159f * t)); break;
    case ANIM_NOD: p.dy = r8(2.0f * sinf(3.14159f * t)); p.look_y = r8(1.0f * sinf(3.14159f * t)); break;
    case ANIM_TYPE: p.dy = (int8_t)(((int)(t * 12)) % 2); p.look_x = 3; p.look_y = 2; break;
    default: break;
    }
    return p;
}

static uint32_t rnd(mascot_anim_t *a)
{
    a->rng ^= a->rng << 13;
    a->rng ^= a->rng >> 17;
    a->rng ^= a->rng << 5;
    return a->rng;
}

static const uint32_t DURATION[ANIM_COUNT] = {0, 180, 420, 1800, 2400, 1500, 600, 500, 1000};

void mascot_anim_init(mascot_anim_t *a, uint32_t seed, uint32_t now_ms)
{
    memset(a, 0, sizeof *a);
    a->rng = seed ? seed : 0x9E3779B9u;
    a->next_at_ms = now_ms + 1500u;
}

void mascot_anim_trigger(mascot_anim_t *a, anim_kind_t k, uint32_t now_ms)
{
    a->kind = k;
    a->start_ms = now_ms;
    a->dur_ms = DURATION[k];
}

/* Weighted idle repertoire per expression (weights out of 100). Closed-eye moods don't blink. */
static anim_kind_t pick(mascot_anim_t *a, pip_expr_t e)
{
    /* columns: blink, double blink, glance at text, look around, look up, hop, nod, type */
    static const uint8_t W[PIP_EXPR_COUNT][8] = {
        {40, 10, 15, 15, 5, 10, 5, 0},  /* READY: lively */
        {50, 0, 20, 0, 30, 0, 0, 0},    /* LISTENING */
        {10, 0, 0, 45, 45, 0, 0, 0},    /* THINKING: looks around / up */
        {35, 0, 25, 0, 0, 0, 10, 30},   /* WORKING: glances at the text, types */
        {0, 0, 0, 0, 0, 0, 100, 0},     /* PAUSED: sips (nod) */
        {30, 0, 10, 0, 0, 60, 0, 0},    /* DONE: happy hops */
        {0, 0, 0, 0, 0, 0, 0, 0},       /* ALARM: continuous shake instead */
        {0, 0, 0, 0, 0, 0, 0, 0},       /* SLEEP: breathing only */
    };
    const uint8_t *w = W[e];
    uint32_t total = 0;
    for (int i = 0; i < 8; i++) {
        total += w[i];
    }
    if (!total) {
        return ANIM_NONE;
    }
    uint32_t r = rnd(a) % total;
    for (int i = 0; i < 8; i++) {
        if (r < w[i]) {
            return (anim_kind_t)(ANIM_BLINK + i);
        }
        r -= w[i];
    }
    return ANIM_BLINK;
}

bool mascot_anim_step(mascot_anim_t *a, pip_expr_t e, uint32_t now_ms)
{
    if (now_ms - a->last_frame_ms < MASCOT_FRAME_MS) {
        return false;
    }
    a->last_frame_ms = now_ms;
    if (e != a->expr) {
        a->expr = e;
        a->kind = ANIM_NONE;
        a->next_at_ms = now_ms + 600u;
    }
    if (a->kind == ANIM_NONE && (int32_t)(now_ms - a->next_at_ms) >= 0) {
        anim_kind_t k = pick(a, e);
        if (k != ANIM_NONE) {
            mascot_anim_trigger(a, k, now_ms);
        }
        a->next_at_ms = now_ms + 2500u + rnd(a) % 6000u; /* random interval: 2.5 - 8.5 s */
    }
    mascot_pose_t p;
    memset(&p, 0, sizeof p);
    if (a->kind != ANIM_NONE) {
        uint32_t el = now_ms - a->start_ms;
        if (el >= a->dur_ms) {
            a->kind = ANIM_NONE;
        } else {
            p = mascot_event_pose(a->kind, (int)(el * 1000u / a->dur_ms));
        }
    }
    /* continuous moods layered on top */
    float s = (float)now_ms;
    if (e == PIP_EXPR_ALARM) {
        p.dx = (int8_t)(((now_ms / 70u) % 2u) ? 2 : -2);
    } else if (e == PIP_EXPR_SLEEP) {
        p.dy = (int8_t)(p.dy + r8(1.4f * sinf(s * 6.2832f / 3200.0f)));
    } else if (e == PIP_EXPR_LISTENING) {
        p.dy = (int8_t)(p.dy + r8(1.2f * sinf(s * 6.2832f / 900.0f)));
    } else if (e == PIP_EXPR_READY || e == PIP_EXPR_WORKING) {
        p.dy = (int8_t)(p.dy + r8(0.6f * sinf(s * 6.2832f / 4000.0f))); /* calm breathing */
    }
    bool changed = memcmp(&p, &a->pose, sizeof p) != 0;
    a->pose = p;
    return changed;
}
