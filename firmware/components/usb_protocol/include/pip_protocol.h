/* PIP wire protocol v1 (spec v6 section 6): framing, CRC16-CCITT-FALSE, resync parser,
 * fixed little-endian payload structs. Pure C99, shared by firmware, sim_rlcd and tests. */
#ifndef PIP_PROTOCOL_H
#define PIP_PROTOCOL_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define PIP_SYNC0 0xAA
#define PIP_SYNC1 0x55
#define PIP_PROTO_VER 0x01
#define PIP_HDR_LEN 9
#define PIP_CRC_LEN 2
#define PIP_MAX_PAYLOAD 4096
#define PIP_MAX_FRAME (PIP_HDR_LEN + PIP_MAX_PAYLOAD + PIP_CRC_LEN) /* 4107 */

#define PIP_FLAG_ACK_REQUIRED 0x01
#define PIP_FLAG_COMPRESSED 0x02
#define PIP_FLAG_IS_SIMULATOR 0x04

typedef enum {
    PIP_HEARTBEAT = 0x00,
    PIP_AUDIO_START = 0x01,
    PIP_AUDIO_DATA = 0x02,
    PIP_AUDIO_END = 0x03,
    PIP_BTN_EVENT = 0x04,
    PIP_OFFLINE_EVENTS = 0x05,
    PIP_AUTH_CHALLENGE = 0x06, /* Wi-Fi link: device -> host, 16-byte nonce + 6-byte MAC on connect */
    PIP_WAKE_EVENT = 0x07,     /* device -> host: wake word heard (u8 source 0 mic / 1 test, u8 score) */
    PIP_UI_UPDATE = 0x10,
    PIP_AUDIO_START_OUT = 0x11,
    PIP_AUDIO_DATA_OUT = 0x12,
    PIP_AUDIO_END_OUT = 0x13,
    PIP_PLAY_CHIME = 0x14,
    PIP_ALARM_TRIGGER = 0x15,
    PIP_CALENDAR_SYNC = 0x16,
    PIP_DEVICE_CONFIG = 0x17,  /* JSON: {"wifi":{"ssid","password"},"wifi_clear","token","wake":{"enabled","word"}} */
    PIP_AUTH_RESPONSE = 0x18,  /* Wi-Fi link: host -> device, HMAC-SHA256(link token, nonce) */
    PIP_OTA_BEGIN = 0x20,      /* u32 image size, 32 B sha256, 32 B version string */
    PIP_OTA_DATA = 0x21,       /* u32 offset + image bytes */
    PIP_OTA_END = 0x22,        /* verify, switch boot slot, reboot */
    PIP_WAKE_TEST = 0x23,      /* host -> device: PCM16 mono 16 kHz fed straight into the wake-word detector */
    PIP_SIM_INPUT = 0xE0, /* simulator-only extension: inject a physical button gesture */
    PIP_ACK = 0xF0,
    PIP_DIAG_REPORT = 0xFD,
    PIP_DUMP_FB = 0xFE
} pip_type_t;

typedef enum {
    PIP_ACK_OK = 0,
    PIP_ACK_BAD_VER = 1,
    PIP_ACK_BAD_LEN = 2,
    PIP_ACK_BAD_JSON = 3,
    PIP_ACK_BUSY = 4,
    PIP_ACK_UNKNOWN_TYPE = 5,
    PIP_ACK_FAILED = 6,
    PIP_ACK_DENIED = 7
} pip_ack_status_t;

typedef struct {
    uint8_t type;
    uint8_t flags;
    uint16_t seq;
    uint16_t len;
    const uint8_t *payload; /* points into parser buffer; valid until next feed */
} pip_frame_t;

typedef struct {
    uint8_t buf[PIP_MAX_FRAME];
    size_t len;
    size_t pending; /* bytes of the last returned frame, consumed on the next feed */
    uint32_t crc_errors;
    uint32_t frame_errors;
    uint32_t frames_ok;
} pip_parser_t;

uint16_t pip_crc16(const uint8_t *data, size_t len);

