/* PIP rig geometry + scene engine (act selection, 2-hour no-repeat history, cross-fades, blinks,
 * breathing and full-body button reactions). The choreography itself lives in mascot_acts.c. */
#include "mascot.h"

#include <math.h>
#include <string.h>

#include "mascot_acts.h"

#define PI_F 3.14159265f
#define DEG (PI_F / 180.0f)

static float clamp01(float x) { return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x); }
static float smooth(float x)
{
    x = clamp01(x);
    return x * x * (3.0f - 2.0f * x);
}

void mascot_home_pose(mascot_pose_t *p)
{
    memset(p, 0, sizeof *p);
    p->scale = 1.0f;
    p->eyes = EYE_PILL;
    p->mouth = MOUTH_SMILE;
}

/* ---- laptop (shared by the rig's hand targets and the renderer) ---------------------------- */
#define LT_W 34.0f     /* width */
#define LT_D 20.0f     /* deck depth = lid height, so the shut lid covers the deck */
#define LT_VIEW 0.4f   /* how far you look down on the floor: depth toward you moves things down the screen */

void mascot_laptop(const mascot_pose_t *p, pip_laptop_t *g)
{
    /* ground plane: X right, Z toward you. f points from the hinge to the typist (PIP); it turns smoothly
     * from "PIP on the left" through "PIP straight behind" to "PIP on the right", so gliding never pops. */
    float dx = p->x - p->fp_x, fz = 30.0f, n = sqrtf(dx * dx + fz * fz);
    float fx = dx / n;
    fz /= n;
    float ux = fz, uz = -fx; /* along the keyboard */
    if (ux < 0.0f) {
        ux = -ux;
        uz = -uz;
    }
    /* lid: leaning back a little when open, folded onto the deck while carried */
    float shut = smooth(p->fp_lift / 6.0f);
    float al = -0.2f + (PI_F * 0.5f + 0.2f) * shut;
    float ly = cosf(al), lf = sinf(al); /* lid direction: up and toward the typist */
    const float T = 2.0f;               /* deck thickness */
#define LT_P(X, Y, Z) ((pip_pt_t){(X), -(Y) + LT_VIEW * (Z)})
    float hx = LT_W * 0.5f * ux, hz = LT_W * 0.5f * uz, dfx = LT_D * 0.5f * fx, dfz = LT_D * 0.5f * fz;
    g->deck[0] = LT_P(dfx - hx, T, dfz - hz);
    g->deck[1] = LT_P(dfx + hx, T, dfz + hz);
    g->deck[2] = LT_P(-dfx + hx, T, -dfz + hz);
    g->deck[3] = LT_P(-dfx - hx, T, -dfz - hz);
    float tx = LT_D * lf * fx, ty = LT_D * ly, tz = LT_D * lf * fz;
    g->lid[0] = LT_P(-dfx - hx, T, -dfz - hz);
    g->lid[1] = LT_P(-dfx + hx, T, -dfz + hz);
    g->lid[2] = LT_P(-dfx + hx + tx, T + ty, -dfz + hz + tz);
    g->lid[3] = LT_P(-dfx - hx + tx, T + ty, -dfz - hz + tz);
    for (int i = 0; i < 2; i++) { /* on the keys, toward the typist, a little in from each side */
        float side = i == 0 ? -1.0f : 1.0f;
        g->keys[i] = LT_P(0.3f * LT_D * fx + side * LT_W * 0.2f * ux, T, 0.3f * LT_D * fz + side * LT_W * 0.2f * uz);
    }
    if (g->keys[0].x > g->keys[1].x) {
        pip_pt_t k = g->keys[0];
        g->keys[0] = g->keys[1];
        g->keys[1] = k;
    }
#undef LT_P
    /* the screen faces the typist; you see it while it also turns toward you (view from slightly above) */
    float nz = fz * cosf(al), ny = -sinf(al);
    g->screen_vis = nz * 0.93f + ny * 0.37f > 0.05f;
}

