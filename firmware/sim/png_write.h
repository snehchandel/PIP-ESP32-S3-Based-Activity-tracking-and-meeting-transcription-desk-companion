#ifndef PNG_WRITE_H
#define PNG_WRITE_H

#include "rlcd_fb.h"

/* Write the logical framebuffer as an exact 400x300 1-bit grayscale PNG. */
int png_write_fb(const char *path, const rlcd_fb_t *fb);

#endif
