/* PIP mascot rig + scene engine (pure C99, shared by the device and sim_rlcd).
 *
 * PIP is no longer a set of fixed sprites: it is a small procedural robot rig (head/visor/eyes/antenna,
 * body, arms, legs) that can turn around its vertical axis, sit, hop, walk, lean, hold props and press
 * itself against the glass. A scene engine plays "acts" (short choreographies with props) chosen per
 * screen. On the idle screen PIP has the whole display: it can walk behind the message board, lean on it,
 * kick a ball across the room or leave the screen on one side and come back on the other. On the idle screen every performance is checked against a 2-hour history so
 * the same animation never repeats within that window. The reflective LCD refreshes fast, so motion runs
 * at up to 20 FPS. */
#ifndef PIP_MASCOT_H
#define PIP_MASCOT_H

#include <stdbool.h>
#include <stdint.h>

/* legacy expression ids (kept for the screen -> mood mapping) */
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

typedef enum { EYE_PILL = 0, EYE_HAPPY, EYE_CLOSED, EYE_ANGLED, EYE_WIDE, EYE_STAR, EYE_HEART, EYE_COUNT } eye_style_t;
typedef enum { MOUTH_NONE = 0, MOUTH_SMILE, MOUTH_GRIN, MOUTH_O, MOUTH_FLAT, MOUTH_WAVY, MOUTH_COUNT } mouth_t;

typedef enum {
    EMOTE_NONE = 0,
    EMOTE_FOCUS,    /* three action lines that shoot out and pulse */
    EMOTE_IDEA,     /* light bulb with blinking rays */
    EMOTE_HEART,    /* hearts floating up */
    EMOTE_ZZZ,      /* Zs drifting up and growing */
    EMOTE_QUESTION, /* wobbling ? */
    EMOTE_EXCLAIM,  /* bouncing ! */
    EMOTE_MUSIC,    /* notes floating on a wave */
    EMOTE_SWEAT,    /* drop sliding down the head */
    EMOTE_SPARKLE,  /* twinkling stars */
    EMOTE_DOTS,     /* thought bubble filling with ... */
    EMOTE_KNOCK,    /* impact lines at the knuckles */
    EMOTE_ALARM,    /* shake lines on both sides */
    EMOTE_SOUND,    /* sound waves toward the ear (listening) */
    EMOTE_COUNT
} emote_t;

typedef enum {
    PROP_NONE = 0,
    PROP_BALL,
    PROP_MUG,
    PROP_CALENDAR,
    PROP_BOOK,
    PROP_PLANT,
    PROP_WATERCAN,
    PROP_DUMBBELL,
    PROP_YOYO,
    PROP_PLANE,
    PROP_BLOCKS,
    PROP_LAPTOP,
    PROP_BALLOON,
    PROP_TELESCOPE,
    PROP_GUITAR,
    PROP_BROOM,
    PROP_KITE,
    PROP_CLOCK,
    PROP_SIGN,
    PROP_UMBRELLA,
    PROP_HEADPHONES,
    PROP_PENCIL,
    PROP_WRENCH,
    PROP_GIFT,
    PROP_PHONE,
    PROP_PAN,
    PROP_BAG,
    PROP_POTATO,
    PROP_COUNT
} prop_t;

/* What the step in progress is about (classified on the PC: host/service/planner/activity.py). PIP acts it out. */
typedef enum {
    PIP_ACT_GENERAL = 0,
    PIP_ACT_WRITE,
    PIP_ACT_COMPUTER,
    PIP_ACT_READ,
    PIP_ACT_CALL,
    PIP_ACT_CLEAN,
    PIP_ACT_EXERCISE,
    PIP_ACT_COOK,
    PIP_ACT_GARDEN,
    PIP_ACT_MUSIC,
    PIP_ACT_FIX,
    PIP_ACT_PLAN,
    PIP_ACT_ERRAND,
    PIP_ACT_REST,
    PIP_ACTIVITY_COUNT
} pip_activity_t;

/* Scene tags select acts that fit the moment: the task's activity (focus, pause, done, idle preview), the
 * activity picked in the voice picker (listening) or the thinking stage. */
#define PIP_TAG(act) (1u << (unsigned)(act))
#define PIP_TAG_VOICE(choice) (1u << (unsigned)(choice)) /* 0 Calendar, 1 Brain dump, 2 Focus, 3 Alarms */
#define PIP_TAG_TRANSCRIBE 1u
#define PIP_TAG_PLANNING 2u
#define PIP_TAG_EGG (1u << 31) /* easter eggs: only ever picked by the rare roll in start_perf */