/* ---- rig ---------------------------------------------------------------------------------- */
void mascot_rig(const mascot_pose_t *p, pip_rig_t *r)
{
    memset(r, 0, sizeof *r);
    float s = p->scale > 0.2f ? p->scale : 1.0f;
    float yaw = p->yaw * DEG, c = cosf(yaw), sn = sinf(yaw);
    float sit = clamp01(p->sit);
    r->s = s;
    r->sitting = sit > 0.5f;
    float leg_full = 12.0f * s;
    float leg = leg_full * (1.0f - 0.75f * sit);
    r->leg_w = 9.0f * s;
    float lift[2] = {p->leg_l, p->leg_r};
    for (int i = 0; i < 2; i++) {
        float side = i == 0 ? -1.0f : 1.0f;
        r->foot[i].x = p->x + side * 10.0f * s * c + sit * 6.0f * s * sn;
        r->foot[i].y = p->y - lift[i] * s;
        r->leg_len[i] = leg;
    }
    /* body */
    r->bw = 40.0f * s;
    r->bx = p->x + p->lean * 0.3f;
    r->b_bot = p->y - leg;
    r->b_top = r->b_bot - 34.0f * s;
    /* head */
    r->hw = 64.0f * s;
    r->hx = p->x + p->lean;
    r->h_bot = r->b_top - 1.0f * s + p->head_dy;
    r->h_top = r->h_bot - 50.0f * s;
    float hr = 30.0f * s, hcy = (r->h_top + r->h_bot) * 0.5f;
    /* visor: the face band spans +-50 deg around the front of a cylinder of radius hr */
    float a0 = -50.0f * DEG + yaw, a1 = 50.0f * DEG + yaw;
    if (a0 < 90.0f * DEG && a1 > -90.0f * DEG) {
        float l = sinf(a0 < -90.0f * DEG ? -90.0f * DEG : a0) * hr * 0.92f;
        float rr = sinf(a1 > 90.0f * DEG ? 90.0f * DEG : a1) * hr * 0.92f;
        if (rr - l > 6.0f * s) {
            r->visor = true;
            r->v_l = r->hx + l;
            r->v_r = r->hx + rr;
            r->v_top = hcy - 15.0f * s;
            r->v_bot = hcy + 15.0f * s;
        }
    }
    r->face_dx = sn * hr * 0.75f;
    for (int i = 0; i < 2; i++) {
        float th = (i == 0 ? -17.0f : 17.0f) * DEG + yaw;
        float z = cosf(th);
        r->eye_vis[i] = r->visor && z > 0.25f;
        r->eye_w[i] = 8.0f * s * (z < 0.4f ? 0.4f : z);
        r->eye[i].x = r->hx + sinf(th) * hr * 0.92f + p->look_x * 3.0f * s;
        r->eye[i].y = hcy - 2.0f * s + p->look_y * 3.0f * s;
        float eth = (i == 0 ? -90.0f : 90.0f) * DEG + yaw;
        r->ear[i].x = r->hx + sinf(eth) * hr * 1.06f;
        r->ear[i].y = hcy;
        r->ear_z[i] = cosf(eth);
    }
    r->ant_base.x = r->hx;
    r->ant_base.y = r->h_top;
    r->ant_tip.x = r->hx + p->antenna * s;
    r->ant_tip.y = r->h_top - 15.0f * s;
    /* chest light / back panel on the body cylinder (radius 20) */
    r->chest_vis = c > 0.3f;
    r->chest.x = r->bx + sn * 20.0f * s * 0.8f;
    r->chest.y = (r->b_top + r->b_bot) * 0.5f;
    r->back_vis = c < -0.3f;
    r->back.x = r->bx - sn * 20.0f * s * 0.8f;
    r->back.y = r->chest.y;
    /* arms: screen-left/right at yaw 0, swinging toward the facing direction in profile */
    float arm[2] = {p->arm_l, p->arm_r};
    for (int i = 0; i < 2; i++) {
        float side = i == 0 ? -1.0f : 1.0f;
        float sth = (i == 0 ? -90.0f : 90.0f) * DEG + yaw;
        r->shoulder[i].x = r->bx + sinf(sth) * 20.0f * s;
        r->shoulder[i].y = r->b_top + 8.0f * s;
        r->arm_z[i] = cosf(sth);
        float dirx = side * c + sn * (1.0f - fabsf(c));
        dirx = dirx > 1.0f ? 1.0f : (dirx < -1.0f ? -1.0f : dirx);
        if (fabsf(dirx) < 0.35f) {
            dirx = dirx < 0.0f ? -0.35f : 0.35f;
        }
        float a = arm[i] * DEG, len = 24.0f * s;
        float out = sinf(a);
        if (arm[i] > 90.0f && out < 0.62f) { /* raised arms open into a V so they clear the head */
            out = 0.62f;
        }
        r->hand[i].x = r->shoulder[i].x + out * dirx * len;
        r->hand[i].y = r->shoulder[i].y + cosf(a) * len;
    }
    r->held_c.x = (r->hand[0].x + r->hand[1].x) * 0.5f;
    r->held_c.y = (r->hand[0].y + r->hand[1].y) * 0.5f;
    if (p->held == PROP_BOOK || p->held == PROP_CALENDAR) {
        /* held by its edges: the arms set where it is, the hands close in on it. A left arm raised well above the
         * right one lets go (points at the board) and the right hand holds it alone; a pencil writes on it. */
        float half = 17.0f * s, dy = (p->held == PROP_CALENDAR ? -5.0f : 0.0f) * s;
        float free_l = smooth((p->arm_l - p->arm_r - 20.0f) / 20.0f);
        pip_pt_t hc = r->held_c;
        hc.x += sn * 14.0f * s; /* turned: held out in front, not across the face */
        hc.x += (r->hand[1].x - half - hc.x) * free_l;
        hc.y += (r->hand[1].y - dy - hc.y) * free_l;
        r->held_c = hc;
        pip_pt_t edge_l = {hc.x - half, hc.y + dy};
        if (p->held_l == PROP_PENCIL) { /* the arm's scribble moves the pencil across the page */
            float sc = (p->arm_l - 74.0f) * 0.5f * s;
            sc = sc > 5.0f * s ? 5.0f * s : (sc < -5.0f * s ? -5.0f * s : sc);
            edge_l.x = hc.x - 4.0f * s + sc;
            edge_l.y = hc.y - (p->held == PROP_CALENDAR ? 12.0f : 2.0f) * s;
        }
        r->hand[0].x += (edge_l.x - r->hand[0].x) * (1.0f - free_l);
        r->hand[0].y += (edge_l.y - r->hand[0].y) * (1.0f - free_l);
        r->hand[1].x = hc.x + half;
        r->hand[1].y = hc.y + dy;
    }
    /* grip: the hands go where the object needs them, reaching in front of the body */
    float g = clamp01(p->grip);
    if (g > 0.0f) {
        pip_pt_t tgt[2];
        bool have = false;
        int front_only = -1; /* >= 0: only this arm is drawn in front; the other reaches across behind the body */
        float cy = (r->b_top + r->b_bot) * 0.5f;
        if (p->held == PROP_GUITAR) { /* left hand on the neck, right hand strumming over the sound hole */
            tgt[0].x = r->bx - 23.0f * s;
            tgt[0].y = cy - 8.0f * s;
            tgt[1].x = r->bx + 5.0f * s;
            tgt[1].y = cy + 3.0f * s + 3.5f * s * sinf(p->held_t * 14.0f);
            have = true;
        } else if (p->floor_prop == PROP_LAPTOP) { /* both hands on the keyboard, tapping in turn */
            pip_laptop_t lt;
            mascot_laptop(p, &lt);
            float k = sinf(p->fp_t * 22.0f);
            for (int i = 0; i < 2; i++) {
                tgt[i].x = p->fp_x + lt.keys[i].x;
                tgt[i].y = p->fp_y - p->fp_lift + lt.keys[i].y - 2.0f * fmaxf(0.0f, i == 0 ? k : -k);
            }
            front_only = p->fp_x > p->x ? 1 : 0; /* the arm on the laptop's side */
            have = true;
        }
        if (have) {
            for (int i = 0; i < 2; i++) {
                r->hand[i].x += (tgt[i].x - r->hand[i].x) * g;
                r->hand[i].y += (tgt[i].y - r->hand[i].y) * g;
                if (g > 0.5f) {
                    r->arm_z[i] = front_only < 0 || front_only == i ? 1.0f : -1.0f;
                }
            }
        }
    }
}

