/* Layout constants for the 400x300 logical canvas.
 * Header (big clock + weather) | left: PIP's stage with an isometric floor | right: text | inverted status bar. */
#ifndef UI_LAYOUT_H
#define UI_LAYOUT_H

#define UI_MARGIN 8

#define TOPBAR_Y 3
#define TOPBAR_RULE_Y 34 /* taller header so the clock reads from across the desk */
#define ZONE_TOP 36

/* PIP's stage: everything PIP draws is clipped to this column */
#define STAGE_X 4
#define STAGE_W 144
#define STAGE_CX 76  /* floor centre */
#define STAGE_FY 220

/* legacy names: the region tests/tools sample for "is PIP visible" */
#define MASCOT_X STAGE_X
#define MASCOT_Y (ZONE_TOP + 2)
#define MASCOT_W STAGE_W
#define MASCOT_H (BAR_Y - ZONE_TOP - 4)

#define CONTENT_X 154
#define CONTENT_Y 42
#define CONTENT_R 392
#define CONTENT_W (CONTENT_R - CONTENT_X)
#define CONTENT_B 256

#define BAR_Y 264
#define BAR_H 36

#endif
