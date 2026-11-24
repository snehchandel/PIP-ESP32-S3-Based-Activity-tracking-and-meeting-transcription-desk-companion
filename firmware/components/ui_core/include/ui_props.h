/* PIP's props: things on the isometric floor, in its hands, or flying around the stage. */
#ifndef UI_PROPS_H
#define UI_PROPS_H

#include <stdbool.h>

#include "mascot.h"
#include "rlcd_fb.h"

/* (x, y) = screen position of the prop's footprint on the floor */
void ui_prop_floor(rlcd_fb_t *fb, const mascot_pose_t *p, float x, float y);
/* props in PIP's hands; `two_handed_pass` draws the ones held in front of the body (before the near arm) */
void ui_prop_held(rlcd_fb_t *fb, const mascot_pose_t *p, const pip_rig_t *r, int cx, int fy, bool two_handed_pass);
void ui_prop_flying(rlcd_fb_t *fb, const mascot_pose_t *p, const pip_rig_t *r, int cx, int fy);
/* isometric cube standing on (x, y); a = half width */
void ui_iso_cube(rlcd_fb_t *fb, float x, float y, float a, bool ribbon);

#endif
