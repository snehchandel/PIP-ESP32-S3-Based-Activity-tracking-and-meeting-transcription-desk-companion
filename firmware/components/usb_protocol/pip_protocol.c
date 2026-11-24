#include "pip_protocol.h"

#include <string.h>

uint16_t pip_crc16(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFF;
    for (size_t i = 0; i < len; i++) {
        crc = (uint16_t)(crc ^ (uint16_t)((unsigned)data[i] << 8u));
        for (int b = 0; b < 8; b++) {
            crc = (crc & 0x8000u) ? (uint16_t)(((unsigned)crc << 1u) ^ 0x1021u) : (uint16_t)((unsigned)crc << 1u);
        }
    }
    return crc;
}

static void w16(uint8_t *p, uint16_t v)
{
    p[0] = (uint8_t)(v & 0xFF);
    p[1] = (uint8_t)(v >> 8);
}

static void w32(uint8_t *p, uint32_t v)
{
    for (int i = 0; i < 4; i++) {
        p[i] = (uint8_t)(v >> (8 * i));
    }
}

static uint16_t r16(const uint8_t *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t r32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

size_t pip_encode(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len, uint8_t *out,
                  size_t cap)
{
    size_t total = PIP_HDR_LEN + (size_t)len + PIP_CRC_LEN;
    if (len > PIP_MAX_PAYLOAD || cap < total || (len && !payload)) {
        return 0;
    }
    out[0] = PIP_SYNC0;
    out[1] = PIP_SYNC1;
    out[2] = PIP_PROTO_VER;
    out[3] = type;
    out[4] = flags;
    w16(out + 5, seq);
    w16(out + 7, len);
    if (len) {
        memmove(out + PIP_HDR_LEN, payload, len);
    }
    w16(out + PIP_HDR_LEN + len, pip_crc16(out + 2, PIP_HDR_LEN - 2 + (size_t)len));
    return total;
}

void pip_parser_init(pip_parser_t *p) { memset(p, 0, sizeof *p); }

static void drop(pip_parser_t *p, size_t n)
{
    if (n >= p->len) {
        p->len = 0;
        return;
    }
    memmove(p->buf, p->buf + n, p->len - n);
    p->len -= n;
}

/* Try to extract one frame from the buffer head. Returns 1 ok, 0 need more, -1 dropped byte. */
static int try_frame(pip_parser_t *p, pip_frame_t *out)
{
    if (p->len >= 1 && p->buf[0] != PIP_SYNC0) {
        drop(p, 1);
        return -1;
    }
    if (p->len >= 2 && p->buf[1] != PIP_SYNC1) {
        p->frame_errors++;
        drop(p, 1);
        return -1;
    }
    if (p->len < PIP_HDR_LEN) {
        return 0;
    }
    uint16_t len = r16(p->buf + 7);
    if (p->buf[2] != PIP_PROTO_VER || len > PIP_MAX_PAYLOAD) {
        p->frame_errors++;
        drop(p, 1);
        return -1;
    }
    size_t total = PIP_HDR_LEN + (size_t)len + PIP_CRC_LEN;
    if (p->len < total) {
        return 0;
    }
    uint16_t want = r16(p->buf + PIP_HDR_LEN + len);
    if (pip_crc16(p->buf + 2, PIP_HDR_LEN - 2 + (size_t)len) != want) {
        p->crc_errors++;
        drop(p, 1);
        return -1;
    }
    out->type = p->buf[3];
    out->flags = p->buf[4];
    out->seq = r16(p->buf + 5);
    out->len = len;
    out->payload = p->buf + PIP_HDR_LEN;
    p->pending = total;
    p->frames_ok++;
    return 1;
}

bool pip_parser_feed(pip_parser_t *p, uint8_t byte, pip_frame_t *out)
{
    if (p->pending) { /* previously returned frame still at buffer head */
        drop(p, p->pending);
        p->pending = 0;
    }
    if (p->len >= sizeof p->buf) {
        drop(p, 1);
    }
    p->buf[p->len++] = byte;
    for (;;) {
        int r = try_frame(p, out);
        if (r == 1) {
            return true;
        }
        if (r == 0 || p->len == 0) {
            return false;
        }
    }
}

size_t pip_pack_heartbeat(const pip_heartbeat_t *h, uint8_t *o)
{
    o[0] = h->proto_ver;
    o[1] = h->link_mode;
    w16(o + 2, h->flags);
    w32(o + 4, h->uptime_s);
    w32(o + 8, h->utc_epoch_s);
    w32(o + 12, h->state_rev);
    return 16;
}

bool pip_unpack_heartbeat(const uint8_t *p, size_t n, pip_heartbeat_t *h)
{
    if (n != 16) {
        return false;
    }
    h->proto_ver = p[0];
    h->link_mode = p[1];
    h->flags = r16(p + 2);
    h->uptime_s = r32(p + 4);
    h->utc_epoch_s = r32(p + 8);
    h->state_rev = r32(p + 12);
    return true;
}

size_t pip_pack_btn_event(const pip_btn_event_t *e, uint8_t *o)
{
    w32(o, e->event_seq);
    o[4] = e->btn_id;
    o[5] = e->gesture;
    w16(o + 6, e->reserved);
    w32(o + 8, e->ts_ms);
    return 12;
}

bool pip_unpack_btn_event(const uint8_t *p, size_t n, pip_btn_event_t *e)
{
    if (n != 12) {
        return false;
    }
    e->event_seq = r32(p);
    e->btn_id = p[4];
    e->gesture = p[5];
    e->reserved = r16(p + 6);
    e->ts_ms = r32(p + 8);
    return true;
}

size_t pip_pack_audio_start(const pip_audio_start_t *a, uint8_t *o)
{
    w32(o, a->stream_id);
    w16(o + 4, a->sample_rate_hz);
    o[6] = a->channels;
    o[7] = a->bits_per_sample;
    w16(o + 8, a->max_sec);
    w16(o + 10, a->reserved);
    return 12;
}

size_t pip_pack_audio_end(const pip_audio_end_t *a, uint8_t *o)
{
    w32(o, a->stream_id);
    o[4] = a->reason;
    o[5] = a->truncated;
    w16(o + 6, a->reserved);
    w32(o + 8, a->total_samples);
    return 12;
}

size_t pip_pack_ack(const pip_ack_t *a, uint8_t *o)
{
    w16(o, a->ref_seq);
    o[2] = a->status;
    o[3] = a->detail;
    w16(o + 4, a->rsv);
    return 6;
}

bool pip_unpack_ack(const uint8_t *p, size_t n, pip_ack_t *a)
{
    if (n != 6) {
        return false;
    }
    a->ref_seq = r16(p);
    a->status = p[2];
    a->detail = p[3];
    a->rsv = r16(p + 4);
    return true;
}

bool pip_unpack_chime(const uint8_t *p, size_t n, pip_chime_t *c)
{
    if (n != 4) {
        return false;
    }
    c->chime_id = p[0];
    c->volume_pct = p[1];
    c->status = p[2];
    c->rsv = p[3];
    return true;
}

bool pip_unpack_sim_input(const uint8_t *p, size_t n, pip_sim_input_t *s)
{
    if (n != 4) {
        return false;
    }
    s->btn_id = p[0];
    s->action = p[1];
    s->hold_ms = r16(p + 2);
    return true;
}

size_t pip_pack_fb_chunk(uint8_t idx, const uint8_t *fb, uint8_t *o)
{
    uint16_t off = (uint16_t)(idx * PIP_FB_CHUNK_BYTES);
    o[0] = idx;
    o[1] = PIP_FB_CHUNKS;
    w16(o + 2, off);
    memcpy(o + 4, fb + off, PIP_FB_CHUNK_BYTES);
    return PIP_FB_CHUNK_PAYLOAD;
}
