/* Monotonic countdown, pause/resume, rescue split and 32-entry offline event queue (C99). */
#ifndef LOCAL_TIMER_H
#define LOCAL_TIMER_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef enum { LT_STOPPED = 0, LT_RUNNING = 1, LT_PAUSED = 2 } lt_state_t; /* == timer_state_t */

typedef struct {
    lt_state_t state;
    uint32_t remaining_ms;
    uint32_t total_ms;
    uint32_t last_ms; /* monotonic timestamp of last accounting */
} local_timer_t;

void lt_load(local_timer_t *t, uint32_t remaining_ms, uint32_t total_ms, lt_state_t state, uint32_t now_ms);
void lt_start(local_timer_t *t, uint32_t now_ms); /* start or resume */
void lt_pause(local_timer_t *t, uint32_t now_ms);
void lt_stop(local_timer_t *t);
/* Account elapsed time; returns true exactly once when a running timer reaches zero. */
bool lt_tick(local_timer_t *t, uint32_t now_ms);

/* Rescue "cut step in half": current = max(120, floor(rem/2)); next = max(120, rem - current).
 * Original work is never deleted: current + next >= remaining. */
void lt_split_calc(uint32_t remaining_sec, uint32_t *current_sec, uint32_t *next_sec);

#define OEV_CAPACITY 32

typedef enum { OEV_STEP_COMPLETE = 1, OEV_STEP_SPLIT = 2, OEV_TIMER_DELTA = 3, OEV_ALARM_ACK = 4 } oev_kind_t;

typedef struct {
    uint32_t seq;
    uint8_t kind;
    char ref_id[24]; /* step_id or alarm_id */
    uint32_t remaining_ms;
    uint32_t ts_epoch;
} oev_t;

typedef struct {
    oev_t ev[OEV_CAPACITY];
    uint8_t head;
    uint8_t count;
    uint32_t next_seq;
    uint32_t dropped;
} oev_queue_t;

void oev_init(oev_queue_t *q);
/* Append. When full, the oldest TIMER_DELTA is evicted first (it is superseded by later
 * state), otherwise the oldest entry; `dropped` counts evictions. */
void oev_push(oev_queue_t *q, oev_kind_t kind, const char *ref_id, uint32_t remaining_ms, uint32_t ts_epoch);
const oev_t *oev_at(const oev_queue_t *q, uint8_t i);
/* Serialize as the OFFLINE_EVENTS JSON array. Returns bytes written (0 if cap too small). */
size_t oev_to_json(const oev_queue_t *q, uint32_t boot_id, char *out, size_t cap);
void oev_clear(oev_queue_t *q);
const char *oev_kind_name(uint8_t kind);

#endif
