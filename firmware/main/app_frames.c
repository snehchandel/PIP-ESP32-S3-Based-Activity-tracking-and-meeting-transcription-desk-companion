/* Host -> device frame handling: UI_UPDATE, CALENDAR_SYNC, ALARM_TRIGGER, DUMP_FB, ACKs. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"
#include "json_mini.h"

static void ack(app_t *a, uint16_t ref, uint8_t status)
{
    pip_ack_t k = {ref, status, 0, 0};
    uint8_t b[6];
    app_send(a, PIP_ACK, false, b, (uint16_t)pip_pack_ack(&k, b));
}

#define GETS(key, field) (void)jm_get_str(j, n, key, field, sizeof(field))

void app_apply_ui_update(app_t *a, const char *j, size_t n)
{
    ui_model_t *m = &a->m;
    long v = 0;
    char s[24];
    if (jm_get_long(j, n, "rev", &v)) {
        a->state_rev = (uint32_t)v;
    }
    GETS("task_title", m->task_title);
    GETS("step_id", m->step_id);
    GETS("step_title", m->step_title);
    GETS("next_step_id", a->next_step_id);
    GETS("next_step_title", m->next_step_title);
    GETS("next_alarm_hhmm", m->next_alarm_hhmm);
    GETS("clarification_text", m->clarification);
    GETS("thinking_stage", m->thinking_stage);
    GETS("done_title", m->done_title);
    if (jm_get_long(j, n, "step_index", &v)) m->step_index = (uint8_t)v;
    if (jm_get_long(j, n, "step_total", &v)) m->step_total = (uint8_t)v;
    if (jm_get_long(j, n, "next_step_min", &v)) m->next_step_min = (uint16_t)v;
    if (jm_get_long(j, n, "parked_count", &v)) m->parked_count = (uint16_t)v;
    if (jm_get_long(j, n, "tz_offset_min", &v)) a->tz_offset_min = (int16_t)v;
    (void)jm_get_bool(j, n, "is_starter", &m->is_starter);
    m->has_active_step = m->step_id[0] != 0;

    long rem = 0, total = 0;
    (void)jm_get_long(j, n, "remaining_ms", &rem);
    if (!jm_get_long(j, n, "step_total_ms", &total)) {
        total = rem;
    }
    lt_state_t ts = LT_STOPPED;
    if (jm_get_str(j, n, "timer_state", s, sizeof s)) {
        ts = strcmp(s, "RUNNING") == 0 ? LT_RUNNING : (strcmp(s, "PAUSED") == 0 ? LT_PAUSED : LT_STOPPED);
    }
    lt_load(&a->timer, (uint32_t)(rem < 0 ? 0 : rem), (uint32_t)(total < 0 ? 0 : total), ts, a->now_ms);
    app_sync_timer_to_model(a);
    if (jm_get_long(j, n, "break_remaining_ms", &v) && v > 0) {
        lt_load(&a->brk, (uint32_t)v, APP_BREAK_MS, LT_RUNNING, a->now_ms);
        m->break_remaining_ms = (uint32_t)v;
    }
    if (jm_get_str(j, n, "page", s, sizeof s)) {
        m->page = strcmp(s, "AGENDA") == 0 ? PAGE_AGENDA : PAGE_FOCUS;
    }
    bool host_ringing = true;
    if (m->state == UI_STATE_ALARM_RINGING && jm_get_bool(j, n, "alarm_ringing", &host_ringing) && !host_ringing) {
        m->state = UI_STATE_IDLE_READY; /* host ended the alarm (dismissed in the app or auto-timeout) */
    }
    if (jm_get_str(j, n, "ui_state", s, sizeof s) && m->state != UI_STATE_ALARM_RINGING) {
        ui_state_t ns = app_state_from_name(s);
        /* never let a stale host state interrupt an active local voice capture */
        if (!(m->state == UI_STATE_LISTENING && ns != UI_STATE_LISTENING)) {
            m->state = ns;
        }
    }
    a->dirty = true;
}

void app_apply_calendar(app_t *a, const char *j, size_t n)
{
    ui_model_t *m = &a->m;
    long v = 0;
    if (jm_get_long(j, n, "rev", &v)) {
        a->calendar_rev = (uint32_t)v;
    }
    GETS("date_label", m->date_label);
    if (jm_get_long(j, n, "tomorrow_count", &v)) m->tomorrow_count = (uint8_t)v;
    if (jm_get_long(j, n, "parked_count", &v)) m->parked_count = (uint16_t)v;
    jm_span_t arr, el;
    size_t cur = 0;
    m->today_count = 0;
    if (jm_find(j, n, "today", &arr)) {
        while (m->today_count < UI_AGENDA_MAX && jm_array_next(arr, &cur, &el)) {
            agenda_item_t *it = &m->today[m->today_count++];
            memset(it, 0, sizeof *it);
            (void)jm_get_str(el.p, el.n, "id", it->id, sizeof it->id);
            (void)jm_get_str(el.p, el.n, "title", it->title, sizeof it->title);
            (void)jm_get_str(el.p, el.n, "hhmm", it->hhmm, sizeof it->hhmm);
            (void)jm_get_bool(el.p, el.n, "done", &it->done);
            if (jm_get_long(el.p, el.n, "kind", &v)) it->kind = (uint8_t)v;
        }
    }
    cur = 0;
    a->alarm_count = 0;
    if (jm_find(j, n, "upcoming_alarms", &arr)) {
        while (a->alarm_count < APP_ALARMS_MAX && jm_array_next(arr, &cur, &el)) {
            app_alarm_t *al = &a->alarms[a->alarm_count++];
            memset(al, 0, sizeof *al);
            (void)jm_get_str(el.p, el.n, "id", al->id, sizeof al->id);
            (void)jm_get_str(el.p, el.n, "title", al->title, sizeof al->title);
            if (jm_get_long(el.p, el.n, "epoch_s", &v)) al->epoch_s = (uint32_t)v;
            if (jm_get_long(el.p, el.n, "chime_id", &v)) al->chime_id = (uint8_t)v;
            al->enabled = true;
            (void)jm_get_bool(el.p, el.n, "enabled", &al->enabled);
        }
    }
    a->dirty = true;
}