/* ---- engine --------------------------------------------------------------------------------- */
static uint32_t rnd(mascot_anim_t *a)
{
    a->rng ^= a->rng << 13;
    a->rng ^= a->rng >> 17;
    a->rng ^= a->rng << 5;
    return a->rng;
}

uint16_t mascot_perf_key(const pip_perf_t *p)
{
    return (uint16_t)(((unsigned)p->mode & 15u) << 12 | ((unsigned)p->act & 63u) << 6 | ((unsigned)p->variant & 7u) << 3 |
                      ((unsigned)p->dir & 1u) << 2 | ((unsigned)p->mood & 3u));
}

/* ms since this key was last performed (UINT32_MAX = not within the history window) */
static uint32_t seen_ago(const mascot_anim_t *a, uint16_t key, uint32_t now)
{
    uint32_t best = UINT32_MAX;
    for (int i = 0; i < a->hist_n; i++) {
        if (a->hist_key[i] == key) {
            uint32_t ago = now - a->hist_ms[i];
            if (ago < best) {
                best = ago;
            }
        }
    }
    return best;
}

static bool recent_act(const mascot_anim_t *a, pip_mode_t m, int act, int gap)
{
    int n = a->recent_n[m];
    for (int i = 0; i < n && i < gap; i++) {
        if (a->recent[m][i] == act) {
            return true;
        }
    }
    return false;
}

