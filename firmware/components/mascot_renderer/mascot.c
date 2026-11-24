#include "mascot.h"

#include "pip_sprites.h"

typedef char pip_sprite_count_guard_t[(PIP_SPRITE_COUNT == 10) ? 1 : -1];

const uint8_t *mascot_bits(pip_expr_t e, uint8_t blink_phase)
{
    if ((unsigned)e >= PIP_EXPR_COUNT) {
        e = PIP_EXPR_READY;
    }
    if (blink_phase) {
        if (e == PIP_EXPR_READY) {
            return pip_sprites[PIP_SPRITE_READY_BLINK];
        }
        if (e == PIP_EXPR_WORKING) {
            return pip_sprites[PIP_SPRITE_WORKING_BLINK];
        }
    }
    return pip_sprites[e];
}

uint8_t mascot_blink_phase(pip_expr_t e, uint32_t now_ms)
{
    if (e != PIP_EXPR_READY && e != PIP_EXPR_WORKING) {
        return 0;
    }
    uint32_t frame = now_ms / MASCOT_FRAME_MS;
    return (frame % MASCOT_BLINK_PERIOD) == (MASCOT_BLINK_PERIOD - 1) ? 1 : 0;
}

const char *mascot_expr_name(pip_expr_t e)
{
    static const char *const names[PIP_EXPR_COUNT] = {"READY",  "LISTENING", "THINKING", "WORKING",
                                                      "PAUSED", "DONE",      "ALARM",    "SLEEP"};
    return (unsigned)e < PIP_EXPR_COUNT ? names[e] : "READY";
}
