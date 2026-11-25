#include "app_controller.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mascot.h"
#include "ui_layout.h"
#include "ui_render.h"

static const char *const STATE_NAMES[UI_STATE_COUNT] = {
    "IDLE_READY", "LISTENING", "TRANSCRIBING", "THINKING", "RUNNING", "PAUSED",
    "BREAK", "STEP_DONE", "ALARM_RINGING", "NEEDS_CONFIRMATION", "SLEEP", "ERROR_RECOVERABLE", "VOICE_PICK",
    "MEETING"};

const char *app_state_name(ui_state_t s) { return (unsigned)s < UI_STATE_COUNT ? STATE_NAMES[s] : "IDLE_READY"; }

ui_state_t app_state_from_name(const char *s)
{
    for (int i = 0; i < UI_STATE_COUNT; i++) {
        if (strcmp(s, STATE_NAMES[i]) == 0) {
            return (ui_state_t)i;
        }
    }
    return UI_STATE_IDLE_READY;
}

void app_init(app_t *a, const app_io_t *io, uint32_t now_ms, uint32_t boot_id, bool is_sim)
{
    memset(a, 0, sizeof *a);
    a->io = *io;
    a->is_sim = is_sim;
    a->boot_id = boot_id;
    a->now_ms = now_ms;
    a->idle_since_ms = now_ms;
    ui_model_init(&a->m);
    oev_init(&a->oev);
    gestures_init(&a->gest, now_ms);
    mascot_anim_init(&a->anim, boot_id ^ 0xA5A5u, now_ms);
    lt_load(&a->timer, 0, 0, LT_STOPPED, now_ms);
    lt_load(&a->brk, 0, 0, LT_STOPPED, now_ms);
    a->dirty = true;
}

void app_send(app_t *a, uint8_t type, bool ack, const uint8_t *payload, uint16_t len)
{
    uint8_t flags = (uint8_t)((ack ? PIP_FLAG_ACK_REQUIRED : 0) | (a->is_sim ? PIP_FLAG_IS_SIMULATOR : 0));
    if (a->tx_seq == 0) {
        a->tx_seq = 1; /* 0 is reserved for "no pending reliable frame" */
    }
    if (a->io.send) {
        a->io.send(a->io.ctx, type, flags, a->tx_seq, payload, len);
    }
    a->tx_seq++;
}

void app_toast_for(app_t *a, const char *msg, uint32_t ms)
{
    snprintf(a->m.toast, sizeof a->m.toast, "%s", msg);
    a->toast_until_ms = a->now_ms + ms;
    a->dirty = true;
}

void app_toast(app_t *a, const char *msg)
{
    app_toast_for(a, msg, APP_TOAST_MS);
}

void app_stop_voice(app_t *a)
{
    /* AUDIO_END_OUT with the abort flag: drop whatever speech is still buffered (alarm dismissed) */
    static const uint8_t abort_end[8] = {0, 0, 0, 0, 1, 0, 0, 0};
    if (a->io.play) {
        a->io.play(a->io.ctx, PIP_AUDIO_END_OUT, abort_end, sizeof abort_end);
    }
}

void app_set_epoch(app_t *a, uint32_t epoch_s)
{
    a->epoch_valid = epoch_s > 1600000000u;
    a->epoch_s_at = epoch_s;
    a->epoch_ms_at = a->now_ms;
}

uint32_t app_epoch_now(const app_t *a)
{
    return a->epoch_valid ? a->epoch_s_at + (a->now_ms - a->epoch_ms_at) / 1000u : 0u;
}

void app_set_battery(app_t *a, int pct)
{
    bool valid = pct >= 0;
    uint8_t p = (uint8_t)(pct < 0 ? 0 : (pct > 100 ? 100 : pct));
    if (valid != a->m.batt_valid || p != a->m.batt_pct) {
        a->m.batt_valid = valid;
        a->m.batt_pct = p;
        a->dirty = true;
    }
}

void app_set_audio_level(app_t *a, uint8_t level)
{
    if (level > 8) {
        level = 8;
    }
    if (a->m.audio_level != level && (a->m.state == UI_STATE_LISTENING || a->m.state == UI_STATE_MEETING)) {
        a->m.audio_level = level;
        a->dirty = true;
    }
}