static void remember(mascot_anim_t *a, uint32_t now)
{
    a->hist_key[a->hist_head] = mascot_perf_key(&a->perf);
    a->hist_ms[a->hist_head] = now;
    a->hist_head = (a->hist_head + 1) % MASCOT_HIST;
    if (a->hist_n < MASCOT_HIST) {
        a->hist_n++;
    }
    uint8_t *r = a->recent[a->mode];
    memmove(r + 1, r, MASCOT_RECENT - 1);
    r[0] = a->perf.act;
    if (a->recent_n[a->mode] < MASCOT_RECENT) {
        a->recent_n[a->mode]++;
    }
    a->perf_count++;
}

/* Which acts fit the scene: tagged acts follow the task at hand. On the idle screen untagged free play runs and,
 * while a step is lined up, every third act previews it. Falls back to the "general" acts, then to everything. */
static int egg_pool(pip_mode_t m, uint8_t *pool)
{
    int np = 0;
    for (int i = 0; i < mascot_act_count(m) && np < 96; i++) {
        if (mascot_act_tags(m, i) & PIP_TAG_EGG) {
            pool[np++] = (uint8_t)i;
        }
    }
    return np;
}

static int eligible_pool(const mascot_anim_t *a, pip_mode_t m, uint8_t *pool)
{
    int n = mascot_act_count(m), np = 0;
    uint32_t tags = a->tags;
    bool idle = m == PIP_MODE_IDLE, preview = idle && tags && a->perf_count % 3u == 2u;
    for (int pass = 0; pass < 3 && np == 0; pass++) {
        uint32_t want = pass == 0 ? tags : PIP_TAG(PIP_ACT_GENERAL);
        for (int i = 0; i < n && np < 96; i++) {
            uint32_t at = mascot_act_tags(m, i);
            bool ok;
            if (at & PIP_TAG_EGG) {
                ok = false; /* easter eggs only come from the rare roll */
            } else if (pass == 2) {
                ok = true;
            } else if (idle) {
                ok = preview ? (at & want) != 0u : at == 0u;
            } else {
                ok = at == 0u || (at & want) != 0u;
            }
            if (ok) {
                pool[np++] = (uint8_t)i;
            }
        }
    }
    return np;
}

