/* PIP choreography: every act is a pure function of time that poses the rig, its props and emotes.
 * Acts start and end near the home pose so the engine can chain them with short cross-fades.
 * Variation axes: variant (act specific), dir (mirrors left/right), mood (tempo + emote flavour). */
#include <math.h>
#include <string.h>

#include "mascot_acts.h"

#define PI_F 3.14159265f
#define TAU_F 6.2831853f

typedef void (*act_fn)(mascot_pose_t *p, float t, float D, int v, float s, int mood);

typedef struct {
    const char *name;
    act_fn fn;
    float dur;       /* seconds at normal tempo */
    uint8_t variants;
} act_t;

/* ---- easing toolkit ------------------------------------------------------------------------ */
static float cl(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
static float sm(float x)
{
    x = cl(x);
    return x * x * (3.0f - 2.0f * x);
}
static float seg(float t, float a, float b) { return b <= a ? (t >= b ? 1.0f : 0.0f) : sm((t - a) / (b - a)); }
static float bump(float t, float a, float b) { return (t <= a || t >= b) ? 0.0f : sinf(PI_F * (t - a) / (b - a)); }
static float wav(float t, float period) { return sinf(TAU_F * t / period); }
static float fmaxf2(float a, float b) { return a > b ? a : b; }
static float fminf2(float a, float b) { return a < b ? a : b; }
/* 0 -> 1 over [a, a+r], back to 0 over [b-r, b] */
static float win(float t, float a, float b, float r) { return fminf2(seg(t, a, a + r), 1.0f - seg(t, b - r, b)); }
static float mixf(float x, float y, float w) { return x + (y - x) * w; }

static void emote(mascot_pose_t *p, int e, float t, float t0)
{
    p->emote = e;
    p->emote_t = t - t0;
}

/* stepping legs, arm swing and a little bob, scaled by `amt` (0..1) */
static void steps(mascot_pose_t *p, float t, float amt, float rate)
{
    float ph = sinf(t * TAU_F * rate);
    p->leg_l = fmaxf2(0.0f, ph) * 5.0f * amt;
    p->leg_r = fmaxf2(0.0f, -ph) * 5.0f * amt;
    p->y -= fabsf(ph) * 1.5f * amt;
    p->arm_l += 20.0f * ph * amt;
    p->arm_r -= 20.0f * ph * amt;
}

/* walk from x0 to x1 during [t0, t1], turning to face the way it goes */
static void walk(mascot_pose_t *p, float t, float t0, float t1, float x0, float x1)
{
    if (t <= t0) {
        p->x = x0;
        return;
    }
    if (t >= t1) {
        p->x = x1;
        return;
    }
    float u = (t - t0) / (t1 - t0);
    p->x = x0 + (x1 - x0) * (0.5f - 0.5f * cosf(PI_F * u));
    float w = win(t, t0, t1, 0.35f);
    p->yaw = mixf(p->yaw, (x1 > x0 ? 72.0f : -72.0f), w);
    steps(p, t, w, 1.8f);
}

/* hop: y offset over [a, b] */
static float hop(float t, float a, float b, float h) { return -h * bump(t, a, b); }

static int mood_emote(int mood, int e0, int e1, int e2) { return mood == 0 ? e0 : (mood == 1 ? e1 : e2); }

/* ==== IDLE ("Let's Focus") ===================================================================== */
static void a_ball(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->mouth = MOUTH_GRIN;
    p->yaw = 20.0f * s * in;
    float hx = s * 24.0f;
    p->obj = PROP_BALL;
    p->obj_t = t;
    if (v == 0) { /* dribble while strolling, then a high toss and catch */
        walk(p, t, 1.0f, 4.0f, 0.0f, s * 18.0f);
        walk(p, t, D * 0.55f, D * 0.55f + 3.0f, s * 18.0f, -s * 10.0f);
        walk(p, t, D - 4.0f, D - 1.0f, -s * 10.0f, 0.0f);
        float b = fabsf(sinf(t * PI_F * 1.6f));
        p->obj_x = p->x + hx;
        p->obj_y = -40.0f * b - 4.0f;
        if (s > 0) p->arm_r = 45.0f + 20.0f * b; else p->arm_l = 45.0f + 20.0f * b;
        float toss = bump(t, D * 0.4f, D * 0.4f + 2.4f);
        if (toss > 0.0f) {
            p->obj_y = -45.0f - 120.0f * toss;
            p->look_y = -1.0f * toss;
            p->eyes = EYE_WIDE;
            if (s > 0) p->arm_r = 170.0f; else p->arm_l = 170.0f;
        }
        if (t > D * 0.4f + 2.4f && t < D * 0.4f + 3.6f) emote(p, EMOTE_SPARKLE, t, D * 0.4f + 2.4f);
    } else if (v == 1) { /* keepy-uppy with the feet, final header */
        float ph = t * 2.4f;
        float b = fabsf(sinf(ph * PI_F));
        p->obj_x = p->x + s * 8.0f;
        p->obj_y = -8.0f - 46.0f * b;
        int foot = ((int)ph) % 2;
        float kick = 1.0f - b;
        if (foot) p->leg_r = 6.0f * kick; else p->leg_l = 6.0f * kick;
        p->look_y = 0.6f;
        p->arm_l = 45.0f;
        p->arm_r = 45.0f;
        if (t > D * 0.7f) { /* header: ball bounces off the head */
            float hb = fabsf(sinf((t - D * 0.7f) * PI_F * 1.5f));
            p->obj_x = p->x;
            p->obj_y = -118.0f - 40.0f * hb;
            p->head_dy = 3.0f * (1.0f - hb);
            p->look_y = -1.0f;
            emote(p, EMOTE_MUSIC, t, D * 0.7f);
        }
    } else if (v == 2) { /* balance on the head, wobble, catch */
        float wob = wav(t, 1.7f) * 5.0f;
        p->lean = wob * 0.6f;
        p->arm_l = 90.0f + wob * 3.0f;
        p->arm_r = 90.0f - wob * 3.0f;
        p->obj_x = p->x + p->lean + wob;
        p->obj_y = -126.0f;
        p->look_y = -1.0f;
        p->eyes = EYE_ANGLED;
        if (t > D - 3.0f) {
            float f = seg(t, D - 3.0f, D - 2.0f);
            p->obj_y = -126.0f + 80.0f * f;
            p->obj_x = p->x + hx * f;
            p->eyes = EYE_WIDE;
            emote(p, EMOTE_EXCLAIM, t, D - 3.0f);
        }
    } else { /* spin the ball on a fingertip */
        if (s > 0) p->arm_r = 172.0f; else p->arm_l = 172.0f;
        p->obj_x = p->x + s * 8.0f;
        p->obj_y = -150.0f;
        p->look_y = -1.0f;
        p->look_x = 0.4f * s;
        p->yaw = 15.0f * s + 10.0f * wav(t, 3.0f);
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_MUSIC, EMOTE_HEART), t, 1.0f);
    }
    if (t > D - 1.4f) { /* lets it drop beside its feet: the next prop trip picks it up from there */
        float f = seg(t, D - 1.4f, D - 0.9f);
        p->obj_x = mixf(p->obj_x, s * 24.0f, f);
        p->obj_y = mixf(p->obj_y, -7.0f, f);
        if (t > D - 0.9f) {
            p->obj = PROP_NONE;
            p->floor_prop = PROP_BALL;
            p->fp_x = s * 24.0f;
            p->fp_y = 0.0f;
        }
    }
}

static void a_knock(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* walks right up to the glass (grows), knocks, waves, steps back */
    float near = win(t, 0.5f, D - 0.5f, 2.2f);
    p->scale = 1.0f + 0.72f * near;
    p->y = 34.0f * near;
    p->x = s * 6.0f * near * (v == 2 ? 3.0f : 1.0f);
    p->glass = near;
    p->eyes = EYE_WIDE;
    p->look_x = 0.0f;
    p->look_y = 0.2f;
    p->mouth = MOUTH_O;
    float knock0 = 3.0f, knock1 = D * 0.55f;
    if (t > knock0 && t < knock1) {
        float k = fabsf(sinf((t - knock0) * PI_F * (v == 1 ? 3.2f : 2.4f)));
        if (v == 1 || s > 0) p->arm_r = 98.0f + 18.0f * k;
        if (v == 1 || s < 0) p->arm_l = 98.0f + 18.0f * k;
        p->lean = 1.5f * k * s;
        if (k > 0.85f) emote(p, EMOTE_KNOCK, t, knock0);
        if (v == 3) { /* presses its face to the glass between knocks */
            p->lid = 0.35f;
            p->mouth = MOUTH_WAVY;
        }
    } else if (t >= knock1) {
        float w = win(t, knock1, D - 1.0f, 0.5f);
        p->arm_r = mixf(0.0f, 150.0f + 20.0f * wav(t, 0.5f), w); /* hello! */
        p->mouth = MOUTH_GRIN;
        p->eyes = EYE_HAPPY;
        emote(p, mood_emote(mood, EMOTE_HEART, EMOTE_EXCLAIM, EMOTE_SPARKLE), t, knock1);
    }
}

