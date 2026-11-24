/* Protocol v1: CRC16-CCITT-FALSE vectors, framing, resync, payload struct sizes. */
#include <string.h>

#include "pip_protocol.h"
#include "tinytest.h"

static int feed_all(pip_parser_t *p, const uint8_t *b, size_t n, pip_frame_t *frames, uint8_t (*payloads)[PIP_MAX_PAYLOAD],
                    int max)
{
    int got = 0;
    for (size_t i = 0; i < n; i++) {
        pip_frame_t f;
        if (pip_parser_feed(p, b[i], &f) && got < max) {
            frames[got] = f;
            memcpy(payloads[got], f.payload, f.len);
            got++;
        }
    }
    return got;
}

static uint8_t payloads[4][PIP_MAX_PAYLOAD];

int main(void)
{
    CHECK_EQ(pip_crc16((const uint8_t *)"123456789", 9), 0x29B1);
    CHECK_EQ(pip_crc16(NULL, 0), 0xFFFF);
    CHECK_EQ(PIP_MAX_FRAME, 4107);
    CHECK(PIP_FB_CHUNK_PAYLOAD <= PIP_MAX_PAYLOAD);
    CHECK_EQ(PIP_FB_CHUNKS * PIP_FB_CHUNK_BYTES, 15000);

    /* golden vector shared with the Python implementation (tests/protocol) */
    uint8_t out[PIP_MAX_FRAME];
    const uint8_t hello[] = {'h', 'i'};
    size_t n = pip_encode(PIP_HEARTBEAT, PIP_FLAG_ACK_REQUIRED, 0x1234, hello, 2, out, sizeof out);
    CHECK_EQ(n, 13);
    const uint8_t golden[] = {0xAA, 0x55, 0x01, 0x00, 0x01, 0x34, 0x12, 0x02, 0x00, 'h', 'i'};
    CHECK(memcmp(out, golden, sizeof golden) == 0);
    uint16_t crc = pip_crc16(out + 2, 9);
    CHECK_EQ(out[11], crc & 0xFF);
    CHECK_EQ(out[12], crc >> 8);

    /* roundtrip with garbage prefix, a corrupted frame, then a good one */
    uint8_t stream[64];
    size_t k = 0;
    stream[k++] = 0x00;
    stream[k++] = 0xAA;
    stream[k++] = 0x13;
    memcpy(stream + k, out, n);
    stream[k + 10] ^= 0xFF; /* corrupt payload of the first copy */
    k += n;
    memcpy(stream + k, out, n);
    k += n;
    pip_parser_t p;
    pip_parser_init(&p);
    pip_frame_t frames[4];
    int got = feed_all(&p, stream, k, frames, payloads, 4);
    CHECK_EQ(got, 1);
    CHECK_EQ(frames[0].seq, 0x1234);
    CHECK_EQ(frames[0].len, 2);
    CHECK(memcmp(payloads[0], "hi", 2) == 0);
    CHECK_EQ(p.crc_errors, 1);

    /* back-to-back frames */
    pip_parser_init(&p);
    uint8_t two[64];
    size_t a = pip_encode(PIP_ACK, 0, 1, NULL, 0, two, sizeof two);
    size_t b = pip_encode(PIP_DUMP_FB, 0, 2, NULL, 0, two + a, sizeof two - a);
    got = feed_all(&p, two, a + b, frames, payloads, 4);
    CHECK_EQ(got, 2);
    CHECK_EQ(frames[1].type, PIP_DUMP_FB);

    /* LEN > 4096 is rejected and the parser resyncs */
    pip_parser_init(&p);
    uint8_t bad[] = {0xAA, 0x55, 0x01, 0x10, 0x00, 0x00, 0x00, 0x01, 0x10};
    got = feed_all(&p, bad, sizeof bad, frames, payloads, 4);
    CHECK_EQ(got, 0);
    CHECK(p.frame_errors >= 1);
    got = feed_all(&p, out, n, frames, payloads, 4);
    CHECK_EQ(got, 1);
    CHECK(pip_encode(0, 0, 0, out, PIP_MAX_PAYLOAD + 1, out, sizeof out) == 0);

    /* fixed payload sizes and roundtrips */
    uint8_t buf[32];
    pip_heartbeat_t h = {1, 1, 3, 100, 1763900000u, 42}, h2;
    CHECK_EQ(pip_pack_heartbeat(&h, buf), 16);
    CHECK(pip_unpack_heartbeat(buf, 16, &h2) && h2.utc_epoch_s == 1763900000u && h2.state_rev == 42);
    pip_btn_event_t e = {7, 1, 5, 0, 123456}, e2;
    CHECK_EQ(pip_pack_btn_event(&e, buf), 12);
    CHECK(pip_unpack_btn_event(buf, 12, &e2) && e2.gesture == 5 && e2.ts_ms == 123456);
    pip_audio_start_t as = {9, 16000, 1, 16, 60, 0};
    CHECK_EQ(pip_pack_audio_start(&as, buf), 12);
    CHECK_EQ(buf[4] | (buf[5] << 8), 16000);
    pip_audio_end_t ae = {9, 1, 0, 0, 32000};
    CHECK_EQ(pip_pack_audio_end(&ae, buf), 12);
    pip_ack_t ak = {0xBEEF, 3, 0, 0}, ak2;
    CHECK_EQ(pip_pack_ack(&ak, buf), 6);
    CHECK(pip_unpack_ack(buf, 6, &ak2) && ak2.ref_seq == 0xBEEF && ak2.status == 3);

    static uint8_t fb[15000];
    for (int i = 0; i < 15000; i++) {
        fb[i] = (uint8_t)i;
    }
    static uint8_t chunk[PIP_FB_CHUNK_PAYLOAD];
    CHECK_EQ(pip_pack_fb_chunk(3, fb, chunk), 3754);
    CHECK_EQ(chunk[0], 3);
    CHECK_EQ(chunk[1], 4);
    CHECK_EQ(chunk[2] | (chunk[3] << 8), 11250);
    CHECK_EQ(chunk[4], (uint8_t)11250);
    TT_DONE();
}
