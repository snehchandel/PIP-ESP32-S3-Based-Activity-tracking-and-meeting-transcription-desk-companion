/* ST7305 reflective LCD flush driver. The portable ui_core draws in logical 400x300
 * landscape (bit 1 = black); rotation into the panel's 300x400 RAM layout and polarity
 * inversion (panel bit 1 = white) happen only here. */
#ifndef RLCD_DISPLAY_H
#define RLCD_DISPLAY_H

#include "esp_err.h"
#include "rlcd_fb.h"

esp_err_t rlcd_display_init(void);
esp_err_t rlcd_display_flush(const rlcd_fb_t *fb);
/* Pure conversion (exposed for tests): logical fb -> panel RAM image (15000 B). */
void rlcd_display_convert(const rlcd_fb_t *fb, uint8_t *panel);

#endif