static void a_bored(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float sit = win(t, 0.3f, D - 0.3f, 1.2f);
    p->sit = sit;
    p->lid = 0.45f * sit;
    p->mouth = MOUTH_FLAT;
    p->yaw = 25.0f * s * sit;
    if (v == 0) { /* chin in hand, sighs, kicks feet */
        p->arm_r = 150.0f * sit;
        p->head_dy = 3.0f * sit + 2.0f * bump(fmodf(t, 5.0f), 3.0f, 4.6f);
        p->leg_l = 3.0f * fmaxf2(0.0f, wav(t, 1.4f)) * sit;
        p->leg_r = 3.0f * fmaxf2(0.0f, -wav(t, 1.4f)) * sit;
        emote(p, EMOTE_DOTS, t, 2.0f);
    } else if (v == 1) { /* twiddles thumbs */
        p->arm_l = (55.0f + 10.0f * wav(t, 0.6f)) * sit;
        p->arm_r = (55.0f - 10.0f * wav(t, 0.6f)) * sit;
        p->look_y = 0.7f;
    } else if (v == 2) { /* doodles on the floor */
        p->arm_r = (35.0f + 12.0f * wav(t, 0.9f)) * sit;
        p->lean = 3.0f * s * sit;
        p->look_y = 1.0f;
        p->look_x = 0.5f * s;
        p->floor_prop = PROP_PENCIL;
        p->fp_x = s * 26.0f;
        p->fp_y = 4.0f;
    } else { /* counts the ceiling tiles */
        p->look_y = -1.0f;
        p->look_x = wav(t, 4.0f);
        p->arm_l = 30.0f * sit;
        emote(p, EMOTE_DOTS, t, 1.0f);
    }
    if (t > D - 4.0f) { /* hopeful look at you */
        p->lid = 0.0f;
        p->look_x = 0.0f;
        p->look_y = 0.0f;
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_SMILE;
        emote(p, mood_emote(mood, EMOTE_QUESTION, EMOTE_EXCLAIM, EMOTE_HEART), t, D - 4.0f);
    }
}

static void a_calendar(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_CALENDAR;
    p->arm_r = 62.0f * in;
    p->arm_l = 50.0f * in;
    p->look_x = 0.7f;
    p->look_y = 0.6f;
    p->yaw = 10.0f * in;
    p->held_t = floorf(t / 3.0f); /* a page flip every 3 s */
    p->head_dy = 1.5f * bump(fmodf(t, 3.0f), 0.0f, 0.4f);
    if (v == 1) {
        p->held_l = PROP_PENCIL;
        p->arm_l = (70.0f + 8.0f * wav(t, 0.4f)) * in;
    }
    if (t > D * 0.6f) { /* turns to the text and points: "let's do this" */
        float w = win(t, D * 0.6f, D - 0.6f, 0.6f);
        p->yaw = mixf(p->yaw, 65.0f, w);
        p->arm_l = mixf(p->arm_l, 100.0f, w);
        p->look_x = mixf(p->look_x, 1.0f, w);
        p->look_y = mixf(p->look_y, -0.2f, w);
        emote(p, mood_emote(mood, EMOTE_IDEA, EMOTE_EXCLAIM, EMOTE_SPARKLE), t, D * 0.6f);
    }
}

static void a_telescope(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_TELESCOPE;
    p->fp_x = s * 32.0f;
    p->fp_y = -4.0f;
    p->fp_t = (v == 0 ? -0.6f : (v == 1 ? 0.0f : 0.5f)) + 0.25f * wav(t, 5.0f); /* tube tilt */
    walk(p, t, 0.5f, 2.5f, 0.0f, s * 10.0f);
    walk(p, t, D - 2.5f, D - 0.5f, s * 10.0f, 0.0f);
    float look = win(t, 2.5f, D - 2.6f, 0.5f);
    p->yaw = mixf(p->yaw, 80.0f * s, look);
    p->lean = 4.0f * s * look;
    p->arm_r = mixf(p->arm_r, 75.0f, look);
    p->look_x = s * look;
    p->look_y = p->fp_t * look;
    if (t > D * 0.65f && t < D - 2.6f) {
        p->eyes = EYE_WIDE;
        p->yaw = mixf(p->yaw, 0.0f, seg(t, D * 0.65f, D * 0.65f + 0.5f));
        emote(p, mood_emote(mood, EMOTE_EXCLAIM, EMOTE_SPARKLE, EMOTE_QUESTION), t, D * 0.65f);
    }
}

static void a_dance(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 1.0f);
    float beat = t * (1.6f + 0.2f * (float)mood);
    p->x = s * 14.0f * sinf(beat * PI_F * 0.5f) * in;
    p->y = -4.0f * fabsf(sinf(beat * PI_F)) * in;
    p->arm_l = (90.0f + 70.0f * sinf(beat * PI_F)) * in;
    p->arm_r = (90.0f - 70.0f * sinf(beat * PI_F)) * in;
    p->leg_l = 4.0f * fmaxf2(0.0f, sinf(beat * PI_F)) * in;
    p->leg_r = 4.0f * fmaxf2(0.0f, -sinf(beat * PI_F)) * in;
    p->eyes = EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    p->antenna = 4.0f * sinf(beat * PI_F);
    if (v >= 2) p->held_l = PROP_HEADPHONES;
    float spin = seg(t, D * 0.5f, D * 0.5f + 1.2f);
    p->yaw = 360.0f * spin * s + (v == 1 ? 30.0f * sinf(beat * PI_F * 0.5f) : 0.0f);
    emote(p, EMOTE_MUSIC, t, 0.5f);
}

static void a_read(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float sit = win(t, 0.2f, D - 0.2f, 1.0f);
    p->sit = sit;
    p->held = PROP_BOOK;
    p->arm_l = 55.0f * sit;
    p->arm_r = 55.0f * sit;
    p->look_y = 0.8f;
    p->held_t = t * 0.35f; /* page turning */
    p->yaw = 12.0f * s * sit;
    if (v == 0) { /* giggles at a funny bit */
        float g = bump(fmodf(t, 9.0f), 5.0f, 7.0f);
        p->head_dy = -2.0f * fabsf(sinf(t * 14.0f)) * g;
        if (g > 0.1f) {
            p->eyes = EYE_HAPPY;
            p->mouth = MOUTH_GRIN;
            emote(p, mood_emote(mood, EMOTE_HEART, EMOTE_MUSIC, EMOTE_SPARKLE), t, 5.0f);
        }
    } else { /* dozes off over the book, startles awake */
        float doze = win(t, D * 0.35f, D * 0.7f, 1.5f);
        p->lid = doze;
        p->head_dy = 4.0f * doze;
        if (doze > 0.5f) emote(p, EMOTE_ZZZ, t, D * 0.35f);
        if (t > D * 0.7f && t < D * 0.7f + 1.5f) {
            p->eyes = EYE_WIDE;
            p->y = hop(t, D * 0.7f, D * 0.7f + 0.6f, 6.0f);
            emote(p, EMOTE_EXCLAIM, t, D * 0.7f);
        }
    }
}

static void a_coffee(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_MUG;
    p->held_t = t;
    float sip = bump(fmodf(t, 6.0f), 2.0f, 4.0f);
    p->arm_r = (55.0f + 85.0f * sip) * in;
    p->head_dy = -1.5f * sip;
    p->look_y = 0.3f;
    p->yaw = -10.0f * s * in;
    if (sip > 0.6f) {
        p->eyes = EYE_CLOSED;
        p->mouth = MOUTH_O;
    }
    if (v == 1 && t > 2.0f && t < 5.0f) { /* too hot! blows on it */
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_O;
        emote(p, EMOTE_SWEAT, t, 2.0f);
    } else if (sip <= 0.6f && t > 4.0f) {
        p->eyes = EYE_HAPPY;
        emote(p, mood_emote(mood, EMOTE_HEART, EMOTE_SPARKLE, EMOTE_MUSIC), t, 4.0f);
    }
}

static void a_plant(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_PLANT;
    p->fp_x = s * 36.0f;
    p->fp_y = 2.0f;
    p->fp_t = 0.5f + 2.5f * seg(t, D * 0.35f, D * 0.75f) + (float)v; /* leaves grow */
    walk(p, t, 0.6f, 2.6f, 0.0f, s * 8.0f);
    walk(p, t, D - 2.6f, D - 0.6f, s * 8.0f, 0.0f);
    float w = win(t, 2.6f, D - 2.6f, 0.6f);
    p->held = PROP_WATERCAN;
    p->yaw = mixf(p->yaw, 55.0f * s, w);
    float pour = win(t, 4.0f, D * 0.75f, 0.8f);
    p->arm_r = mixf(30.0f, 85.0f, w) + 10.0f * pour;
    p->held_t = pour; /* tilt + water drops */
    p->look_x = s * w;
    p->look_y = 0.7f * w;
    if (t > D * 0.75f) {
        p->eyes = EYE_HAPPY;
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_HEART, EMOTE_MUSIC), t, D * 0.75f);
    }
}

