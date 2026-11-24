#ifndef UI_RENDER_H
#define UI_RENDER_H

#include "rlcd_fb.h"
#include "ui_draw.h"
#include "ui_model.h"

#define UI_META_MAX 20

typedef struct {
    const char *name;
    ui_rect_t r;
    int parent; /* index of enclosing box or -1 (nested boxes may overlap their parent) */
} ui_box_t;

typedef struct {
    ui_screen_t screen;
    int n;
    ui_box_t boxes[UI_META_MAX];
} ui_meta_t;

/* Render the full screen for model `m`. `meta` may be NULL (device build). */
void ui_render(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);

/* internal helpers shared by screen files */
int ui_meta_add(ui_meta_t *meta, const char *name, int x, int y, int w, int h, int parent);
void ui_chrome_top(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_chrome_mascot(rlcd_fb_t *fb, const ui_model_t *m, int expr, const char *label, ui_meta_t *meta);
/* Where PIP lives on a screen: clip window + home spot (feet centre). */
typedef struct {
    int x, y, w, h;
    int cx, fy;
    int text_x; /* emotes keep left of this x so they never cover text (0 = no limit) */
} ui_stage_t;
extern const ui_stage_t UI_STAGE_COLUMN; /* left column next to the text (most screens) */
extern const ui_stage_t UI_STAGE_WORLD;  /* the whole area between header and bar (idle) */
/* the stage being drawn (props read it for clipping-aware effects) */
const ui_stage_t *ui_stage_current(void);
void ui_draw_mascot(rlcd_fb_t *fb, const mascot_pose_t *pose); /* column stage */
void ui_draw_mascot_on(rlcd_fb_t *fb, const mascot_pose_t *pose, const ui_stage_t *st);
/* Compose one frame of a slide between two full screens: rows [y0, y1) move, the rest show `to`.
 * dir: 1 = new screen enters from the right, -1 = from the left, 2 = drops in from the top, -2 = old
 * screen lifts away upward. u = eased progress 0..1. `out` may alias neither input. */
void ui_slide_compose(rlcd_fb_t *out, const rlcd_fb_t *from, const rlcd_fb_t *to, int dir, float u, int y0, int y1);
/* Slide direction for a screen change (0 = switch instantly). */
int ui_slide_dir(ui_screen_t from, ui_screen_t to);
void ui_weather_icon(rlcd_fb_t *fb, int x, int y, int code, uint32_t ms);
typedef struct {
    int icon; /* ui_icon_t or -1 */
    const char *label;
} ui_hint_t;
void ui_chrome_bar(rlcd_fb_t *fb, const ui_model_t *m, const ui_hint_t *hints, int n, ui_meta_t *meta);
void ui_progress(rlcd_fb_t *fb, int x, int y, int w, int h, uint32_t done, uint32_t total, ui_meta_t *meta);
void ui_fmt_mmss(char *out, uint32_t ms);
void ui_inverted_pill(rlcd_fb_t *fb, const font_t *f, int x, int y, const char *s, ui_meta_t *meta,
                      const char *name);

void ui_screen_idle(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_listening(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_thinking(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_focus(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_paused(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_break(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_done(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_daily(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_alarm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_confirm(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_sleep(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_voice_pick(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);
void ui_screen_error(rlcd_fb_t *fb, const ui_model_t *m, ui_meta_t *meta);

#endif