static void start_perf(mascot_anim_t *a, uint32_t now)
{
    pip_mode_t m = a->mode;
    uint8_t pool[96];
    int np = 0;
    /* easter eggs: about 1 in 24 idle acts, 1 in 3 when upset on the error screen; never twice within 2 h */
    uint32_t roll = rnd(a);
    if ((m == PIP_MODE_IDLE && roll % 24u == 0u) || (m == PIP_MODE_ERROR && roll % 3u == 0u)) {
        uint8_t eggs[8];
        int ne = egg_pool(m, eggs);
        if (ne > 0) {
            pip_perf_t c = {(uint8_t)m, eggs[rnd(a) % (uint32_t)ne], 0, (uint8_t)(rnd(a) & 1u), (uint8_t)(rnd(a) % 3u)};
            if (m != PIP_MODE_IDLE || seen_ago(a, mascot_perf_key(&c), now) >= MASCOT_NO_REPEAT_MS) {
                pool[np++] = c.act;
            }
        }
    }
    if (np == 0) {
        np = eligible_pool(a, m, pool);
    }
    int gap = np / 2 < MASCOT_RECENT ? np / 2 : MASCOT_RECENT; /* an activity type sits out at least n/2 turns */
    pip_perf_t best = {0};
    uint32_t best_ago = 0;
    bool have = false;
    int seq_next = -1;
    if (mascot_lib_sequential(m)) { /* the next act in table order after the last one played here */
        int last = a->recent_n[m] ? a->recent[m][0] : -1;
        for (int i = 0; i < np && seq_next < 0; i++) {
            if (pool[i] > last) {
                seq_next = pool[i];
            }
        }
        if (seq_next < 0) {
            seq_next = pool[0];
        }
    }
    for (int tries = 0; tries < 600; tries++) {
        pip_perf_t c;
        c.mode = (uint8_t)m;
        c.act = (uint8_t)(seq_next >= 0 ? seq_next : pool[rnd(a) % (uint32_t)np]);
        if (seq_next < 0 && np > 1 && recent_act(a, m, c.act, gap) && tries < 400) {
            continue;
        }
        c.variant = (uint8_t)(rnd(a) % (uint32_t)mascot_act_variants(m, c.act));
        c.dir = (uint8_t)(rnd(a) & 1u);
        c.mood = (uint8_t)(rnd(a) % 3u);
        uint32_t ago = seen_ago(a, mascot_perf_key(&c), now);
        if (ago >= MASCOT_NO_REPEAT_MS) {
            best = c;
            have = true;
            break;
        }
        if (!have || ago > best_ago) { /* fallback: the one seen longest ago */
            best = c;
            best_ago = ago;
            have = true;
        }
    }
    if (m != PIP_MODE_IDLE && m != PIP_MODE_PICK) { /* keep things where they are: mirror rather than move them */
        mascot_pose_t t0;
        mascot_perf_pose(&best, 0.0f, mascot_perf_seconds(&best), &t0);
        if (!mascot_same_props(&a->pose, &t0)) {
            pip_perf_t flip = best;
            flip.dir ^= 1u;
            mascot_perf_pose(&flip, 0.0f, mascot_perf_seconds(&flip), &t0);
            if (mascot_same_props(&a->pose, &t0)) {
                best = flip;
            }
        }
    }
    a->from = a->pose;
    a->blend_start_ms = now;
    a->perf = best;
    a->act_start_ms = now;
    a->act_dur_ms = (uint32_t)(mascot_perf_seconds(&best) * 1000.0f);
    remember(a, now);
    /* different props: fetch them from the screen edge first (the act starts when PIP is back) */
    mascot_pose_t to;
    if (m == PIP_MODE_PICK) {
        mascot_pick_pose(&to, 0.0f, a->pick_row, a->pick_rows);
    } else {
        mascot_perf_pose(&best, 0.0f, (float)a->act_dur_ms / 1000.0f, &to);
    }
    a->trip = !mascot_same_props(&a->pose, &to) || fabsf(a->pose.x - to.x) > 12.0f; /* or just far away */
    if (a->trip) {
        a->trip_from = a->pose;
        a->trip_to = to;
        a->trip_start_ms = now;
        a->trip_ms = (uint32_t)(mascot_trip_seconds(&a->pose, &to) * 1000.0f);
    }
}