static void a_workout(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    float rate = 0.9f + 0.15f * (float)mood;
    float r = 0.5f - 0.5f * cosf(t * TAU_F * rate);
    p->eyes = EYE_ANGLED;
    p->mouth = MOUTH_FLAT;
    if (v == 0) { /* curls */
        p->held = PROP_DUMBBELL;
        p->held_l = PROP_DUMBBELL;
        p->arm_l = (30.0f + 120.0f * r) * in;
        p->arm_r = (30.0f + 120.0f * (1.0f - r)) * in;
    } else if (v == 1) { /* squats */
        p->sit = 0.55f * r * in;
        p->arm_l = 90.0f * in;
        p->arm_r = 90.0f * in;
    } else { /* jumping jacks */
        p->arm_l = (20.0f + 150.0f * r) * in;
        p->arm_r = (20.0f + 150.0f * r) * in;
        p->y = -5.0f * fabsf(sinf(t * TAU_F * rate)) * in;
        p->x = 0.0f;
    }
    if (t > D * 0.5f) emote(p, EMOTE_SWEAT, t, D * 0.5f);
    if (t > D - 2.5f) {
        p->eyes = EYE_HAPPY;
        p->mouth = MOUTH_GRIN;
        emote(p, EMOTE_SPARKLE, t, D - 2.5f);
    }
}

static void a_yoyo(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_YOYO;
    p->arm_r = (70.0f + 15.0f * wav(t, 1.1f)) * in;
    p->held_t = t * (1.0f + 0.2f * (float)mood); /* string length / spin */
    p->look_y = 0.7f;
    p->look_x = 0.5f;
    p->yaw = 15.0f * s * in;
    p->sign = v; /* 0 up-down, 1 around the world, 2 walk the dog */
    if (v == 1) p->arm_r = (110.0f + 30.0f * wav(t, 1.0f)) * in;
    p->mouth = MOUTH_GRIN;
    if (t > D - 3.0f) emote(p, EMOTE_SPARKLE, t, D - 3.0f);
}

static void a_plane(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float throw_t = 2.5f, catch_t = D - 3.0f;
    p->mouth = MOUTH_GRIN;
    if (t < throw_t) {
        p->held = PROP_PLANE;
        p->arm_r = 60.0f + 100.0f * seg(t, 0.5f, throw_t);
        p->yaw = 30.0f * s;
        p->look_y = -0.5f;
    } else if (t < catch_t) {
        float u = (t - throw_t) / (catch_t - throw_t);
        float loops = (float)(1 + v);
        float ang = u * TAU_F * loops;
        p->obj = PROP_PLANE;
        p->obj_t = ang * s; /* heading */
        p->obj_x = 50.0f + s * 110.0f * sinf(ang); /* loops across the room, over the board */
        p->obj_y = -110.0f + 40.0f * cosf(ang) - 20.0f * sinf(ang * 2.0f);
        /* PIP turns its whole body to follow the plane */
        p->yaw = 90.0f * s * sinf(ang) + (cosf(ang) < 0.0f ? 180.0f * (1.0f - fabsf(sinf(ang))) : 0.0f);
        p->look_y = -0.8f;
        p->look_x = sinf(ang) * 0.5f;
        p->arm_l = 40.0f;
        p->eyes = EYE_WIDE;
    } else {
        p->held = PROP_PLANE;
        p->arm_r = 120.0f * (1.0f - seg(t, catch_t + 1.0f, D - 0.4f));
        p->eyes = EYE_HAPPY;
        p->y = hop(t, catch_t, catch_t + 0.7f, 8.0f);
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_HEART, EMOTE_EXCLAIM), t, catch_t);
    }
}

static void a_blocks(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_BLOCKS;
    p->fp_x = s * 34.0f;
    p->fp_y = 4.0f;
    float build_end = D * 0.62f;
    float n = floorf(1.0f + 4.0f * seg(t, 1.0f, build_end));
    p->fp_t = n; /* blocks stacked */
    p->yaw = 50.0f * s;
    p->x = s * 6.0f;
    float place = fabsf(sinf(t * PI_F * 0.9f));
    p->arm_r = 60.0f + 50.0f * place * (t < build_end ? 1.0f : 0.0f);
    p->look_x = s;
    p->look_y = 0.3f - 0.15f * n;
    if (t > build_end && t < build_end + 1.6f) p->fp_t = n + 0.5f + 0.4f * wav(t, 0.4f) * 0.5f; /* wobble */
    if (t >= build_end + 1.6f) { /* timber! */
        p->fp_t = v == 0 ? 10.0f : n; /* variant 1: it holds */
        p->eyes = v == 0 ? EYE_WIDE : EYE_HAPPY;
        p->mouth = v == 0 ? MOUTH_O : MOUTH_GRIN;
        p->y = hop(t, build_end + 1.6f, build_end + 2.3f, 7.0f);
        emote(p, v == 0 ? EMOTE_SWEAT : mood_emote(mood, EMOTE_SPARKLE, EMOTE_HEART, EMOTE_EXCLAIM), t,
              build_end + 1.6f);
    }
    p->x *= win(t, 0.0f, D, 0.8f);
    p->yaw *= win(t, 0.0f, D, 0.8f);
}

static void a_balloon(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    float lift = win(t, D * 0.3f, D * 0.75f, 2.0f) * (v == 0 ? 1.0f : 0.5f);
    p->held = PROP_BALLOON;
    p->arm_r = (165.0f - 5.0f * wav(t, 2.0f)) * in;
    p->obj = PROP_BALLOON;
    p->y = -46.0f * lift + 2.0f * wav(t, 2.2f) * lift;
    p->x = s * 10.0f * wav(t, 7.0f) * lift;
    p->leg_l = 4.0f * lift;
    p->leg_r = 2.0f * lift;
    p->look_y = -0.7f;
    p->eyes = lift > 0.3f ? EYE_WIDE : EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    p->obj_t = t;
    if (lift > 0.3f) emote(p, mood_emote(mood, EMOTE_EXCLAIM, EMOTE_MUSIC, EMOTE_SPARKLE), t, D * 0.3f);
}

static void a_juggle(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_BALL;
    p->held_l = PROP_BALL; /* both hands hold balls -> the renderer draws a 3-ball cascade */
    p->held_t = t * (1.1f + 0.25f * (float)v);
    float hand = sinf(p->held_t * TAU_F);
    p->arm_l = (60.0f + 15.0f * hand) * in;
    p->arm_r = (60.0f - 15.0f * hand) * in;
    p->look_y = -0.6f;
    p->eyes = EYE_ANGLED;
    if (t > D * 0.5f) {
        p->eyes = EYE_HAPPY;
        p->mouth = MOUTH_GRIN;
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_MUSIC, EMOTE_HEART), t, D * 0.5f);
    }
}

static void a_spin(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float sp1 = seg(t, 1.0f, 2.6f), sp2 = seg(t, 4.0f, 6.0f);
    p->yaw = s * (360.0f * sp1 - (v == 1 ? 720.0f : 360.0f) * sp2);
    p->y = hop(t, 1.0f, 2.6f, 10.0f) + hop(t, 4.0f, 6.0f, 6.0f);
    p->arm_l = 90.0f * (bump(t, 1.0f, 2.6f) + bump(t, 4.0f, 6.0f));
    p->arm_r = p->arm_l;
    if (t > 6.5f) {
        float w = win(t, 6.5f, D - 0.5f, 0.6f);
        p->arm_r = (150.0f + 20.0f * wav(t, 0.55f)) * w;
        p->eyes = EYE_HAPPY;
        p->mouth = MOUTH_GRIN;
        emote(p, mood_emote(mood, EMOTE_HEART, EMOTE_SPARKLE, EMOTE_MUSIC), t, 6.5f);
    }
}

static void a_hide(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* sneaks out through the left edge of the screen, peeks back in, scampers home */
    const float off = PIP_WORLD_L - PIP_OFFSCREEN;
    walk(p, t, 0.5f, 3.5f, 0.0f, off);
    if (t >= 3.5f && t < D * 0.55f) {
        p->x = off;
    }
    if (t >= D * 0.55f) {
        float peek = win(t, D * 0.55f, D * 0.8f, 1.0f);
        p->x = off + 50.0f * peek;
        p->yaw = 60.0f;
        p->lean = 8.0f * peek;
        p->look_x = 0.0f;
        p->eyes = EYE_WIDE;
        if (peek > 0.5f) emote(p, v == 0 ? EMOTE_QUESTION : EMOTE_EXCLAIM, t, D * 0.6f);
        if (t >= D * 0.8f) {
            walk(p, t, D * 0.8f, D - 0.5f, off + 50.0f * peek, 0.0f);
            p->mouth = MOUTH_GRIN;
        }
    }
    (void)s;
    (void)mood;
}

