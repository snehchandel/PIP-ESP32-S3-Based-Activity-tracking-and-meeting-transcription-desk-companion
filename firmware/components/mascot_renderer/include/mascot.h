/* PIP mascot: canonical 8 expressions + 2 FPS blink controller (pure C99). */
#ifndef PIP_MASCOT_H
#define PIP_MASCOT_H

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

#define MASCOT_FRAME_MS 500u     /* 2 FPS max */
#define MASCOT_BLINK_PERIOD 8u   /* one blink frame every 8 frames (4 s) */

/* 120x120, 15 bytes/row, MSB-first, bit 1 = black. */
const uint8_t *mascot_bits(pip_expr_t e, uint8_t blink_phase);
/* Blink only animates READY and WORKING; returns 1 on the blink frame. */
uint8_t mascot_blink_phase(pip_expr_t e, uint32_t now_ms);
const char *mascot_expr_name(pip_expr_t e);

#endif