void app_ring_alarm(app_t *a, const char *id, const char *title, const char *hhmm, uint8_t audio)
{
    if (a->m.state != UI_STATE_ALARM_RINGING) {
        a->state_before_alarm = a->m.state;
    }
    snprintf(a->alarm_id, sizeof a->alarm_id, "%s", id);
    snprintf(a->m.alarm_title, sizeof a->m.alarm_title, "%s", title);
    snprintf(a->m.alarm_hhmm, sizeof a->m.alarm_hhmm, "%s", hhmm);
    a->m.alarm_audio = audio;
    a->m.state = UI_STATE_ALARM_RINGING;
    a->dirty = true;
    if (a->io.chime) {
        a->io.chime(a->io.ctx, CHIME_ALARM);
    }
}

static void on_alarm_trigger(app_t *a, const char *j, size_t n)
{
    char id[24] = "", title[64] = "", hhmm[6] = "", mode[8] = "";
    (void)jm_get_str(j, n, "alarm_id", id, sizeof id);
    (void)jm_get_str(j, n, "title", title, sizeof title);
    (void)jm_get_str(j, n, "hhmm", hhmm, sizeof hhmm);
    (void)jm_get_str(j, n, "audio_mode", mode, sizeof mode);
    app_ring_alarm(a, id, title, hhmm, (uint8_t)(strcmp(mode, "CHIME") != 0));
}

static void dump_fb(app_t *a)
{
    static uint8_t chunk[PIP_FB_CHUNK_PAYLOAD];
    for (uint8_t i = 0; i < PIP_FB_CHUNKS; i++) {
        app_send(a, PIP_DUMP_FB, false, chunk, (uint16_t)pip_pack_fb_chunk(i, a->fb.px, chunk));
    }
}

void app_on_frame(app_t *a, const pip_frame_t *f)
{
    a->last_rx_ms = a->now_ms;
    a->ever_linked = true;
    const char *j = (const char *)f->payload;
    bool json_type = f->type == PIP_UI_UPDATE || f->type == PIP_CALENDAR_SYNC || f->type == PIP_ALARM_TRIGGER;
    if (json_type && !jm_valid_object(j, f->len)) {
        ack(a, f->seq, PIP_ACK_BAD_JSON);
        return;
    }
    uint8_t status = PIP_ACK_OK;
    switch (f->type) {
    case PIP_HEARTBEAT: {
        pip_heartbeat_t h;
        if (pip_unpack_heartbeat(f->payload, f->len, &h) && h.utc_epoch_s) {
            app_set_epoch(a, h.utc_epoch_s);
        }
        break;
    }
    case PIP_UI_UPDATE: app_apply_ui_update(a, j, f->len); break;
    case PIP_CALENDAR_SYNC: app_apply_calendar(a, j, f->len); break;
    case PIP_ALARM_TRIGGER: on_alarm_trigger(a, j, f->len); break;
    case PIP_PLAY_CHIME: {
        pip_chime_t c;
        if (pip_unpack_chime(f->payload, f->len, &c) && a->io.chime) {
            a->io.chime(a->io.ctx, c.chime_id);
        } else {
            status = PIP_ACK_BAD_LEN;
        }
        break;
    }
    case PIP_ACK: {
        pip_ack_t k;
        if (pip_unpack_ack(f->payload, f->len, &k) && a->pending_oev_seq && k.ref_seq == a->pending_oev_seq &&
            k.status == PIP_ACK_OK) {
            oev_clear(&a->oev);
            a->pending_oev_seq = 0;
        }
        return;
    }
    case PIP_DIAG_REPORT: app_send_diag(a); break;
    case PIP_DUMP_FB: dump_fb(a); return;
    case PIP_SIM_INPUT: return; /* consumed by the simulator transport */
    default:
        if (f->type == PIP_AUDIO_START_OUT || f->type == PIP_AUDIO_DATA_OUT || f->type == PIP_AUDIO_END_OUT) {
            if (a->io.play) {
                a->io.play(a->io.ctx, f->type, f->payload, f->len); /* host voice (Piper TTS) */
            }
            break;
        }
        status = PIP_ACK_UNKNOWN_TYPE;
        break;
    }
    if (f->flags & PIP_FLAG_ACK_REQUIRED) {
        ack(a, f->seq, status);
    }
}