static void a_stretch(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float up = win(t, 0.5f, D * 0.55f, 1.2f);
    p->arm_l = 170.0f * up;
    p->arm_r = 170.0f * up;
    p->y = -3.0f * up;
    p->lean = 6.0f * wav(t, 3.0f) * up * (v == 1 ? 1.4f : 1.0f);
    p->eyes = EYE_CLOSED;
    float yawn = bump(t, D * 0.2f, D * 0.45f);
    p->mouth = yawn > 0.3f ? MOUTH_O : MOUTH_SMILE;
    if (yawn > 0.3f) emote(p, EMOTE_ZZZ, t, D * 0.2f);
    if (t > D * 0.6f) { /* shake it off */
        float sh = win(t, D * 0.6f, D * 0.85f, 0.3f);
        p->lean = 4.0f * sinf(t * 30.0f) * sh;
        p->antenna = 5.0f * sinf(t * 30.0f) * sh;
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_GRIN;
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_EXCLAIM, EMOTE_MUSIC), t, D * 0.6f);
    }
}

static void a_guitar(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_GUITAR;
    p->held_t = t;
    p->arm_l = 75.0f * in;
    p->arm_r = (40.0f + 18.0f * fabsf(sinf(t * PI_F * (2.0f + (float)mood)))) * in;
    p->head_dy = 1.5f * fabsf(sinf(t * PI_F * 2.0f));
    p->leg_r = 3.0f * fmaxf2(0.0f, sinf(t * PI_F * 2.0f));
    p->eyes = v == 0 ? EYE_CLOSED : EYE_HAPPY;
    p->mouth = MOUTH_O;
    p->yaw = 15.0f * s * in;
    if (v == 1) p->sit = in;
    emote(p, EMOTE_MUSIC, t, 0.8f);
}

static void a_sweep(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_BROOM;
    float sw = sinf(t * TAU_F * 0.8f);
    p->x = s * 18.0f * sinf(t * TAU_F / D) * in;
    p->arm_r = (40.0f + 25.0f * sw) * in;
    p->arm_l = (55.0f + 20.0f * sw) * in;
    p->lean = 3.0f * sw * in;
    p->yaw = 35.0f * s * in;
    p->held_t = sw;
    p->look_y = 0.9f;
    p->mouth = v == 0 ? MOUTH_WAVY : MOUTH_SMILE;
    if (t > D * 0.4f && t < D * 0.6f) emote(p, EMOTE_SPARKLE, t, D * 0.4f);
    if (v == 1) emote(p, EMOTE_MUSIC, t, 1.0f);
}

static void a_kite(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 1.0f);
    p->held = PROP_KITE;
    p->obj = PROP_KITE;
    p->obj_t = t;
    float rise = seg(t, 0.5f, 5.0f);
    p->obj_x = s * (20.0f + 30.0f * sinf(t * 0.7f + (float)v)) * in;
    p->obj_y = (-60.0f - 100.0f * rise + 12.0f * sinf(t * 1.3f)) * in;
    p->arm_r = (110.0f + 30.0f * rise + 8.0f * wav(t, 1.7f)) * in;
    walk(p, t, 0.6f, 3.0f, 0.0f, -s * 16.0f);
    walk(p, t, D - 3.0f, D - 0.6f, -s * 16.0f, 0.0f);
    if (t > 3.0f && t < D - 3.0f) p->yaw = 30.0f * s;
    p->look_y = -1.0f;
    p->look_x = 0.4f * s;
    p->mouth = MOUTH_GRIN;
    if (t > D * 0.5f) emote(p, mood_emote(mood, EMOTE_MUSIC, EMOTE_SPARKLE, EMOTE_HEART), t, D * 0.5f);
}

static void a_clock(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_CLOCK;
    p->held_t = t;
    p->arm_r = 65.0f * in;
    p->look_x = 0.6f;
    p->look_y = 0.5f;
    if (v == 0) { /* taps it, shakes it */
        p->arm_l = (70.0f + 14.0f * fabsf(sinf(t * PI_F * 2.0f))) * in;
        p->lean = 2.0f * sinf(t * 20.0f) * bump(t, 3.0f, 4.5f);
    } else { /* listens to it tick */
        p->lean = 6.0f * in;
        p->arm_r = 120.0f * in;
        p->eyes = EYE_CLOSED;
        emote(p, EMOTE_SOUND, t, 1.0f);
    }
    if (t > D * 0.55f) { /* "it's focus time" - points at the text */
        float w = win(t, D * 0.55f, D - 0.5f, 0.6f);
        p->eyes = EYE_WIDE;
        p->yaw = 60.0f * w;
        p->arm_l = mixf(p->arm_l, 100.0f, w);
        p->look_x = mixf(p->look_x, 1.0f, w);
        emote(p, mood_emote(mood, EMOTE_QUESTION, EMOTE_EXCLAIM, EMOTE_FOCUS), t, D * 0.55f);
    }
}

static void a_sign(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    float up = win(t, 1.0f, D - 1.0f, 1.0f);
    p->held = PROP_SIGN;
    p->sign = v + 4 * mood;
    p->arm_r = (60.0f + 105.0f * up) * in;
    p->arm_l = (40.0f + 30.0f * up) * in;
    p->y = -4.0f * fabsf(sinf(t * PI_F * 1.4f)) * up;
    p->eyes = EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    p->yaw = 10.0f * s * wav(t, 2.5f);
    p->antenna = 3.0f * sinf(t * 6.0f); /* the sign is the message: no emote competing with it */
}

static void a_idea(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float think_end = D * 0.6f;
    if (t < think_end) {
        float u = t / think_end;
        p->x = s * 22.0f * sinf(u * TAU_F * (v == 0 ? 1.0f : 1.5f));
        float vx = cosf(u * TAU_F * (v == 0 ? 1.0f : 1.5f));
        p->yaw = (vx >= 0.0f ? 72.0f : -72.0f) * s * fminf2(1.0f, fabsf(vx) * 3.0f);
        steps(p, t, fminf2(1.0f, fabsf(vx) * 2.0f), 1.6f);
        p->arm_r = 150.0f; /* hand on chin/head */
        p->look_y = -0.6f;
        emote(p, EMOTE_DOTS, t, 0.5f);
    } else {
        p->x = 0.0f;
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_GRIN;
        p->arm_r = 175.0f * win(t, think_end, D - 0.4f, 0.4f);
        p->y = hop(t, think_end + 0.3f, think_end + 1.0f, 12.0f);
        emote(p, EMOTE_IDEA, t, think_end);
    }
}

static void a_laptop(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float sit = win(t, 0.2f, D - 0.2f, 1.0f);
    p->sit = sit;
    p->floor_prop = PROP_LAPTOP;
    p->fp_x = s * 6.0f;
    p->fp_y = 18.0f;
    p->fp_t = t;
    float typing = sinf(t * 22.0f);
    p->arm_l = (58.0f + 6.0f * typing) * sit;
    p->arm_r = (58.0f - 6.0f * typing) * sit;
    p->look_y = 0.9f;
    float glance = bump(fmodf(t, 7.0f), 5.0f, 6.6f); /* glances up at you */
    p->look_y = mixf(p->look_y, 0.0f, glance);
    if (glance > 0.5f) p->eyes = v == 0 ? EYE_HAPPY : EYE_WIDE;
    emote(p, mood_emote(mood, EMOTE_FOCUS, EMOTE_IDEA, EMOTE_MUSIC), t, 1.0f);
}

static void a_umbrella(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->held = PROP_UMBRELLA;
    p->held_t = t * (v == 1 ? 1.6f : 0.6f); /* twirl + rain phase */
    p->arm_r = 150.0f * in;
    p->look_y = -0.8f;
    p->mouth = MOUTH_GRIN;
    p->eyes = EYE_HAPPY;
    float splash = fmodf(t, 4.0f);
    p->y = hop(splash, 2.4f, 3.0f, 7.0f) * in;
    p->x = s * 10.0f * wav(t, 8.0f) * in;
    emote(p, EMOTE_MUSIC, t, 1.0f);
}

static void a_peekaboo(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float cyc = fmodf(t, 4.0f);
    float hide = win(cyc, 0.3f, 2.6f, 0.4f) * win(t, 0.0f, D - 1.0f, 0.5f);
    p->arm_l = 150.0f * hide + 100.0f * bump(cyc, 2.6f, 3.6f);
    p->arm_r = p->arm_l;
    p->lid = hide;
    p->head_dy = 2.0f * hide;
    if (cyc > 2.6f && cyc < 3.6f) {
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_GRIN;
        p->y = hop(cyc, 2.6f, 3.2f, 6.0f);
        emote(p, mood_emote(mood, EMOTE_EXCLAIM, EMOTE_SPARKLE, EMOTE_HEART), cyc, 2.6f);
    }
}

static void a_gift(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_GIFT;
    p->fp_x = s * 40.0f;
    p->fp_y = 6.0f;
    p->fp_t = seg(t, D * 0.55f, D * 0.6f); /* 0 closed .. 1 lid off */
    walk(p, t, 0.5f, 2.2f, 0.0f, s * 6.0f);
    p->yaw = mixf(p->yaw, 50.0f * s, win(t, 2.2f, D - 0.6f, 0.4f));
    float shake = bump(t, 3.0f, D * 0.5f);
    p->arm_r = 75.0f + 10.0f * sinf(t * 25.0f) * shake;
    p->look_x = s;
    p->look_y = 0.5f;
    if (shake > 0.2f) emote(p, EMOTE_QUESTION, t, 3.0f);
    if (t > D * 0.6f) {
        p->eyes = EYE_STAR;
        p->mouth = MOUTH_GRIN;
        p->y = hop(t, D * 0.6f, D * 0.6f + 0.7f, 10.0f);
        p->arm_l = 160.0f * win(t, D * 0.6f, D - 0.5f, 0.4f);
        p->arm_r = p->arm_l;
        emote(p, v == 0 ? EMOTE_HEART : EMOTE_SPARKLE, t, D * 0.6f);
    }
}