void app_sync_timer_to_model(app_t *a)
{
    a->m.timer_state = (timer_state_t)a->timer.state;
    a->m.remaining_ms = a->timer.remaining_ms;
    a->m.step_total_ms = a->timer.total_ms;
}

void app_send_offline_events(app_t *a)
{
    static char buf[PIP_MAX_PAYLOAD];
    if (a->oev.count == 0) {
        return;
    }
    size_t n = oev_to_json(&a->oev, a->boot_id, buf, sizeof buf);
    if (n == 0) {
        return;
    }
    if (a->tx_seq == 0) {
        a->tx_seq = 1;
    }
    a->pending_oev_seq = a->tx_seq;
    a->pending_oev_ms = a->now_ms;
    app_send(a, PIP_OFFLINE_EVENTS, true, (const uint8_t *)buf, (uint16_t)n);
}

static void supervise_states(app_t *a, uint32_t now_ms);

/* Gentle time cues while a step runs: "5 minutes left" (steps of 8+ min) and "Time to wrap up" at 1 minute.
 * Device-local, so they work offline too; each fires once, when the countdown crosses its mark. */
static void focus_cues(app_t *a, uint32_t before_s, uint32_t after_s)
{
    if (a->timer.state != LT_RUNNING || a->m.state != UI_STATE_RUNNING) {
        return;
    }
    const char *msg = NULL;
    uint8_t id = 0;
    if (before_s > APP_CUE_5MIN_S && after_s <= APP_CUE_5MIN_S && a->timer.total_ms >= APP_CUE_5MIN_MIN_TOTAL_MS) {
        msg = "5 minutes left";
        id = CHIME_NUDGE;
    } else if (before_s > APP_CUE_WRAP_S && after_s <= APP_CUE_WRAP_S &&
               a->timer.total_ms >= APP_CUE_WRAP_MIN_TOTAL_MS) {
        msg = "Time to wrap up";
        id = CHIME_WRAP;
    }
    if (!msg) {
        return;
    }
    app_toast_for(a, msg, 5000);
    mascot_react(&a->anim, PIP_REACT_PRESS, a->now_ms); /* PIP turns and looks at you */
    if (a->io.chime) {
        a->io.chime(a->io.ctx, id);
    }
}

static void update_clock(app_t *a)
{
    if (!a->epoch_valid) {
        return;
    }
    int64_t local = (int64_t)app_epoch_now(a) + (int64_t)a->tz_offset_min * 60;
    uint32_t sod = (uint32_t)(local % 86400);
    uint8_t hh = (uint8_t)(sod / 3600u), mm = (uint8_t)((sod / 60u) % 60u);
    if (!a->m.clock_valid || hh != a->m.hh || mm != a->m.mm) {
        a->m.clock_valid = true;
        a->m.hh = hh;
        a->m.mm = mm;
        a->dirty = true;
    }
}

static void standalone_alarms(app_t *a)
{
    uint32_t now = app_epoch_now(a);
    if (!now || a->m.link == LINK_TETHERED || a->m.state == UI_STATE_ALARM_RINGING) {
        return;
    }
    for (uint8_t i = 0; i < a->alarm_count; i++) {
        app_alarm_t *al = &a->alarms[i];
        if (al->enabled && !al->fired && al->epoch_s <= now && now - al->epoch_s < 3600u) {
            al->fired = true;
            int64_t local = (int64_t)al->epoch_s + (int64_t)a->tz_offset_min * 60;
            uint32_t sod = (uint32_t)(local % 86400);
            char hhmm[6];
            unsigned h = (sod / 3600u) % 24u, mi = (sod / 60u) % 60u;
            hhmm[0] = (char)('0' + h / 10u);
            hhmm[1] = (char)('0' + h % 10u);
            hhmm[2] = ':';
            hhmm[3] = (char)('0' + mi / 10u);
            hhmm[4] = (char)('0' + mi % 10u);
            hhmm[5] = 0;
            app_ring_alarm(a, al->id, al->title, hhmm, 0);
            return;
        }
    }
}