/* PIP's family, for the easter eggs (original designs) */
typedef enum { PIP_FORM_PIP = 0, PIP_FORM_TIN, PIP_FORM_MAINFRAME, PIP_FORM_COUNT } pip_form_t;

/* Everything the renderer needs for one frame. Units: stage pixels, degrees, seconds. */
typedef struct {
    float x, y;       /* feet position relative to PIP's home spot (y < 0 = in the air) */
    float yaw;        /* heading: 0 faces the viewer, +90 faces right (toward the text), 180 = back */
    float scale;      /* 1 = normal, ~1.7 = pressed against the glass */
    float lean;       /* head/body tilt sideways, px at the head */
    float head_dy;    /* head bob relative to the body */
    float look_x, look_y; /* eye direction -1..1 inside the visor */
    float lid;        /* 0 open .. 1 closed */
    float arm_l, arm_r;   /* deg: 0 hanging, 90 straight out, 180 straight up (screen-left / right arm) */
    float leg_l, leg_r;   /* foot lift px */
    float antenna;    /* tip sway px */
    float sit;        /* 0 standing .. 1 sitting on the floor */
    int eyes, mouth;  /* eye_style_t / mouth_t */
    int emote;        /* emote_t */
    float emote_t;    /* seconds since the emote appeared (drives its animation) */
    int held;         /* prop_t in the right hand */
    float held_t;     /* prop animation phase (s) */
    int held_l;       /* prop_t in the left hand */
    int floor_prop;   /* prop_t standing on the floor */
    float fp_x, fp_y, fp_t; /* its position (stage px) and animation phase */
    float fp_lift;    /* px above the floor while PIP carries it */
    int obj;          /* free-flying prop_t (ball in the air, paper plane, kite, balloon) */
    float obj_x, obj_y, obj_t;
    float glass;      /* 0..1: glare streaks of the screen glass (PIP pressed against it) */
    int sign;         /* sign text index when holding PROP_SIGN */
    int behind;       /* idle world: 1 = PIP is behind the message board (the board hides it) */
    float grip;       /* 0..1: hands go onto what PIP works with (laptop keys, guitar neck + strings) */
    int form;         /* pip_form_t: easter eggs swap PIP for a relative */
    float form_t;     /* that form's own animation clock */
    float puff;       /* 0..1 smoke cloud hiding a form swap */
} mascot_pose_t;

/* Idle world geometry (stage px relative to PIP's home spot; must match ui_layout.h). */
#define PIP_BOARD_DX 74.0f   /* left edge of the message board */
#define PIP_WORLD_L -72.0f   /* left edge of the screen */
#define PIP_WORLD_R 317.0f   /* right edge of the screen */
#define PIP_OFFSCREEN 40.0f  /* PIP is fully off-screen this far past an edge */

/* What the current screen wants PIP to do. */
typedef enum {
    PIP_MODE_IDLE = 0, /* Let's Focus: free play, props, attention seeking */
    PIP_MODE_LISTEN,
    PIP_MODE_THINK,
    PIP_MODE_FOCUS,    /* timer running: works next to you and keeps catching your eye */
    PIP_MODE_PAUSE,
    PIP_MODE_BREAK,
    PIP_MODE_DONE,
    PIP_MODE_AGENDA,   /* today's calendar */
    PIP_MODE_ALARM,
    PIP_MODE_CONFIRM,
    PIP_MODE_SLEEP,
    PIP_MODE_PICK,     /* voice activity picker: faces and points at the highlighted option */
    PIP_MODE_ERROR,
    PIP_MODE_COUNT
} pip_mode_t;

/* Button reactions (full-body: turns, spins, hops). */
typedef enum {
    PIP_REACT_NONE = 0,
    PIP_REACT_PRESS,  /* quick turn toward the button + look at you */
    PIP_REACT_DOUBLE, /* full 360 spin */
    PIP_REACT_HOLD,   /* leans in, hand to ear */
    PIP_REACT_BACK,   /* turns away and back (BOOT) */
    PIP_REACT_NEXT,   /* picker moved: hop toward the new option */
    PIP_REACT_COUNT
} pip_react_t;

#define MASCOT_FRAME_MS 50u            /* 20 FPS */
#define MASCOT_NO_REPEAT_MS 7200000u   /* 2 hours */
#define MASCOT_HIST 512
#define MASCOT_RECENT 16

typedef struct {
    uint8_t mode, act, variant, dir, mood;
} pip_perf_t;