void mascot_anim_init(mascot_anim_t *a, uint32_t seed, uint32_t now_ms)
{
    memset(a, 0, sizeof *a);
    a->rng = seed ? seed : 0x9E3779B9u;
    mascot_home_pose(&a->pose);
    a->from = a->pose;
    a->mode = PIP_MODE_IDLE;
    a->next_blink_ms = now_ms + 2000u;
    a->last_frame_ms = now_ms - MASCOT_FRAME_MS;
    a->pick_rows = 4;
}

void mascot_set_scene(mascot_anim_t *a, pip_mode_t mode, uint32_t tags, uint32_t now_ms)
{
    bool restart = !a->started || mode != a->mode || (tags != a->tags && mode != PIP_MODE_IDLE);
    a->tags = tags;
    if (!restart) {
        return;
    }
    a->mode = mode;
    a->started = true;
    start_perf(a, now_ms);
}

void mascot_set_mode(mascot_anim_t *a, pip_mode_t mode, uint32_t now_ms) { mascot_set_scene(a, mode, a->tags, now_ms); }

void mascot_react(mascot_anim_t *a, pip_react_t r, uint32_t now_ms)
{
    a->react = r;
    a->react_start_ms = now_ms;
}

void mascot_set_pick(mascot_anim_t *a, int row, int rows)
{
    a->pick_row = row;
    a->pick_rows = rows > 0 ? rows : 1;
}

static float lerpf(float x, float y, float w) { return x + (y - x) * w; }

static void blend(mascot_pose_t *out, const mascot_pose_t *from, float w)
{
    /* continuous channels cross-fade; props/emotes switch at once */
    mascot_pose_t t = *out;
    t.x = lerpf(from->x, out->x, w);
    t.y = lerpf(from->y, out->y, w);
    float dy = out->yaw - from->yaw;
    while (dy > 180.0f) dy -= 360.0f;
    while (dy < -180.0f) dy += 360.0f;
    t.yaw = from->yaw + dy * w;
    t.scale = lerpf(from->scale, out->scale, w);
    t.lean = lerpf(from->lean, out->lean, w);
    t.head_dy = lerpf(from->head_dy, out->head_dy, w);
    t.look_x = lerpf(from->look_x, out->look_x, w);
    t.look_y = lerpf(from->look_y, out->look_y, w);
    t.arm_l = lerpf(from->arm_l, out->arm_l, w);
    t.arm_r = lerpf(from->arm_r, out->arm_r, w);
    t.leg_l = lerpf(from->leg_l, out->leg_l, w);
    t.leg_r = lerpf(from->leg_r, out->leg_r, w);
    t.antenna = lerpf(from->antenna, out->antenna, w);
    t.sit = lerpf(from->sit, out->sit, w);
    if (from->floor_prop == out->floor_prop) { /* the same thing on the floor glides, never jumps */
        t.fp_x = lerpf(from->fp_x, out->fp_x, w);
        t.fp_y = lerpf(from->fp_y, out->fp_y, w);
        t.fp_lift = lerpf(from->fp_lift, out->fp_lift, w);
    }
    t.glass = lerpf(from->glass, out->glass, w);
    t.grip = lerpf(from->grip, out->grip, w);
    *out = t;
}

static const uint32_t REACT_MS[PIP_REACT_COUNT] = {0, 900, 1200, 1400, 1100, 650};