/* ---- idle world: the message board and the whole room ---------------------------------------- */
/* head centre right at the board's left edge: half of PIP's face shows */
#define PEEK_X (PIP_BOARD_DX + 10.0f)

static void a_behind(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* strolls behind the board (only its legs show underneath), then peeks out from its edge */
    p->behind = 1;
    float far = 150.0f + 40.0f * (float)v;
    walk(p, t, 0.5f, 4.5f, 0.0f, far);
    float back0 = D * 0.38f, peek0 = back0 + 3.0f, peek1 = D - 4.0f;
    if (t > 4.5f && t <= back0) { /* waiting behind the board, tapping a foot */
        p->leg_r = 3.0f * fmaxf2(0.0f, sinf(t * PI_F * 2.4f));
        p->yaw = -20.0f;
    }
    if (t > back0) {
        walk(p, t, back0, peek0, far, PEEK_X);
    }
    if (t > peek0 && t <= peek1) {
        float w = win(t, peek0, peek1, 0.6f);
        float bob = v == 1 ? 6.0f * bump(fmodf(t - peek0, 2.6f), 0.4f, 2.2f) : 3.0f * wav(t, 2.0f);
        p->x = PEEK_X;
        p->lean = (-10.0f - bob) * w;
        p->yaw = -35.0f * w;
        p->look_x = -0.3f * w;
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_GRIN;
        emote(p, v == 0 ? mood_emote(mood, EMOTE_EXCLAIM, EMOTE_QUESTION, EMOTE_HEART) : EMOTE_QUESTION, t, peek0 + 0.4f);
    }
    if (t > peek1) {
        walk(p, t, peek1, D - 0.5f, PEEK_X, 0.0f);
        p->mouth = MOUTH_GRIN;
    }
    (void)s;
}

static void a_lean(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* walks over and leans on the board like it owns the place */
    const float at = PIP_BOARD_DX - 30.0f;
    walk(p, t, 0.5f, 3.0f, 0.0f, at);
    walk(p, t, D - 3.0f, D - 0.5f, at, 0.0f);
    float w = win(t, 3.0f, D - 3.0f, 0.7f);
    p->lean = mixf(p->lean, 6.0f, w);
    p->arm_r = mixf(p->arm_r, 112.0f, w); /* elbow on the board */
    p->arm_l = mixf(p->arm_l, 25.0f, w);
    p->leg_l = mixf(p->leg_l, 3.0f * fmaxf2(0.0f, sinf(t * PI_F * 1.6f)), w);
    p->yaw = mixf(p->yaw, -15.0f, w);
    p->eyes = w > 0.5f ? EYE_HAPPY : p->eyes;
    p->mouth = MOUTH_SMILE;
    if (w > 0.5f) emote(p, EMOTE_MUSIC, t, 3.5f); /* whistling */
    float look0 = D * 0.5f;
    float lk = win(t, look0, D - 3.5f, 0.6f);
    if (lk > 0.0f) { /* reads the board, then nods at you */
        p->yaw = mixf(p->yaw, 50.0f, lk);
        p->look_x = mixf(p->look_x, 1.0f, lk);
        p->look_y = mixf(p->look_y, -0.8f, lk);
        p->eyes = EYE_PILL;
        emote(p, v == 0 ? EMOTE_IDEA : mood_emote(mood, EMOTE_EXCLAIM, EMOTE_SPARKLE, EMOTE_HEART), t, look0);
    }
    (void)s;
}

static void a_present(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* presenter: points at the headline, then turns to you, ta-da */
    const float at = 28.0f;
    walk(p, t, 0.4f, 2.4f, 0.0f, at);
    walk(p, t, D - 2.4f, D - 0.4f, at, 0.0f);
    float pt = win(t, 2.4f, D * 0.55f, 0.5f);
    p->yaw = mixf(p->yaw, 70.0f, pt);
    p->arm_l = mixf(p->arm_l, 150.0f + 8.0f * wav(t, 0.8f), pt); /* the near arm in profile */
    p->look_x = mixf(p->look_x, 1.0f, pt);
    p->look_y = mixf(p->look_y, -1.0f, pt);
    p->y += hop(t, 3.0f, 3.5f, 6.0f);
    if (pt > 0.5f) emote(p, EMOTE_EXCLAIM, t, 2.8f);
    float tada = win(t, D * 0.55f, D - 2.4f, 0.5f);
    if (tada > 0.0f) {
        p->yaw = mixf(p->yaw, 0.0f, tada);
        p->look_x = mixf(p->look_x, 0.0f, tada);
        p->look_y = mixf(p->look_y, 0.0f, tada);
        p->arm_l = mixf(p->arm_l, v == 0 ? 125.0f : 165.0f, tada);
        p->arm_r = mixf(p->arm_r, v == 0 ? 125.0f : 165.0f, tada);
        p->y += hop(t, D * 0.55f + 0.3f, D * 0.55f + 0.9f, 8.0f);
        p->eyes = EYE_HAPPY;
        p->mouth = MOUTH_GRIN;
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_HEART, EMOTE_SPARKLE), t, D * 0.55f);
    }
    (void)s;
}

static void a_kick(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* kicks a ball all the way across the room: under the board, off the far wall and back */
    const float b0 = 22.0f, wall = PIP_WORLD_R - 8.0f, stop = 30.0f;
    const float k0 = 2.2f, hit = 4.4f, back = D - 3.6f;
    float bx = b0;
    if (t > k0 && t <= hit) {
        float u = (t - k0) / (hit - k0);
        bx = b0 + (wall - b0) * u * (1.3f - 0.3f * u); /* fast, easing a little */
    } else if (t > hit && t <= back) {
        float u = (t - hit) / (back - hit);
        bx = wall + (stop - wall) * (1.0f - (1.0f - u) * (1.0f - u));
    } else if (t > back) {
        bx = stop;
    }
    float hb = 0.0f;
    if (v == 1 && t > k0 && t < back) { /* bouncy ball: hops that die down */
        hb = fabsf(sinf((t - k0) * PI_F * 1.4f)) * 26.0f * (1.0f - (t - k0) / (back - k0));
    }
    p->obj = PROP_BALL;
    p->obj_x = bx;
    p->obj_y = -7.0f - hb;
    p->obj_t = bx / 21.0f; /* rolls */
    /* PIP: lines up, kicks, watches it go and come back, traps it */
    p->yaw = 60.0f * win(t, 0.3f, D - 1.0f, 0.5f);
    p->x = 4.0f * seg(t, 0.6f, 1.6f) * (1.0f - seg(t, D - 1.6f, D - 0.6f));
    p->leg_r = 7.0f * bump(t, k0 - 0.35f, k0 + 0.15f) + 6.0f * bump(t, back - 0.3f, back + 0.4f);
    p->arm_l = 40.0f * bump(t, k0 - 0.4f, k0 + 0.4f);
    p->look_x = fminf2(1.0f, (bx - p->x) / 120.0f);
    p->look_y = 0.6f;
    p->mouth = MOUTH_GRIN;
    if (t > hit - 0.2f && t < hit + 1.2f) {
        p->eyes = EYE_WIDE;
        p->mouth = MOUTH_O;
        p->y += hop(t, hit - 0.1f, hit + 0.4f, 6.0f);
        emote(p, EMOTE_EXCLAIM, t, hit - 0.2f);
    }
    if (t > back) {
        p->eyes = EYE_HAPPY;
        emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_MUSIC, EMOTE_HEART), t, back);
    }
    if (t > D - 1.0f) { /* it stays where PIP trapped it */
        p->obj = PROP_NONE;
        p->floor_prop = PROP_BALL;
        p->fp_x = stop;
        p->fp_y = 0.0f;
    }
    (void)s;
}

static void a_lap(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    /* runs off behind the board on the right... and comes back in from the left */
    const float out_r = PIP_WORLD_R + PIP_OFFSCREEN, in_l = PIP_WORLD_L - PIP_OFFSCREEN;
    float gone = D * 0.42f, back = D * 0.5f;
    if (t < gone) {
        p->behind = 1;
        walk(p, t, 0.5f, gone, 0.0f, out_r);
        if (v == 1 && t > 1.0f) emote(p, EMOTE_MUSIC, t, 1.0f);
    } else if (t < back) {
        p->behind = 1;
        p->x = out_r;
    } else {
        p->behind = 0; /* switched while off-screen: no pop */
        walk(p, t, back, D - 1.6f, in_l, 0.0f);
        if (t > back + 0.6f) {
            p->eyes = EYE_HAPPY;
            p->mouth = MOUTH_GRIN;
            emote(p, mood_emote(mood, EMOTE_SPARKLE, EMOTE_HEART, EMOTE_MUSIC), t, back + 0.6f);
        }
        float wave = win(t, D - 1.6f, D - 0.2f, 0.3f);
        p->arm_r = mixf(p->arm_r, 150.0f + 20.0f * wav(t, 0.5f), wave);
    }
    (void)s;
}