static void link_supervision(app_t *a)
{
    bool linked = a->ever_linked && a->now_ms - a->last_rx_ms < APP_LINK_TIMEOUT_MS;
    link_state_t want = linked ? LINK_TETHERED : LINK_STANDALONE;
    if (want != a->m.link) {
        a->m.link = want;
        a->dirty = true;
        if (want == LINK_TETHERED) {
            a->meeting_link_lost_ms = 0;
            app_send_diag(a);
            app_send_offline_events(a);
        } else {
            a->pending_oev_seq = 0;
            if (a->m.state == UI_STATE_MEETING) {
                a->meeting_link_lost_ms = a->now_ms ? a->now_ms : 1u; /* keep recording for a grace period */
            } else if (a->m.state == UI_STATE_LISTENING || a->m.state == UI_STATE_TRANSCRIBING ||
                a->m.state == UI_STATE_THINKING) {
                if (a->io.capture) {
                    a->io.capture(a->io.ctx, false, a->stream_id);
                }
                a->m.state = a->m.has_active_step ? (a->timer.state == LT_RUNNING ? UI_STATE_RUNNING : UI_STATE_PAUSED)
                                                  : UI_STATE_IDLE_READY;
            }
            if (a->io.chime) {
                a->io.chime(a->io.ctx, CHIME_OFFLINE);
            }
        }
    }
    if (linked && a->pending_oev_seq && a->now_ms - a->pending_oev_ms > 2000u) {
        app_send_offline_events(a); /* retry until ACKed */
    }
}

void app_tick(app_t *a, uint32_t now_ms)
{
    a->now_ms = now_ms;
    link_supervision(a);
    if (now_ms - a->last_hb_ms >= APP_HEARTBEAT_MS) {
        a->last_hb_ms = now_ms;
        app_send_heartbeat(a);
    }
    uint32_t before = a->timer.remaining_ms / 1000u;
    if (lt_tick(&a->timer, now_ms)) {
        app_sync_timer_to_model(a);
        snprintf(a->m.done_title, sizeof a->m.done_title, "%s", a->m.step_title);
        a->m.done_activity = a->m.activity;
        if (a->m.state != UI_STATE_MEETING) { /* a meeting recording is never interrupted */
            a->m.state = UI_STATE_STEP_DONE;
        }
        if (a->m.link == LINK_STANDALONE) {
            oev_push(&a->oev, OEV_STEP_COMPLETE, a->m.step_id, 0, app_epoch_now(a));
        }
        if (a->io.chime) {
            a->io.chime(a->io.ctx, CHIME_DONE);
        }
        a->dirty = true;
    } else if (a->timer.remaining_ms / 1000u != before) {
        app_sync_timer_to_model(a);
        focus_cues(a, before, a->timer.remaining_ms / 1000u);
        a->dirty = true;
    }
    uint32_t bb = a->brk.remaining_ms / 1000u;
    if (lt_tick(&a->brk, now_ms)) {
        a->m.break_remaining_ms = 0;
        if (a->m.state == UI_STATE_BREAK) {
            a->m.state = UI_STATE_IDLE_READY;
            if (a->io.chime) {
                a->io.chime(a->io.ctx, CHIME_START);
            }
        }
        a->dirty = true;
    } else if (a->brk.remaining_ms / 1000u != bb) {
        a->m.break_remaining_ms = a->brk.remaining_ms;
        a->dirty = true;
    }
    if (a->m.state == UI_STATE_MEETING && a->meeting_link_lost_ms &&
        now_ms - a->meeting_link_lost_ms >= APP_MEETING_LINK_GRACE_MS) {
        app_meeting_end(a, "Meeting stopped: PC link lost");
    }
    if (a->m.state != UI_STATE_LISTENING) {
        a->voice_auto = false; /* any way out of listening (error, link loss, END) ends the "which activity" wait */
    }
    if (a->m.voice_auto != a->voice_auto) {
        a->m.voice_auto = a->voice_auto;
        a->dirty = true;
    }
    bool hf = a->hands_free && a->m.state == UI_STATE_LISTENING;
    if (a->m.voice_hands_free != hf) {
        a->m.voice_hands_free = hf;
        a->dirty = true;
    }
    if (a->m.state == UI_STATE_LISTENING || a->m.state == UI_STATE_MEETING) {
        uint32_t el32 = (now_ms - a->listen_start_ms) / 1000u;
        uint16_t el = (uint16_t)(el32 > 65535u ? 65535u : el32);
        if (el != a->m.listen_elapsed_s) {
            a->m.listen_elapsed_s = el;
            a->dirty = true;
        }
    }
    update_clock(a);
    standalone_alarms(a);
    /* offline the host can't drive the wake-up sequence: keep chiming for a minute */
    if (a->m.state == UI_STATE_ALARM_RINGING && a->m.link == LINK_STANDALONE &&
        now_ms - a->ring_since_ms < APP_RING_CHIME_FOR_MS && now_ms - a->ring_chime_ms >= APP_RING_CHIME_MS) {
        a->ring_chime_ms = now_ms;
        if (a->io.chime) {
            a->io.chime(a->io.ctx, CHIME_ALARM);
        }
    }
    if (a->m.toast[0] && now_ms >= a->toast_until_ms) {
        a->m.toast[0] = 0;
        a->dirty = true;
    }
    bool busy = a->timer.state == LT_RUNNING || a->brk.state == LT_RUNNING || a->m.state == UI_STATE_ALARM_RINGING ||
                a->m.state == UI_STATE_MEETING;
    if (busy || a->m.link == LINK_TETHERED) {
        a->idle_since_ms = now_ms;
    } else if (a->m.state == UI_STATE_IDLE_READY && now_ms - a->idle_since_ms >= APP_SLEEP_IDLE_MS) {
        a->m.state = UI_STATE_SLEEP;
        a->dirty = true;
    }
    supervise_states(a, now_ms);
    /* live PIP: each screen has its own act library, steered by what the screen is about (the idle one never
     * repeats within 2 hours) */
    a->prev_state = a->m.state;
    mascot_set_scene(&a->anim, ui_mode_for(&a->m), app_scene_tags(a), now_ms);
    if (a->anim.mode == PIP_MODE_PICK) {
        mascot_set_pick(&a->anim, a->m.voice_choice, UI_VOICE_CHOICES);
    }
    if (mascot_anim_step(&a->anim, now_ms)) {
        a->m.pose = a->anim.pose;
        a->m.anim_ms = now_ms;
        a->dirty = true;
    }
}

