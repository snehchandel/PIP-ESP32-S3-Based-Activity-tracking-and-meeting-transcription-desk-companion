#ifndef UI_FONT_H
#define UI_FONT_H

#include <stdint.h>

typedef struct {
    uint32_t offset; /* into bitmap, rows packed MSB-first, ceil(w/8) bytes per row */
    uint8_t w;
    uint8_t h;
    int8_t x_off; /* from pen x */
    int8_t y_off; /* from line top (ascender line) */
    uint8_t adv;
} font_glyph_t;

typedef struct {
    uint8_t first;
    uint8_t count;
    uint8_t line_h;
    uint8_t ascent;
    const font_glyph_t *glyphs;
    const uint8_t *bits;
} font_t;

extern const font_t FONT_14;
extern const font_t FONT_16;
extern const font_t FONT_16B;
extern const font_t FONT_24B;
extern const font_t FONT_32B;
extern const font_t FONT_64;

/* Decode next UTF-8 code point and map it into the font's dense index space
 * (U+00B7 middle dot -> 127, U+2014 em dash -> 128, U+2026 ellipsis -> 129). */
int font_next_code(const char **s);

#endif