/* ==== FOCUS (timer running): keep catching your eye ========================================== */
static void f_type(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_laptop(p, t, D, v, s, 0);
    p->emote = EMOTE_FOCUS;
}

static void f_point(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float w = win(t, 0.5f, D - 0.5f, 0.8f);
    p->yaw = 70.0f * w;
    p->arm_r = (140.0f + 10.0f * wav(t, 1.2f)) * w;
    p->look_x = w;
    p->look_y = -0.5f * w;
    p->eyes = EYE_WIDE;
    if (t > D * 0.5f) { /* turns back to you: thumbs up */
        float b = win(t, D * 0.5f, D - 0.5f, 0.6f);
        p->yaw = mixf(p->yaw, 0.0f, b);
        p->look_x = mixf(p->look_x, 0.0f, b);
        p->eyes = EYE_HAPPY;
        p->mouth = MOUTH_GRIN;
        emote(p, EMOTE_SPARKLE, t, D * 0.5f);
    } else {
        emote(p, EMOTE_FOCUS, t, 0.5f);
    }
}

static void f_peek(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_LAPTOP;
    p->fp_x = 0.0f;
    p->fp_y = 18.0f;
    p->fp_t = t;
    float rise = win(t, D * 0.3f, D * 0.8f, 1.5f);
    p->sit = 1.0f - rise;
    p->y = 10.0f * (1.0f - rise);
    p->look_y = mixf(0.9f, 0.0f, rise);
    p->eyes = rise > 0.5f ? EYE_WIDE : EYE_PILL;
    p->arm_r = (150.0f + 20.0f * wav(t, 0.5f)) * bump(t, D * 0.45f, D * 0.75f) + 55.0f * (1.0f - rise);
    p->arm_l = 55.0f * (1.0f - rise);
    if (rise > 0.6f) emote(p, mood_emote(mood, EMOTE_HEART, EMOTE_EXCLAIM, EMOTE_SPARKLE), t, D * 0.45f);
}

static void f_cheer(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    float b = fabsf(sinf(t * PI_F * 1.8f));
    p->y = -8.0f * b * in;
    p->arm_l = (120.0f + 50.0f * sinf(t * PI_F * 1.8f)) * in;
    p->arm_r = (120.0f - 50.0f * sinf(t * PI_F * 1.8f)) * in;
    p->eyes = EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    p->antenna = 4.0f * sinf(t * PI_F * 1.8f);
    emote(p, EMOTE_SPARKLE, t, 0.3f);
}

static void f_sign(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_sign(p, t, D, v, s, 0);
    p->sign = 12 + v; /* focus messages */
}

static void f_watch(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.8f);
    p->lean = -4.0f * in;
    p->arm_l = 20.0f * in;
    p->arm_r = 150.0f * in; /* hand on hip/head */
    p->look_x = 0.8f + 0.2f * wav(t, 4.0f);
    p->look_y = -0.4f;
    p->leg_r = 3.0f * fmaxf2(0.0f, sinf(t * PI_F * 2.0f)) * in; /* foot tapping */
    p->yaw = 30.0f * in;
    emote(p, EMOTE_FOCUS, t, 0.5f);
    if (fmodf(t, 8.0f) > 6.0f) { /* checks on you */
        p->yaw = 0.0f;
        p->look_x = 0.0f;
        p->eyes = EYE_HAPPY;
    }
}

static void f_write(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_calendar(p, t, D, 1, s, 0);
    p->emote = EMOTE_NONE;
    if (t > D * 0.6f) emote(p, EMOTE_SPARKLE, t, D * 0.6f);
}

static void f_knock(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_knock(p, t, D, v == 0 ? 0 : 1, s, 1);
    p->scale = 1.0f + (p->scale - 1.0f) * 0.6f;
    p->y *= 0.6f;
}

/* ==== listening / thinking ================================================================== */
static void l_ear(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    p->lean = 5.0f * s * in;
    p->yaw = 25.0f * s * in;
    if (s > 0) p->arm_l = 160.0f * in; else p->arm_r = 160.0f * in;
    p->head_dy = 1.5f * sinf(t * PI_F * 1.5f) * (v == 1 ? 1.0f : 0.3f); /* nodding along */
    p->eyes = EYE_WIDE;
    p->mouth = MOUTH_O;
    p->antenna = 3.0f * sinf(t * 9.0f);
    emote(p, EMOTE_SOUND, t, 0.0f);
}

static void l_notes(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    p->held = PROP_BOOK;
    p->held_l = PROP_PENCIL;
    p->arm_r = 60.0f * in;
    p->arm_l = (70.0f + 8.0f * sinf(t * 18.0f)) * in;
    p->look_y = 0.7f;
    p->look_x = 0.3f;
    p->head_dy = 1.0f * bump(fmodf(t, 2.0f), 0.0f, 0.5f);
    emote(p, EMOTE_SOUND, t, 0.0f);
}

static void t_pace(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_idea(p, t, D * 1.6f, v, s, mood); /* pacing part only */
    if (p->emote == EMOTE_DOTS && v == 1) p->emote = EMOTE_QUESTION;
}

static void t_scratch(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    p->arm_r = (160.0f + 10.0f * sinf(t * 16.0f)) * in;
    p->lean = 3.0f * in;
    p->look_y = -0.8f;
    p->look_x = 0.5f * wav(t, 3.0f);
    p->mouth = MOUTH_WAVY;
    emote(p, v == 0 ? EMOTE_DOTS : EMOTE_QUESTION, t, 0.3f);
    if (t > D * 0.75f) {
        p->eyes = EYE_WIDE;
        p->arm_r = 175.0f;
        emote(p, EMOTE_IDEA, t, D * 0.75f);
    }
}

static void t_flip(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    p->held = PROP_BOOK;
    p->held_t = t * 2.5f; /* furious page flipping */
    p->arm_l = 55.0f * in;
    p->arm_r = (55.0f + 10.0f * sinf(t * 15.0f)) * in;
    p->look_y = 0.8f;
    p->eyes = EYE_ANGLED;
    emote(p, EMOTE_DOTS, t, 0.2f);
}

/* ==== break / done / pause ================================================================== */
static void d_celebrate(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.5f);
    float j = fabsf(sinf(t * PI_F * 1.4f));
    p->y = -14.0f * j * in;
    p->arm_l = (150.0f + 25.0f * j) * in;
    p->arm_r = p->arm_l;
    p->leg_l = 5.0f * j;
    p->leg_r = 5.0f * j;
    p->eyes = v == 0 ? EYE_STAR : EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    p->yaw = v == 1 ? 360.0f * seg(fmodf(t, 3.0f), 0.5f, 1.6f) : 0.0f;
    emote(p, EMOTE_SPARKLE, t, 0.0f);
}

static void d_highfive(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_knock(p, t, D, 1, s, 2);
    p->eyes = EYE_HAPPY;
    p->mouth = MOUTH_GRIN;
    if (p->emote == EMOTE_KNOCK) p->emote = EMOTE_SPARKLE;
}

static void r_relax(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float sit = win(t, 0.3f, D - 0.3f, 1.2f);
    p->sit = sit;
    p->arm_l = 150.0f * sit; /* hands behind the head */
    p->arm_r = 150.0f * sit;
    p->eyes = EYE_CLOSED;
    p->mouth = MOUTH_SMILE;
    p->head_dy = 1.0f * wav(t, 4.0f);
    emote(p, v == 0 ? EMOTE_MUSIC : EMOTE_HEART, t, 1.0f);
}

/* ==== calendar / alarm / confirm / sleep / error ============================================= */
static void c_point(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    a_calendar(p, t, D, v, s, mood);
    if (t > D * 0.5f) {
        p->held_t = 0.0f;
    }
}

static void al_ring(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->floor_prop = PROP_CLOCK;
    p->fp_x = s * 36.0f;
    p->fp_y = 6.0f;
    p->fp_t = t; /* rattling bells */
    float j = fabsf(sinf(t * PI_F * 2.2f));
    p->y = -10.0f * j;
    p->arm_l = 160.0f + 15.0f * sinf(t * 14.0f);
    p->arm_r = 160.0f - 15.0f * sinf(t * 14.0f);
    p->lean = 2.5f * sinf(t * 30.0f);
    p->eyes = EYE_WIDE;
    p->mouth = MOUTH_O;
    p->antenna = 5.0f * sinf(t * 30.0f);
    emote(p, EMOTE_ALARM, t, 0.0f);
}

static void al_wake(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->held = PROP_CLOCK;
    p->held_t = t;
    p->arm_r = 165.0f;
    p->arm_l = 120.0f + 30.0f * sinf(t * 10.0f);
    p->y = -6.0f * fabsf(sinf(t * PI_F * 2.0f));
    p->eyes = EYE_WIDE;
    p->mouth = MOUTH_GRIN;
    emote(p, EMOTE_EXCLAIM, t, 0.0f);
}

