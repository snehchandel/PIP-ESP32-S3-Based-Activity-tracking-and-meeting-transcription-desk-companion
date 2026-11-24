/* PIP mascot: 8 expressions (eyeless sprites + live procedural eyes) and a smooth idle-animation engine.
 * Pure C99 - the same motion runs on the device and in sim_rlcd. The reflective LCD refreshes fast, so
 * animation runs at up to 20 FPS (eased), unlike an e-ink panel. */
#ifndef PIP_MASCOT_H
#define PIP_MASCOT_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    PIP_EXPR_READY = 0,
    PIP_EXPR_LISTENING,
    PIP_EXPR_THINKING,
    PIP_EXPR_WORKING,
    PIP_EXPR_PAUSED,
    PIP_EXPR_DONE,
    PIP_EXPR_ALARM,
    PIP_EXPR_SLEEP,
    PIP_EXPR_COUNT
} pip_expr_t;

typedef enum { EYE_PILL = 0, EYE_HAPPY = 1, EYE_CLOSED = 2, EYE_ANGLED = 3 } eye_style_t;

typedef struct {
    int8_t dx, dy;         /* whole-body offset (hop, nod, shake, breathing) */
    int8_t look_x, look_y; /* eye offset inside the visor (+x = toward the text on the right) */
    uint8_t lid;           /* 0 open .. 8 closed (blink) */
} mascot_pose_t;

typedef enum {
    ANIM_NONE = 0,
    ANIM_BLINK,
    ANIM_DOUBLE_BLINK,
    ANIM_GLANCE_TEXT, /* look at the content panel, then back */
    ANIM_LOOK_AROUND,
    ANIM_LOOK_UP,
    ANIM_HOP,
    ANIM_NOD,
    ANIM_TYPE, /* quick typing jitter (WORKING) */
    ANIM_COUNT
} anim_kind_t;

#define MASCOT_FRAME_MS 50u /* 20 FPS during motion */

typedef struct {
    uint32_t rng;
    anim_kind_t kind;
    uint32_t start_ms, dur_ms, next_at_ms, last_frame_ms;
    pip_expr_t expr;
    mascot_pose_t pose;
} mascot_anim_t;

const uint8_t *mascot_bits(pip_expr_t e); /* eyeless 120x120 sprite, 15 B/row, bit 1 = black */
void mascot_eye_spec(pip_expr_t e, eye_style_t *style, int *dx, int *dy, int *h);
void mascot_eye_anchors(int *lx, int *ly, int *rx, int *ry);
const char *mascot_expr_name(pip_expr_t e);

void mascot_anim_init(mascot_anim_t *a, uint32_t seed, uint32_t now_ms);
/* Start an event now (e.g. ANIM_GLANCE_TEXT when the text changes). */
void mascot_anim_trigger(mascot_anim_t *a, anim_kind_t k, uint32_t now_ms);
/* Advance; returns true when the pose changed and the screen should be redrawn. */
bool mascot_anim_step(mascot_anim_t *a, pip_expr_t e, uint32_t now_ms);
/* Pure pose function (exposed for tests): pose of event k at progress t in [0,1000]. */
mascot_pose_t mascot_event_pose(anim_kind_t k, int t_permille);

#endif
