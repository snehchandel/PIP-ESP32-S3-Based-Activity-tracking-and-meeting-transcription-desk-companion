/* Minimal dependency-free 1-bit grayscale PNG writer (stored deflate blocks). */
#include "png_write.h"

#include <stdio.h>
#include <string.h>

static uint32_t crc_table[256];

static void crc_init(void)
{
    for (uint32_t n = 0; n < 256; n++) {
        uint32_t c = n;
        for (int k = 0; k < 8; k++) {
            c = (c & 1u) ? 0xEDB88320u ^ (c >> 1) : c >> 1;
        }
        crc_table[n] = c;
    }
}

static uint32_t crc_update(uint32_t c, const uint8_t *buf, size_t len)
{
    for (size_t i = 0; i < len; i++) {
        c = crc_table[(c ^ buf[i]) & 0xFFu] ^ (c >> 8);
    }
    return c;
}

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)(v >> 24);
    p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);
    p[3] = (uint8_t)v;
}

static void chunk(FILE *f, const char *type, const uint8_t *data, uint32_t len)
{
    uint8_t hdr[8];
    put_u32(hdr, len);
    memcpy(hdr + 4, type, 4);
    fwrite(hdr, 1, 8, f);
    if (len) {
        fwrite(data, 1, len, f);
    }
    uint32_t c = crc_update(0xFFFFFFFFu, (const uint8_t *)type, 4);
    c = crc_update(c, data, len) ^ 0xFFFFFFFFu;
    uint8_t cb[4];
    put_u32(cb, c);
    fwrite(cb, 1, 4, f);
}

int png_write_fb(const char *path, const rlcd_fb_t *fb)
{
    static uint8_t raw[RLCD_H * (RLCD_STRIDE + 1)];
    static uint8_t z[sizeof raw + 64];
    crc_init();
    size_t n = 0;
    for (int y = 0; y < RLCD_H; y++) {
        raw[n++] = 0; /* filter: none */
        for (int b = 0; b < RLCD_STRIDE; b++) {
            raw[n++] = (uint8_t)~fb->px[y * RLCD_STRIDE + b]; /* PNG gray: 1 = white */
        }
    }
    size_t zn = 0;
    z[zn++] = 0x78;
    z[zn++] = 0x01;
    size_t off = 0;
    while (off < n) {
        size_t blk = n - off > 65535 ? 65535 : n - off;
        z[zn++] = (off + blk == n) ? 1 : 0;
        z[zn++] = (uint8_t)(blk & 0xFF);
        z[zn++] = (uint8_t)(blk >> 8);
        z[zn++] = (uint8_t)(~blk & 0xFF);
        z[zn++] = (uint8_t)((~blk >> 8) & 0xFF);
        memcpy(z + zn, raw + off, blk);
        zn += blk;
        off += blk;
    }
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < n; i++) {
        a = (a + raw[i]) % 65521u;
        b = (b + a) % 65521u;
    }
    put_u32(z + zn, (b << 16) | a);
    zn += 4;

    FILE *f = fopen(path, "wb");
    if (!f) {
        return -1;
    }
    static const uint8_t sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    fwrite(sig, 1, 8, f);
    uint8_t ihdr[13];
    put_u32(ihdr, RLCD_W);
    put_u32(ihdr + 4, RLCD_H);
    ihdr[8] = 1;  /* bit depth */
    ihdr[9] = 0;  /* grayscale */
    ihdr[10] = 0;
    ihdr[11] = 0;
    ihdr[12] = 0;
    chunk(f, "IHDR", ihdr, 13);
    chunk(f, "IDAT", z, (uint32_t)zn);
    chunk(f, "IEND", NULL, 0);
    fclose(f);
    return 0;
}