static void q_tilt(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    if (v == 0) {
        p->held = PROP_CLOCK;
        p->held_t = t;
        p->arm_r = 65.0f * in;
    } else {
        p->arm_r = 150.0f * in;
    }
    p->lean = 5.0f * s * sinf(t * 0.9f) * in;
    p->look_x = 0.5f * s;
    p->look_y = -0.3f;
    p->eyes = EYE_WIDE;
    emote(p, EMOTE_QUESTION, t, 0.3f);
}

static void z_sit(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    p->sit = 1.0f;
    p->eyes = EYE_CLOSED;
    p->mouth = v == 1 ? MOUTH_O : MOUTH_SMILE;
    p->head_dy = 3.0f + 1.5f * wav(t, 3.6f);
    p->lean = (v == 2 ? 5.0f : 2.0f) * s + 1.0f * wav(t, 7.0f);
    p->arm_l = 20.0f;
    p->arm_r = 20.0f;
    if (v == 2) p->held_l = PROP_HEADPHONES;
    emote(p, EMOTE_ZZZ, t, 0.0f);
}

static void e_fix(mascot_pose_t *p, float t, float D, int v, float s, int mood)
{
    float in = win(t, 0.0f, D, 0.6f);
    if (v == 0) {
        p->held = PROP_WRENCH;
        p->held_t = t;
        p->arm_r = (70.0f + 30.0f * sinf(t * 6.0f)) * in;
        p->look_y = 0.6f;
        p->look_x = 0.6f;
    } else {
        p->arm_r = (160.0f + 10.0f * sinf(t * 16.0f)) * in;
        p->look_y = -0.7f;
    }
    p->eyes = EYE_ANGLED;
    p->mouth = MOUTH_WAVY;
    emote(p, EMOTE_SWEAT, t, 0.0f);
}

/* ==== prop trips: props come from (and go back to) the edge of the screen =====================
 * Between two performances whose props differ, PIP picks up anything lying on the floor, carries everything
 * off the nearest screen edge, swaps it off-screen and walks back in with the next act's props, setting floor
 * props down where the act expects them. Nothing ever pops into or out of existence. */
#define TRIP_V 110.0f     /* px/s walking pace */
#define TRIP_READY 0.35f  /* turn toward the way out */
#define TRIP_LIFT 0.55f   /* crouch + pick up / set down */
#define TRIP_SWAP 0.45f   /* off-screen: drop one thing, grab the next */
#define CARRY_DX 18.0f    /* a carried floor prop sits this far in front */
#define CARRY_LIFT 20.0f

typedef struct {
    int held, held_l, fp, obj;
} kit_t;

/* what PIP has to carry: flying things are carried in a free hand, a balloon keeps floating on its string */
static void kit_of(const mascot_pose_t *p, kit_t *k)
{
    k->held = p->held;
    k->held_l = p->held_l;
    k->fp = p->floor_prop;
    k->obj = PROP_NONE;
    if (p->obj == PROP_BALLOON) {
        k->obj = PROP_BALLOON;
    } else if (p->obj != PROP_NONE && p->obj != p->held && p->obj != p->held_l) {
        if (k->held == PROP_NONE) {
            k->held = p->obj;
        } else if (k->held_l == PROP_NONE) {
            k->held_l = p->obj;
        }
    }
}

bool mascot_same_props(const mascot_pose_t *a, const mascot_pose_t *b)
{
    kit_t ka, kb;
    kit_of(a, &ka);
    kit_of(b, &kb);
    if (ka.held != kb.held || ka.held_l != kb.held_l || ka.fp != kb.fp || ka.obj != kb.obj) {
        return false;
    }
    return ka.fp == PROP_NONE || (fabsf(a->fp_x - b->fp_x) <= 10.0f && fabsf(a->fp_y - b->fp_y) <= 6.0f);
}

typedef struct {
    bool walk_only;   /* same props, just far from where the next act starts: walk there */
    float side;       /* -1: out through the left edge, +1: the right one (only from far right in the room) */
    float edge;       /* off-screen x */
    float a, b;       /* pick-up spot / set-down spot */
    float c[9];       /* phase end times */
} trip_plan_t;

static void trip_plan(const mascot_pose_t *f, const mascot_pose_t *to, trip_plan_t *tp)
{
    tp->walk_only = mascot_same_props(f, to);
    bool pick = !tp->walk_only && f->floor_prop != PROP_NONE, drop = !tp->walk_only && to->floor_prop != PROP_NONE;
    float start = pick ? f->fp_x : f->x;
    tp->side = start > PIP_BOARD_DX ? 1.0f : -1.0f;
    tp->edge = tp->side > 0.0f ? PIP_WORLD_R + PIP_OFFSCREEN : PIP_WORLD_L - PIP_OFFSCREEN;
    if (tp->walk_only) {
        tp->edge = f->x;
    }
    tp->a = pick ? f->fp_x - tp->side * CARRY_DX : f->x;
    tp->b = drop ? to->fp_x + tp->side * CARRY_DX : to->x;
    float d[9] = {TRIP_READY,
                  fabsf(tp->a - f->x) / TRIP_V,
                  pick ? TRIP_LIFT : 0.0f,
                  fabsf(tp->edge - tp->a) / TRIP_V,
                  tp->walk_only ? 0.0f : TRIP_SWAP,
                  fabsf(tp->b - tp->edge) / TRIP_V,
                  drop ? TRIP_LIFT : 0.0f,
                  fabsf(to->x - tp->b) / TRIP_V,
                  0.0f};
    float acc = 0.0f;
    for (int i = 0; i < 9; i++) {
        acc += d[i];
        tp->c[i] = acc;
    }
}

float mascot_trip_seconds(const mascot_pose_t *from, const mascot_pose_t *to)
{
    trip_plan_t tp;
    trip_plan(from, to, &tp);
    return tp.c[8];
}

/* give PIP the props of `src` (old or new kit) */
static void wear_kit(mascot_pose_t *p, const mascot_pose_t *src)
{
    kit_t k;
    kit_of(src, &k);
    p->held = k.held;
    p->held_l = k.held_l;
    p->obj = k.obj;
    p->obj_t = src->obj_t;
    p->held_t = src->held_t;
    p->sign = src->sign;
    p->floor_prop = k.fp;
    p->fp_t = src->fp_t;
    p->fp_x = src->fp_x;
    p->fp_y = src->fp_y;
}

static float glide(float x0, float x1, float t, float t0, float t1) { return x0 + (x1 - x0) * seg(t, t0, t1); }

void mascot_trip_pose(const mascot_pose_t *f, const mascot_pose_t *to, float t, mascot_pose_t *p)
{
    trip_plan_t tp;
    trip_plan(f, to, &tp);
    const float *c = tp.c;
    mascot_home_pose(p);
    bool out = tp.walk_only || t < c[3] + TRIP_SWAP * 0.5f;
    wear_kit(p, out ? f : to);
    float x0 = f->x, x, heading;
    if (t < c[0]) { /* turn toward the first leg */
        x = x0;
        heading = tp.a != x0 ? (tp.a > x0 ? 1.0f : -1.0f) : tp.side;
    } else if (t < c[1]) {
        x = glide(x0, tp.a, t, c[0], c[1]);
        heading = tp.a > x0 ? 1.0f : -1.0f;
    } else if (t < c[2]) { /* pick up */
        x = tp.a;
        heading = tp.side;
    } else if (t < c[3]) {
        x = glide(tp.a, tp.edge, t, c[2], c[3]);
        heading = tp.side;
    } else if (t < c[4]) {
        x = tp.edge;
        heading = -tp.side;
    } else if (t < c[5]) {
        x = glide(tp.edge, tp.b, t, c[4], c[5]);
        heading = tp.b > tp.edge ? 1.0f : -1.0f;
    } else if (t < c[6]) { /* set down */
        x = tp.b;
        heading = -tp.side;
    } else {
        x = glide(tp.b, to->x, t, c[6], c[7]);
        heading = to->x != tp.b ? (to->x > tp.b ? 1.0f : -1.0f) : -tp.side;
        if (tp.walk_only) {
            heading = to->x > f->x ? 1.0f : -1.0f;
        }
    }
    p->x = x;
    bool walking = (t >= c[0] && t < c[1]) || (t >= c[2] && t < c[3]) || (t >= c[4] && t < c[5]) ||
                   (t >= c[6] && t < c[7]);
    p->yaw = heading * 72.0f;
    if (t >= c[7]) {
        p->yaw = heading * 72.0f * (1.0f - seg(t, c[7] - 0.2f, c[7] + 0.2f));
    }
    p->arm_r = p->held ? 30.0f : 8.0f;
    p->arm_l = p->held_l ? 30.0f : 8.0f;
    if (walking) {
        steps(p, t, 1.0f, 2.2f);
    }
    /* floor props: carried in both arms in front of PIP between pick-up and set-down */
    if (p->floor_prop) {
        float lift = 0.0f;
        bool carried = false;
        if (out && t >= c[1]) {
            float u = t < c[2] ? (t - c[1]) / TRIP_LIFT : 1.0f;
            lift = seg(u, 0.35f, 1.0f);
            p->sit = 0.4f * bump(u, 0.0f, 0.9f);
            carried = true;
        } else if (!out && t < c[6]) {
            float u = t >= c[5] ? (t - c[5]) / TRIP_LIFT : 0.0f;
            lift = 1.0f - seg(u, 0.0f, 0.65f);
            p->sit = 0.4f * bump(u, 0.1f, 1.0f);
            carried = true;
        }
        if (carried) {
            float dir = out ? tp.side : -tp.side;
            p->fp_x = x + dir * CARRY_DX;
            float ground = out ? f->fp_y : to->fp_y;
            p->fp_y = mixf(ground, p->y + 1.0f, lift); /* in front of PIP while lifted */
            p->fp_lift = CARRY_LIFT * lift;
            float arms = 20.0f + 55.0f * fmaxf2(lift, p->sit * 2.0f);
            p->arm_l = arms;
            p->arm_r = p->held ? fmaxf2(arms, 30.0f) : arms;
        }
    }
    /* far-right trips go behind the message board; never flip depth while overlapping it */
    p->behind = tp.side > 0.0f && x > PIP_BOARD_DX - 40.0f && (!tp.walk_only || f->behind) ? 1 : 0;
    if (tp.side < 0.0f && out && f->behind && x > PIP_BOARD_DX - 40.0f) {
        p->behind = 1;
    }
    p->look_x = heading * 0.6f;
    p->mouth = MOUTH_SMILE;
}