void app_local_error(app_t *a, const char *title, const char *text)
{
    snprintf(a->m.error_title, sizeof a->m.error_title, "%s", title);
    snprintf(a->m.error_text, sizeof a->m.error_text, "%s", text);
    if (a->io.capture && (a->m.state == UI_STATE_LISTENING || a->m.state == UI_STATE_MEETING)) {
        a->io.capture(a->io.ctx, false, a->stream_id);
    }
    a->m.state = UI_STATE_ERROR_RECOVERABLE;
    a->error_since_ms = a->now_ms;
    a->error_local = true;
    a->dirty = true;
}

/* A failed read keeps the last good value on screen; the reading only disappears after APP_INDOOR_HOLD_MS
 * without a good one (sensor gone), so the header no longer flickers (BUG-017). */
void app_set_indoor(app_t *a, bool valid, int16_t temp_c10, uint8_t hum)
{
    if (!valid) {
        if (a->m.in_valid && (!a->indoor_seen || a->now_ms - a->indoor_ok_ms >= APP_INDOOR_HOLD_MS)) {
            a->m.in_valid = false;
            a->dirty = true;
        }
        return;
    }
    a->indoor_seen = true;
    a->indoor_ok_ms = a->now_ms;
    if (!a->m.in_valid || temp_c10 / 5 != a->m.in_temp_c10 / 5 || hum != a->m.in_hum) {
        a->m.in_valid = true;
        a->m.in_temp_c10 = temp_c10;
        a->m.in_hum = hum;
        a->dirty = true;
    }
}

/* What PIP should act out on this screen: the task's activity, the voice activity picked, the thinking stage. */
uint32_t app_scene_tags(const app_t *a)
{
    switch (ui_mode_for(&a->m)) {
    case PIP_MODE_FOCUS:
    case PIP_MODE_PAUSE: return PIP_TAG(a->m.activity % PIP_ACTIVITY_COUNT);
    case PIP_MODE_DONE: return PIP_TAG(a->m.done_activity % PIP_ACTIVITY_COUNT);
    case PIP_MODE_IDLE: return a->m.has_active_step ? PIP_TAG(a->m.activity % PIP_ACTIVITY_COUNT) : 0u;
    case PIP_MODE_LISTEN: return PIP_TAG_VOICE(a->m.voice_choice % UI_VOICE_CHOICES);
    case PIP_MODE_THINK: return a->m.state == UI_STATE_TRANSCRIBING ? PIP_TAG_TRANSCRIBE : PIP_TAG_PLANNING;
    default: return 0u;
    }
}