typedef struct {
    uint32_t rng;
    pip_mode_t mode;
    pip_perf_t perf;            /* current performance */
    uint32_t tags;              /* scene tags (see PIP_TAG) */
    uint32_t act_start_ms, act_dur_ms;
    pip_react_t react;
    uint32_t react_start_ms;
    mascot_pose_t pose;         /* output */
    mascot_pose_t from;         /* pose at the last switch (cross-fade source) */
    /* prop trip before the current performance: PIP fetches its props from the screen edge */
    bool trip;
    uint32_t trip_start_ms, trip_ms;
    mascot_pose_t trip_from, trip_to;
    uint32_t blend_start_ms;
    uint32_t last_frame_ms;
    uint32_t next_blink_ms, blink_start_ms;
    int pick_row, pick_rows;
    /* no-repeat history (idle and focus libraries) */
    uint16_t hist_key[MASCOT_HIST];
    uint32_t hist_ms[MASCOT_HIST];
    int hist_n, hist_head;
    uint8_t recent[PIP_MODE_COUNT][MASCOT_RECENT];
    uint8_t recent_n[PIP_MODE_COUNT];
    uint32_t perf_count;
    bool started;
} mascot_anim_t;

void mascot_anim_init(mascot_anim_t *a, uint32_t seed, uint32_t now_ms);
void mascot_set_mode(mascot_anim_t *a, pip_mode_t mode, uint32_t now_ms);
/* Screen + what it is about. A tag change restarts the performance (except on the idle screen, where it only
 * steers the next pick), so PIP switches to the new activity right away - fetching its props if needed. */
void mascot_set_scene(mascot_anim_t *a, pip_mode_t mode, uint32_t tags, uint32_t now_ms);
void mascot_react(mascot_anim_t *a, pip_react_t r, uint32_t now_ms);
void mascot_set_pick(mascot_anim_t *a, int row, int rows);
/* Advance; returns true when the pose changed and the screen should be redrawn (<= 20 FPS). */
bool mascot_anim_step(mascot_anim_t *a, uint32_t now_ms);

/* ---- rig geometry (stage px, y down; floor centre = 0,0). Index 0 = screen-left part at yaw 0. ---- */
typedef struct {
    float x, y;
} pip_pt_t;

typedef struct {
    float s;                       /* scale */
    pip_pt_t foot[2];
    float leg_w, leg_len[2];       /* leg stub width and visible length */
    bool sitting;
    float bx, b_top, b_bot, bw;    /* body */
    float hx, h_top, h_bot, hw;    /* head */
    bool visor;
    float v_l, v_r, v_top, v_bot;  /* visor rectangle */
    pip_pt_t eye[2];
    float eye_w[2];
    bool eye_vis[2];
    pip_pt_t ear[2];
    float ear_z[2];                /* > 0: in front of the head */
    pip_pt_t ant_base, ant_tip;
    pip_pt_t shoulder[2], hand[2];
    float arm_z[2];                /* > 0: arm in front of the body */
    pip_pt_t chest;
    bool chest_vis;
    pip_pt_t back;                 /* back panel (visible when turned away) */
    bool back_vis;
    float face_dx;                 /* visor centre offset (mouth placement) */
} pip_rig_t;

void mascot_rig(const mascot_pose_t *p, pip_rig_t *r);

/* library introspection (tests / sim contact sheets) */
int mascot_act_count(pip_mode_t mode);
const char *mascot_act_name(pip_mode_t mode, int act);
uint32_t mascot_act_tags(pip_mode_t mode, int act); /* 0 = always eligible */
bool mascot_lib_sequential(pip_mode_t mode);        /* acts play in order (break, thinking) */
const char *mascot_activity_name(pip_activity_t a); /* "write", ... as sent by the host */
pip_activity_t mascot_activity_from_name(const char *name);
const char *mascot_mode_name(pip_mode_t mode);
uint16_t mascot_perf_key(const pip_perf_t *p);
/* Pose of a performance at time t (s) - pure; used by the engine, tests and the sim. */
void mascot_perf_pose(const pip_perf_t *p, float t, float dur, mascot_pose_t *out);
void mascot_home_pose(mascot_pose_t *p);
const char *mascot_sign_text(int idx);
/* Props: do two poses carry the same things (so PIP can go from one to the other without a trip)? */
bool mascot_same_props(const mascot_pose_t *a, const mascot_pose_t *b);
/* The trip between two poses with different props: walk to the nearest screen edge, swap, walk back. */
float mascot_trip_seconds(const mascot_pose_t *from, const mascot_pose_t *to);
void mascot_trip_pose(const mascot_pose_t *from, const mascot_pose_t *to, float t, mascot_pose_t *out);
float mascot_perf_seconds(const pip_perf_t *p);

#endif