/* ==== tables ================================================================================ */
static const act_t IDLE[] = {
    {"ball", a_ball, 26, 4},         {"knock on the glass", a_knock, 16, 4},
    {"bored", a_bored, 22, 4},       {"check calendar", a_calendar, 18, 2},
    {"telescope", a_telescope, 20, 3}, {"dance", a_dance, 18, 3},
    {"read", a_read, 24, 2},         {"coffee", a_coffee, 18, 2},
    {"water plant", a_plant, 22, 2}, {"workout", a_workout, 18, 3},
    {"yo-yo", a_yoyo, 16, 3},        {"paper plane", a_plane, 18, 2},
    {"block tower", a_blocks, 22, 2}, {"balloon", a_balloon, 18, 2},
    {"juggle", a_juggle, 16, 3},     {"spin and wave", a_spin, 12, 2},
    {"hide and seek", a_hide, 20, 2}, {"stretch", a_stretch, 16, 2},
    {"guitar", a_guitar, 20, 2},     {"sweep", a_sweep, 18, 2},
    {"kite", a_kite, 24, 3},         {"clock", a_clock, 16, 2},
    {"sign", a_sign, 12, 4},         {"idea", a_idea, 16, 2},
    {"laptop", a_laptop, 20, 2},     {"umbrella", a_umbrella, 18, 2},
    {"peekaboo", a_peekaboo, 14, 2}, {"gift", a_gift, 18, 2},
    /* the whole room */
    {"behind the board", a_behind, 22, 2}, {"lean on the board", a_lean, 20, 2},
    {"present the board", a_present, 14, 2}, {"kick across the room", a_kick, 14, 2},
    {"lap of the room", a_lap, 16, 2},
};
static const act_t FOCUS[] = {
    {"typing", f_type, 22, 2},   {"points at timer", f_point, 10, 1}, {"peeks over laptop", f_peek, 14, 1},
    {"cheers", f_cheer, 8, 1},   {"focus sign", f_sign, 10, 4},       {"watches timer", f_watch, 16, 1},
    {"takes notes", f_write, 14, 1}, {"knocks", f_knock, 12, 2},     {"coffee", a_coffee, 14, 1},
    {"spin and wave", a_spin, 12, 2},
};
static const act_t LISTEN[] = {{"hand to ear", l_ear, 12, 2}, {"takes notes", l_notes, 12, 1}};
static const act_t THINK[] = {{"paces", t_pace, 10, 2}, {"scratches head", t_scratch, 9, 2}, {"flips book", t_flip, 8, 1}};
static const act_t PAUSE[] = {{"coffee", a_coffee, 18, 2}, {"read", a_read, 22, 2}, {"relax", r_relax, 18, 2}};
static const act_t BREAK_[] = {{"stretch", a_stretch, 16, 2}, {"workout", a_workout, 16, 3}, {"water plant", a_plant, 20, 2},
                               {"coffee", a_coffee, 16, 2},   {"relax", r_relax, 18, 2},     {"dance", a_dance, 16, 3}};
static const act_t DONE[] = {{"celebrate", d_celebrate, 8, 2}, {"spin and wave", a_spin, 10, 2}, {"high five", d_highfive, 10, 1},
                             {"gift", a_gift, 14, 2}};
static const act_t AGENDA[] = {{"calendar", c_point, 16, 2}, {"clock", a_clock, 14, 2}};
static const act_t ALARM[] = {{"alarm ringing", al_ring, 8, 1}, {"wake up!", al_wake, 6, 1}};
static const act_t CONFIRM[] = {{"head tilt", q_tilt, 10, 2}};
static const act_t SLEEP[] = {{"dozing", z_sit, 30, 3}};
static const act_t ERROR_[] = {{"fixing", e_fix, 10, 2}};
static const act_t PICK[] = {{"points at option", NULL, 30, 1}};

typedef struct {
    const act_t *acts;
    int n;
    const char *name;
} lib_t;

#define LIB(a, nm) {a, (int)(sizeof(a) / sizeof((a)[0])), nm}
static const lib_t LIBS[PIP_MODE_COUNT] = {
    LIB(IDLE, "idle"),   LIB(LISTEN, "listen"), LIB(THINK, "think"),   LIB(FOCUS, "focus"),   LIB(PAUSE, "pause"),
    LIB(BREAK_, "break"), LIB(DONE, "done"),    LIB(AGENDA, "agenda"), LIB(ALARM, "alarm"),   LIB(CONFIRM, "confirm"),
    LIB(SLEEP, "sleep"), LIB(PICK, "pick"),     LIB(ERROR_, "error"),
};

static const lib_t *lib(pip_mode_t m) { return &LIBS[(unsigned)m < PIP_MODE_COUNT ? m : PIP_MODE_IDLE]; }

int mascot_act_count(pip_mode_t mode) { return lib(mode)->n; }
const char *mascot_mode_name(pip_mode_t mode) { return lib(mode)->name; }

const char *mascot_act_name(pip_mode_t mode, int act)
{
    const lib_t *l = lib(mode);
    return act >= 0 && act < l->n ? l->acts[act].name : "?";
}

int mascot_act_variants(pip_mode_t mode, int act)
{
    const lib_t *l = lib(mode);
    return act >= 0 && act < l->n && l->acts[act].variants ? l->acts[act].variants : 1;
}

float mascot_perf_seconds(const pip_perf_t *p)
{
    const lib_t *l = lib((pip_mode_t)p->mode);
    float base = p->act < l->n ? l->acts[p->act].dur : 10.0f;
    static const float tempo[3] = {1.15f, 1.0f, 0.88f}; /* mood: calm / normal / lively */
    return base * tempo[p->mood % 3];
}

void mascot_perf_pose(const pip_perf_t *pf, float t, float dur, mascot_pose_t *out)
{
    mascot_home_pose(out);
    const lib_t *l = lib((pip_mode_t)pf->mode);
    if (pf->act >= l->n || !l->acts[pf->act].fn) {
        return;
    }
    l->acts[pf->act].fn(out, t, dur, pf->variant, pf->dir ? 1.0f : -1.0f, pf->mood % 3);
}

void mascot_pick_pose(mascot_pose_t *p, float t, int row, int rows)
{
    mascot_home_pose(p);
    float u = rows > 1 ? (float)row / (float)(rows - 1) : 0.5f; /* 0 top .. 1 bottom */
    p->yaw = 42.0f + 6.0f * wav(t, 2.6f);
    p->look_x = 1.0f;
    p->look_y = -0.9f + 1.5f * u;
    p->arm_r = 158.0f - 62.0f * u;
    p->arm_l = 12.0f + 6.0f * wav(t, 1.3f);
    p->lean = 3.0f;
    p->eyes = EYE_WIDE;
    p->antenna = 2.5f * wav(t, 0.9f);
    p->head_dy = -1.0f * fabsf(wav(t, 1.8f));
    emote(p, EMOTE_QUESTION, t, 0.0f);
}

const char *mascot_sign_text(int idx)
{
    static const char *const T[] = {
        /* idle: variant x mood */
        "HI!", "READY?", "LET'S GO", "1 STEP", "HELLO", "FOCUS?", "YOU+ME", "TINY STEP", "HEY!", "PLAN?", "GO GO", "START?",
        /* focus */
        "GO!", "KEEP ON", "YOU GOT IT", "NICE!",
    };
    int n = (int)(sizeof T / sizeof T[0]);
    return T[(idx % n + n) % n];
}