/* Encode a frame into out (cap >= PIP_HDR_LEN+len+2). Returns bytes written, 0 on error. */
size_t pip_encode(uint8_t type, uint8_t flags, uint16_t seq, const uint8_t *payload, uint16_t len, uint8_t *out,
                  size_t cap);

void pip_parser_init(pip_parser_t *p);
/* Feed one byte. Returns true when a complete valid frame is available in *out. The caller
 * must handle *out before the next feed. Bad sync/len/CRC drops one byte and rescans. */
bool pip_parser_feed(pip_parser_t *p, uint8_t byte, pip_frame_t *out);
/* Inter-frame idle resync: call when the line has been idle (e.g. >= 20 ms) while a partial
 * frame is buffered. Drops one byte and rescans, so a frame swallowed by a corrupted LEN is
 * recovered without waiting for more traffic. Returns true if a frame became available. */
bool pip_parser_idle(pip_parser_t *p, pip_frame_t *out);

/* ---- fixed payload structs (little-endian, packed manually) ---- */
typedef struct {
    uint8_t proto_ver, link_mode;
    uint16_t flags;
    uint32_t uptime_s, utc_epoch_s, state_rev;
} pip_heartbeat_t; /* 16 B */

typedef struct {
    uint32_t event_seq;
    uint8_t btn_id;  /* 0 KEY, 1 BOOT */
    uint8_t gesture; /* 1 SHORT 2 DOUBLE 3 HOLD_START 4 HOLD_END 5 RESCUE */
    uint16_t reserved;
    uint32_t ts_ms;
} pip_btn_event_t; /* 12 B */

typedef struct {
    uint32_t stream_id;
    uint16_t sample_rate_hz;
    uint8_t channels, bits_per_sample;
    uint16_t max_sec, reserved;
} pip_audio_start_t; /* 12 B */

typedef struct {
    uint32_t stream_id;
    uint8_t reason, truncated;
    uint16_t reserved;
    uint32_t total_samples;
} pip_audio_end_t; /* 12 B */

typedef struct {
    uint16_t ref_seq;
    uint8_t status, detail;
    uint16_t rsv;
} pip_ack_t; /* 6 B */

typedef struct {
    uint8_t chime_id, volume_pct, status, rsv;
} pip_chime_t; /* 4 B */

typedef struct {
    uint8_t btn_id;   /* 0 KEY, 1 BOOT */
    uint8_t action;   /* 0 short, 1 double, 2 hold */
    uint16_t hold_ms; /* for action=2 */
} pip_sim_input_t;    /* 4 B */

#define PIP_FB_CHUNKS 4
#define PIP_FB_CHUNK_BYTES 3750
#define PIP_FB_CHUNK_PAYLOAD (4 + PIP_FB_CHUNK_BYTES) /* idx, total, offset u16 */

size_t pip_pack_heartbeat(const pip_heartbeat_t *h, uint8_t *out);
bool pip_unpack_heartbeat(const uint8_t *p, size_t n, pip_heartbeat_t *h);
size_t pip_pack_btn_event(const pip_btn_event_t *e, uint8_t *out);
bool pip_unpack_btn_event(const uint8_t *p, size_t n, pip_btn_event_t *e);
size_t pip_pack_audio_start(const pip_audio_start_t *a, uint8_t *out);
size_t pip_pack_audio_end(const pip_audio_end_t *a, uint8_t *out);
size_t pip_pack_ack(const pip_ack_t *a, uint8_t *out);
bool pip_unpack_ack(const uint8_t *p, size_t n, pip_ack_t *a);
bool pip_unpack_chime(const uint8_t *p, size_t n, pip_chime_t *c);
bool pip_unpack_sim_input(const uint8_t *p, size_t n, pip_sim_input_t *s);
/* DUMP_FB chunk payload: [idx][total=4][offset u16 LE][3750 bytes] */
size_t pip_pack_fb_chunk(uint8_t idx, const uint8_t *fb15000, uint8_t *out);

#endif
