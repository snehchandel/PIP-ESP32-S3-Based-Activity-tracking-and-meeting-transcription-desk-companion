/* Layout constants for the 400x300 logical canvas.
 * Header (big clock + weather) | PIP's world | inverted status bar.
 * On the idle "Let's Focus" screen PIP roams the whole world and the text sits on a free-standing message
 * board it can walk behind, lean on and play around. Every other screen keeps PIP in the left stage column
 * next to the text column. */
#ifndef UI_LAYOUT_H
#define UI_LAYOUT_H

#define UI_MARGIN 8

#define TOPBAR_Y 3
#define TOPBAR_RULE_Y 34 /* taller header so the clock reads from across the desk */
#define ZONE_TOP 36

/* PIP's stage column (every screen but idle): everything PIP draws is clipped to it */
#define STAGE_X 4
#define STAGE_W 144
#define STAGE_CX 76  /* PIP's home: feet centre */
#define STAGE_FY 236 /* feet line, the same on every screen so PIP stays put while screens slide */
#define FLOOR_Y (STAGE_FY + 4)

/* idle world: the full width between the 4 px safe margins */
#define WORLD_X 4
#define WORLD_W (400 - 8)

/* idle message board (PIP_BOARD_DX in mascot.h = BOARD_X - STAGE_CX) */
#define BOARD_X 150
#define BOARD_R 393
#define BOARD_Y 40
#define BOARD_B 194 /* PIP's body and legs stay visible under the board when it walks behind */
#define BOARD_PAD 9

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

/* screen-to-screen slide transitions */
#define SLIDE_MS 420u
#define SLIDE_V_MS 360u
#define SLIDE_FRAME_MS 40u

#endif
