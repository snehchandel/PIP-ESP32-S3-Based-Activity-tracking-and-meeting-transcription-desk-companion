#ifndef UI_ICONS_H
#define UI_ICONS_H

#include <stdint.h>

#define UI_ICON_SIZE 18
#define UI_ICON_STRIDE 3

typedef enum {
    ICON_ARROW = 0,
    ICON_CHECK,
    ICON_PAUSE,
    ICON_PLAY,
    ICON_CYCLE,
    ICON_LINK,
    ICON_LINK_OFF,
    ICON_BELL,
    ICON_MIC,
    ICON_HOME,
    ICON_SUN, /* weather icons in out_code order: 0 sun .. 5 fog */
    ICON_CLOUD,
    ICON_RAIN,
    ICON_SNOW,
    ICON_STORM,
    ICON_FOG,
    ICON_WARN,
    UI_ICON_COUNT
} ui_icon_t;

extern const uint8_t ui_icons[UI_ICON_COUNT][UI_ICON_SIZE * UI_ICON_STRIDE];

#endif