/* full-body reactions layered over whatever PIP is doing */
static void apply_react(mascot_anim_t *a, mascot_pose_t *p, uint32_t now)
{
    if (a->react == PIP_REACT_NONE) {
        return;
    }
    uint32_t el = now - a->react_start_ms, dur = REACT_MS[a->react];
    if (el >= dur) {
        a->react = PIP_REACT_NONE;
        return;
    }
    float u = (float)el / (float)dur, b = sinf(PI_F * u);
    switch (a->react) {
    case PIP_REACT_PRESS: /* whip round toward the button, hop, then face you */
        p->yaw = lerpf(p->yaw, 55.0f, b);
        p->y -= 9.0f * b;
        p->look_x = lerpf(p->look_x, 1.0f, b);
        p->arm_r = lerpf(p->arm_r, 120.0f, b);
        if (u > 0.2f && u < 0.8f) {
            p->eyes = EYE_WIDE;
        }
        break;
    case PIP_REACT_DOUBLE: /* full spin with a hop */
        p->yaw += 360.0f * smooth(u);
        p->y -= 12.0f * b;
        p->arm_l = lerpf(p->arm_l, 100.0f, b);
        p->arm_r = lerpf(p->arm_r, 100.0f, b);
        p->emote = EMOTE_SPARKLE;
        p->emote_t = (float)el / 1000.0f;
        break;
    case PIP_REACT_HOLD: /* leans in, hand to ear */
        p->scale *= 1.0f + 0.08f * smooth(u * 3.0f);
        p->lean = lerpf(p->lean, 5.0f, smooth(u * 3.0f));
        p->arm_r = lerpf(p->arm_r, 160.0f, smooth(u * 3.0f));
        p->emote = EMOTE_SOUND;
        p->emote_t = (float)el / 1000.0f;
        break;
    case PIP_REACT_BACK: /* turns away and back */
        p->yaw += 180.0f * b;
        p->y -= 4.0f * b;
        break;
    case PIP_REACT_NEXT:
        p->y -= 6.0f * b;
        p->x += 3.0f * b;
        break;
    default: break;
    }
}

bool mascot_anim_step(mascot_anim_t *a, uint32_t now_ms)
{
    if (now_ms - a->last_frame_ms < MASCOT_FRAME_MS) {
        return false;
    }
    a->last_frame_ms = now_ms;
    if (!a->started) {
        mascot_set_mode(a, a->mode, now_ms);
    }
    if (a->trip && now_ms - a->trip_start_ms >= a->trip_ms) { /* back with the props: the act begins */
        a->trip = false;
        a->from = a->pose;
        a->blend_start_ms = now_ms;
        a->act_start_ms = now_ms;
    }
    if (!a->trip && now_ms - a->act_start_ms >= a->act_dur_ms) {
        start_perf(a, now_ms);
    }
    mascot_pose_t p;
    float t = (float)(now_ms - a->act_start_ms) / 1000.0f;
    if (a->trip) {
        mascot_trip_pose(&a->trip_from, &a->trip_to, (float)(now_ms - a->trip_start_ms) / 1000.0f, &p);
    } else if (a->mode == PIP_MODE_PICK) {
        mascot_pick_pose(&p, t, a->pick_row, a->pick_rows);
    } else {
        mascot_perf_pose(&a->perf, t, (float)a->act_dur_ms / 1000.0f, &p);
    }
    float w = smooth((float)(now_ms - a->blend_start_ms) / 450.0f);
    if (w < 1.0f) {
        blend(&p, &a->from, w);
    }
    /* life layer: breathing + spontaneous blinks (only with open eyes) */
    if (p.sit < 0.5f && p.y > -1.0f) {
        p.head_dy += 0.9f * sinf((float)now_ms * 2.0f * PI_F / 3600.0f);
    }
    if ((int32_t)(now_ms - a->next_blink_ms) >= 0) {
        a->blink_start_ms = now_ms;
        a->next_blink_ms = now_ms + 2200u + rnd(a) % 4200u;
    }
    uint32_t be = now_ms - a->blink_start_ms;
    if (be < 180u && (p.eyes == EYE_PILL || p.eyes == EYE_WIDE || p.eyes == EYE_ANGLED)) {
        float bl = 1.0f - fabsf((float)be / 90.0f - 1.0f);
        p.lid = p.lid > bl ? p.lid : bl;
    }
    apply_react(a, &p, now_ms);
    bool changed = memcmp(&p, &a->pose, sizeof p) != 0;
    a->pose = p;
    return changed;
}
