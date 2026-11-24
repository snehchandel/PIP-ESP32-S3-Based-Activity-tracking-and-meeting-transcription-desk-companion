/* Logical 400x300 1-bit framebuffer: row-major, 50 bytes/row, MSB = leftmost pixel,
 * bit 1 = black ink, bit 0 = white paper. Rotation/polarity happen only in the panel flush. */
#ifndef RLCD_FB_H
#define RLCD_FB_H

#include <stdint.h>

#define RLCD_W 400
#define RLCD_H 300
#define RLCD_STRIDE (RLCD_W / 8)
#define RLCD_FB_BYTES (RLCD_STRIDE * RLCD_H)

typedef struct {
    uint8_t px[RLCD_FB_BYTES];
} rlcd_fb_t;

typedef char rlcd_fb_size_guard_t[(sizeof(rlcd_fb_t) == 15000) ? 1 : -1];

typedef enum { INK_WHITE = 0, INK_BLACK = 1 } ink_t;

#endif