/* Picker timeout, error attention flash and the device-side stuck-state watchdog. */
static void supervise_states(app_t *a, uint32_t now_ms)
{
    ui_state_t st = a->m.state;
    if (st == UI_STATE_VOICE_PICK && now_ms - a->pick_since_ms >= APP_PICK_TIMEOUT_MS) {
        a->m.state = a->state_before_pick;
        a->dirty = true;
    }
    bool flash = st == UI_STATE_ERROR_RECOVERABLE && now_ms - a->error_since_ms < APP_ERROR_FLASH_MS &&
                 ((now_ms - a->error_since_ms) / 300u) % 2u == 1u;
    if (flash != a->m.error_flash) {
        a->m.error_flash = flash;
        a->dirty = true;
    }
    /* a meeting has no time limit; a voice message may run 10 minutes */
    uint32_t limit = st == UI_STATE_LISTENING ? APP_STUCK_LISTEN_MS
                     : (st == UI_STATE_TRANSCRIBING || st == UI_STATE_THINKING) ? APP_STUCK_MS : 0u;
    if (st != a->prev_state) {
        a->state_since_ms = now_ms;
    } else if (limit && now_ms - a->state_since_ms >= limit) {
        app_local_error(a, "PIP got stuck", "No answer from the PC. Press any button.");
    }
}

/* Slides move whole pages while PIP - one character, not one per page - stays where it is, drawn on top.
 * The model behind the panel is kept so the old page can be re-rendered without PIP. */
struct app_slide_s {
    rlcd_fb_t from, to, pages;
    ui_model_t shown; /* the model of what the panel shows */
    bool shown_ok;
};

static void render_pages(rlcd_fb_t *out, const ui_model_t *m)
{
    ui_mascot_hide(true);
    ui_render(out, m, NULL);
    ui_mascot_hide(false);
}

static void slide_begin(app_t *a, ui_screen_t from, ui_screen_t to)
{
    int dir = ui_slide_dir(from, to);
    if (dir == 0 || !a->slide) { /* same layout, or no memory: switch instantly */
        a->sliding = false;
        return;
    }
    struct app_slide_s *sl = a->slide;
    if (a->sliding) {
        sl->from = sl->pages; /* interrupted mid-slide: carry on from where the pages are */
    } else if (sl->shown_ok) {
        render_pages(&sl->from, &sl->shown);
    } else {
        sl->from = a->fb;
    }
    a->sliding = true;
    a->slide_dir = (int8_t)dir;
    a->slide_start_ms = a->now_ms;
    a->slide_last_ms = a->now_ms - SLIDE_FRAME_MS;
    a->slide_dur_ms = dir == 2 || dir == -2 ? SLIDE_V_MS : SLIDE_MS;
}

bool app_render_if_dirty(app_t *a)
{
    if (!a->slide) {
        a->slide = calloc(1, sizeof *a->slide); /* NULL: slides are off, screens switch instantly */
    }
    ui_screen_t s = ui_screen_for(&a->m);
    if (a->shown_valid && s != a->shown_screen) {
        slide_begin(a, a->shown_screen, s);
    }
    a->shown_screen = s;
    a->shown_valid = true;
    if (a->sliding) {
        uint32_t el = a->now_ms - a->slide_start_ms;
        if (el < a->slide_dur_ms) {
            if (a->now_ms - a->slide_last_ms < SLIDE_FRAME_MS) {
                return false; /* <= 25 FPS while sliding */
            }
            a->slide_last_ms = a->now_ms;
            a->dirty = false;
            struct app_slide_s *sl = a->slide;
            float u = (float)el / (float)a->slide_dur_ms;
            float k = 1.0f - u;
            render_pages(&sl->to, &a->m);
            ui_slide_compose(&sl->pages, &sl->from, &sl->to, a->slide_dir, 1.0f - k * k * k, ZONE_TOP - 1, BAR_Y);
            a->fb = sl->pages;
            ui_draw_mascot_on(&a->fb, &a->m.pose, s == SCREEN_IDLE_READY ? &UI_STAGE_WORLD : &UI_STAGE_COLUMN);
            return true;
        }
        a->sliding = false;
        a->dirty = true; /* final frame: the plain new screen */
    }
    if (!a->dirty) {
        return false;
    }
    a->dirty = false;
    ui_render(&a->fb, &a->m, NULL);
    if (a->slide) {
        a->slide->shown = a->m;
        a->slide->shown_ok = true;
    }
    return true;
}
