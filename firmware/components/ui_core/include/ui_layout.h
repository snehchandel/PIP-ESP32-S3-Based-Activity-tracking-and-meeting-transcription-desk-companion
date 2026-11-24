/* Layout constants for the 400x300 logical canvas (spec v6 section 4.3). */
#ifndef UI_LAYOUT_H
#define UI_LAYOUT_H

#define UI_MARGIN 8

#define TOPBAR_Y 3
#define TOPBAR_RULE_Y 24
#define ZONE_TOP 26

#define MASCOT_X 16
#define MASCOT_Y 70 /* vertically centred against the text column (no separate stage) */
#define MASCOT_W 120
#define MASCOT_H 120
#define GROUND_Y 164
#define PILL_Y 180
#define PILL_H 21

#define CONTENT_X 150
#define CONTENT_Y 34
#define CONTENT_R 388
#define CONTENT_W (CONTENT_R - CONTENT_X)
#define CONTENT_B 248

#define BAR_Y 264
#define BAR_H 36

#endif
