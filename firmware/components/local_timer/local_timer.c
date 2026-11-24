#include "local_timer.h"

#include <stdio.h>
#include <string.h>

void lt_load(local_timer_t *t, uint32_t remaining_ms, uint32_t total_ms, lt_state_t state, uint32_t now_ms)
{
    t->remaining_ms = remaining_ms;
    t->total_ms = total_ms ? total_ms : remaining_ms;
    t->state = remaining_ms == 0 && state == LT_RUNNING ? LT_STOPPED : state;
    t->last_ms = now_ms;
}

void lt_start(local_timer_t *t, uint32_t now_ms)
{
    if (t->remaining_ms > 0) {
        t->state = LT_RUNNING;
        t->last_ms = now_ms;
    }
}

void lt_pause(local_timer_t *t, uint32_t now_ms)
{
    if (t->state == LT_RUNNING) {
        lt_tick(t, now_ms);
        if (t->remaining_ms > 0) {
            t->state = LT_PAUSED;
        }
    }
}

void lt_stop(local_timer_t *t) { t->state = LT_STOPPED; }

bool lt_tick(local_timer_t *t, uint32_t now_ms)
{
    if (t->state != LT_RUNNING) {
        t->last_ms = now_ms;
        return false;
    }
    uint32_t dt = now_ms - t->last_ms;
    t->last_ms = now_ms;
    if (dt >= t->remaining_ms) {
        t->remaining_ms = 0;
        t->state = LT_STOPPED;
        return true;
    }
    t->remaining_ms -= dt;
    return false;
}

void lt_split_calc(uint32_t remaining_sec, uint32_t *current_sec, uint32_t *next_sec)
{
    uint32_t cur = remaining_sec / 2u;
    if (cur < 120u) {
        cur = 120u;
    }
    uint32_t nxt = remaining_sec > cur ? remaining_sec - cur : 0u;
    if (nxt < 120u) {
        nxt = 120u;
    }
    *current_sec = cur;
    *next_sec = nxt;
}

void oev_init(oev_queue_t *q)
{
    memset(q, 0, sizeof *q);
    q->next_seq = 1;
}

void oev_clear(oev_queue_t *q)
{
    q->head = 0;
    q->count = 0;
}

const oev_t *oev_at(const oev_queue_t *q, uint8_t i)
{
    return i < q->count ? &q->ev[(q->head + i) % OEV_CAPACITY] : NULL;
}

static void remove_at(oev_queue_t *q, uint8_t i)
{
    for (uint8_t k = i; k + 1 < q->count; k++) {
        q->ev[(q->head + k) % OEV_CAPACITY] = q->ev[(q->head + k + 1) % OEV_CAPACITY];
    }
    q->count--;
}

void oev_push(oev_queue_t *q, oev_kind_t kind, const char *ref_id, uint32_t remaining_ms, uint32_t ts_epoch)
{
    if (q->count == OEV_CAPACITY) {
        uint8_t victim = 0;
        for (uint8_t i = 0; i < q->count; i++) {
            if (oev_at(q, i)->kind == OEV_TIMER_DELTA) {
                victim = i;
                break;
            }
        }
        remove_at(q, victim);
        q->dropped++;
    }
    oev_t *e = &q->ev[(q->head + q->count) % OEV_CAPACITY];
    memset(e, 0, sizeof *e);
    e->seq = q->next_seq++;
    e->kind = (uint8_t)kind;
    if (ref_id) {
        strncpy(e->ref_id, ref_id, sizeof e->ref_id - 1);
    }
    e->remaining_ms = remaining_ms;
    e->ts_epoch = ts_epoch;
    q->count++;
}

const char *oev_kind_name(uint8_t kind)
{
    switch (kind) {
    case OEV_STEP_COMPLETE: return "STEP_COMPLETE";
    case OEV_STEP_SPLIT: return "STEP_SPLIT";
    case OEV_TIMER_DELTA: return "TIMER_DELTA";
    case OEV_ALARM_ACK: return "ALARM_ACK";
    default: return "UNKNOWN";
    }
}

size_t oev_to_json(const oev_queue_t *q, uint32_t boot_id, char *out, size_t cap)
{
    size_t n = 0;
    int w = snprintf(out, cap, "[");
    if (w < 0 || (size_t)w >= cap) {
        return 0;
    }
    n = (size_t)w;
    for (uint8_t i = 0; i < q->count; i++) {
        const oev_t *e = oev_at(q, i);
        w = snprintf(out + n, cap - n,
                     "%s{\"seq\":%lu,\"boot_id\":%lu,\"kind\":\"%s\",\"ref_id\":\"%s\",\"remaining_ms\":%lu,"
                     "\"ts_epoch\":%lu}",
                     i ? "," : "", (unsigned long)e->seq, (unsigned long)boot_id, oev_kind_name(e->kind), e->ref_id,
                     (unsigned long)e->remaining_ms, (unsigned long)e->ts_epoch);
        if (w < 0 || (size_t)w >= cap - n) {
            return 0;
        }
        n += (size_t)w;
    }
    if (n + 2 > cap) {
        return 0;
    }
    out[n++] = ']';
    out[n] = 0;
    return n;
}
