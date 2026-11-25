/* Gesture action matrix (spec v6 section 5.3): local-first state change, then report. */
#include <stdio.h>
#include <string.h>

#include "app_controller.h"

static void report(app_t *a, const gesture_event_t *e)
{
    if (a->m.link != LINK_TETHERED) {
        return;
    }
    pip_btn_event_t ev = {++a->event_seq, (uint8_t)e->btn, (uint8_t)e->gesture, e->flags, e->ts_ms};
    uint8_t b[12];
    app_send(a, PIP_BTN_EVENT, true, b, (uint16_t)pip_pack_btn_event(&ev, b));
}

static void chime(app_t *a, uint8_t id)
{
    if (a->io.chime) {
        a->io.chime(a->io.ctx, id);
    }
}

static void log_offline(app_t *a, oev_kind_t k, const char *ref, uint32_t rem)
{
    if (a->m.link == LINK_STANDALONE) {
        oev_push(&a->oev, k, ref, rem, app_epoch_now(a));
    }
}

static void end_alarm(app_t *a, bool snooze)
{
    if (snooze) {
        for (uint8_t i = 0; i < a->alarm_count; i++) {
            if (strcmp(a->alarms[i].id, a->alarm_id) == 0) {
                a->alarms[i].epoch_s = app_epoch_now(a) + 5u * 60u;
                a->alarms[i].fired = false;
            }
        }
    }
    log_offline(a, OEV_ALARM_ACK, a->alarm_id, snooze ? 1u : 0u);
    app_stop_voice(a); /* silence the spoken wake-up immediately */
    a->m.state = a->state_before_alarm == UI_STATE_ALARM_RINGING ? UI_STATE_IDLE_READY : a->state_before_alarm;
    if (a->m.state == UI_STATE_SLEEP) {
        a->m.state = UI_STATE_IDLE_READY;
    }
}

static void toggle_timer(app_t *a)
{
    if (!a->m.has_active_step) {
        app_toast(a, a->m.link == LINK_TETHERED ? "Hold KEY to plan a task" : "Plan tasks in the PIP app");
        return;
    }
    if (a->timer.state == LT_RUNNING) {
        lt_pause(&a->timer, a->now_ms);
        a->m.state = UI_STATE_PAUSED;
        log_offline(a, OEV_TIMER_DELTA, a->m.step_id, a->timer.remaining_ms);
        chime(a, CHIME_PAUSE);
    } else {
        if (a->timer.remaining_ms == 0) {
            lt_load(&a->timer, a->m.remaining_ms, a->m.step_total_ms, LT_PAUSED, a->now_ms);
        }
        lt_start(&a->timer, a->now_ms);
        a->m.state = a->timer.state == LT_RUNNING ? UI_STATE_RUNNING : a->m.state;
        log_offline(a, OEV_TIMER_DELTA, a->m.step_id, a->timer.remaining_ms);
        chime(a, CHIME_START);
    }
    app_sync_timer_to_model(a);
}

static void start_next_step(app_t *a)
{
    if (!a->next_step_id[0] || a->m.next_step_min == 0) {
        a->m.state = UI_STATE_IDLE_READY;
        return;
    }
    snprintf(a->m.step_id, sizeof a->m.step_id, "%s", a->next_step_id);
    snprintf(a->m.step_title, sizeof a->m.step_title, "%s", a->m.next_step_title);
    a->m.activity = a->m.next_activity; /* offline too, PIP acts out the step it moves on to */
    a->m.next_activity = PIP_ACT_GENERAL;
    uint32_t ms = (uint32_t)a->m.next_step_min * 60000u;
    a->m.step_index++;
    a->m.is_starter = false;
    a->m.has_active_step = true;
    a->next_step_id[0] = 0;
    a->m.next_step_title[0] = 0;
    a->m.next_step_min = 0;
    lt_load(&a->timer, ms, ms, LT_PAUSED, a->now_ms);
    lt_start(&a->timer, a->now_ms);
    a->m.state = UI_STATE_RUNNING;
    log_offline(a, OEV_TIMER_DELTA, a->m.step_id, ms);
    app_sync_timer_to_model(a);
}

static void complete_step(app_t *a)
{
    lt_stop(&a->timer);
    log_offline(a, OEV_STEP_COMPLETE, a->m.step_id, a->timer.remaining_ms);
    snprintf(a->m.done_title, sizeof a->m.done_title, "%s", a->m.step_title);
    a->m.done_activity = a->m.activity;
    a->m.has_active_step = a->next_step_id[0] != 0;
    a->m.state = UI_STATE_STEP_DONE;
    chime(a, CHIME_DONE);
    app_sync_timer_to_model(a);
}

static void rescue_split(app_t *a)
{
    if (!a->m.has_active_step) {
        return;
    }
    lt_tick(&a->timer, a->now_ms);
    uint32_t rem_s = (a->timer.remaining_ms + 999u) / 1000u, cur = 0, nxt = 0;
    lt_split_calc(rem_s, &cur, &nxt);
    lt_state_t st = a->timer.state == LT_STOPPED ? LT_PAUSED : a->timer.state;
    lt_load(&a->timer, cur * 1000u, cur * 1000u, st, a->now_ms);
    log_offline(a, OEV_STEP_SPLIT, a->m.step_id, cur * 1000u);
    app_toast(a, "Cut in half. Just this part.");
    app_sync_timer_to_model(a);
}

static void start_listening(app_t *a)
{
    if (a->m.link != LINK_TETHERED) {
        app_toast(a, "Connect PC for Voice");
        return;
    }
    a->stream_id++;
    a->listen_start_ms = a->now_ms;
    a->m.listen_elapsed_s = 0;
    a->m.audio_level = 0;
    a->m.state = UI_STATE_LISTENING;
    /* the former reserved u16 carries the picked activity (0 brain dump, 1 calendar, 2 focus, 3 alarms) */
    pip_audio_start_t s = {a->stream_id, 16000, 1, 16, 60, ui_voice_choice_activity(a->m.voice_choice)};
    uint8_t b[12];
    app_send(a, PIP_AUDIO_START, true, b, (uint16_t)pip_pack_audio_start(&s, b));
    if (a->io.capture) {
        a->io.capture(a->io.ctx, true, a->stream_id);
    }
}

static void stop_listening(app_t *a, bool timeout)
{
    if (a->m.state != UI_STATE_LISTENING) {
        return;
    }
    if (a->io.capture) {
        a->io.capture(a->io.ctx, false, a->stream_id); /* adapter sends AUDIO_END with sample count */
    }
    (void)timeout;
    a->hands_free = false;
    a->m.state = UI_STATE_TRANSCRIBING;
}

bool app_voice_wake(app_t *a)
{
    ui_state_t st = a->m.state;
    bool ok = st == UI_STATE_IDLE_READY || st == UI_STATE_RUNNING || st == UI_STATE_PAUSED || st == UI_STATE_BREAK ||
              st == UI_STATE_STEP_DONE || st == UI_STATE_SLEEP || st == UI_STATE_VOICE_PICK;
    if (!ok) {
        return false;
    }
    if (a->m.link != LINK_TETHERED) {
        app_toast(a, "Connect PC for Voice");
        return false;
    }
    a->idle_since_ms = a->now_ms;
    if (st != UI_STATE_VOICE_PICK) {
        /* first wake word: open "What's it about?" exactly like holding KEY does */
        a->state_before_pick = st == UI_STATE_SLEEP ? UI_STATE_IDLE_READY : st;
        a->pick_since_ms = a->now_ms;
        a->m.state = UI_STATE_VOICE_PICK;
        mascot_react(&a->anim, PIP_REACT_PRESS, a->now_ms);
        if (a->io.chime) {
            a->io.chime(a->io.ctx, CHIME_CONFIRM);
        }
        a->dirty = true;
        return true;
    }
    /* wake word again while picking: talk hands-free about the highlighted activity */
    mascot_react(&a->anim, PIP_REACT_HOLD, a->now_ms);
    if (a->io.chime) {
        a->io.chime(a->io.ctx, CHIME_START);
    }
    start_listening(a);
    a->hands_free = a->m.state == UI_STATE_LISTENING;
    a->dirty = true;
    return true;
}

void app_voice_end(app_t *a)
{
    if (a->hands_free) {
        a->hands_free = false;
        stop_listening(a, false);
        a->dirty = true;
    }
}

static void react(app_t *a, const gesture_event_t *e)
{
    /* full-body reaction to every press: PIP turns, spins or leans in */
    pip_react_t r = PIP_REACT_NONE;
    if (a->m.state == UI_STATE_VOICE_PICK && e->btn == BTN_KEY && e->gesture == GEST_SHORT) {
        r = PIP_REACT_NEXT;
    } else if (e->gesture == GEST_SHORT) {
        r = e->btn == BTN_BOOT ? PIP_REACT_BACK : PIP_REACT_PRESS;
    } else if (e->gesture == GEST_DOUBLE) {
        r = PIP_REACT_DOUBLE;
    } else if (e->gesture == GEST_HOLD_START) {
        r = PIP_REACT_HOLD;
    }
    if (r != PIP_REACT_NONE) {
        mascot_react(&a->anim, r, a->now_ms);
    }
}

void app_on_gesture(app_t *a, const gesture_event_t *e)
{
    ui_state_t st = a->m.state;
    a->idle_since_ms = a->now_ms;
    a->dirty = true;
    react(a, e);
    if (st == UI_STATE_SLEEP) { /* any key wakes; the waking gesture is consumed */
        a->m.state = UI_STATE_IDLE_READY;
        return;
    }
    if (st == UI_STATE_ERROR_RECOVERABLE) { /* any click dismisses the error screen */
        if (e->gesture == GEST_SHORT || e->gesture == GEST_DOUBLE) {
            report(a, e); /* host clears its error too */
            a->m.state = a->timer.state == LT_RUNNING ? UI_STATE_RUNNING : UI_STATE_IDLE_READY;
            a->m.error_title[0] = a->m.error_text[0] = 0;
            a->error_local = false;
        }
        return;
    }
    if (st == UI_STATE_VOICE_PICK) { /* device-local picker: nothing is reported to the host */
        if (e->btn == BTN_KEY && e->gesture == GEST_SHORT) {
            a->m.voice_choice = (uint8_t)((a->m.voice_choice + 1u) % UI_VOICE_CHOICES);
            a->pick_since_ms = a->now_ms;
        } else if (e->btn == BTN_KEY && e->gesture == GEST_HOLD_START) {
            start_listening(a);
        } else if (e->btn == BTN_BOOT && e->gesture == GEST_SHORT) {
            a->m.state = a->state_before_pick; /* back */
        }
        return;
    }
    if (e->btn == BTN_KEY && e->gesture == GEST_HOLD_START && st != UI_STATE_ALARM_RINGING) {
        if (a->m.link != LINK_TETHERED) {
            app_toast(a, "Connect PC for Voice");
            return;
        }
        a->state_before_pick = st; /* hold KEY: first choose what the message is about */
        a->pick_since_ms = a->now_ms;
        a->m.state = UI_STATE_VOICE_PICK;
        return;
    }
    if (e->btn == BTN_KEY && e->gesture == GEST_HOLD_END) {
        stop_listening(a, (e->flags & GEST_FLAG_TIMEOUT) != 0); /* no-op unless recording */
        return;
    }
    report(a, e);
    if (st == UI_STATE_ALARM_RINGING) {
        if (e->btn == BTN_KEY && e->gesture == GEST_SHORT) {
            end_alarm(a, true);
        } else if (e->gesture != GEST_HOLD_END) {
            end_alarm(a, false);
        }
        return;
    }
    if (e->btn == BTN_KEY) {
        switch (e->gesture) {
        case GEST_SHORT:
            if (st == UI_STATE_NEEDS_CONFIRMATION) {
                a->m.state = a->m.has_active_step ? UI_STATE_PAUSED : UI_STATE_IDLE_READY;
            } else if (st == UI_STATE_STEP_DONE) {
                start_next_step(a);
            } else {
                toggle_timer(a);
            }
            break;
        case GEST_DOUBLE: a->m.page = a->m.page == PAGE_FOCUS ? PAGE_AGENDA : PAGE_FOCUS; break;
        default: break;
        }
        return;
    }
    if (e->gesture == GEST_RESCUE) {
        rescue_split(a);
        return;
    }
    if (e->gesture != GEST_SHORT) {
        return;
    }
    if (a->m.page == PAGE_AGENDA) {
        a->m.page = PAGE_FOCUS;
    } else if (st == UI_STATE_NEEDS_CONFIRMATION) {
        a->m.state = a->m.has_active_step ? UI_STATE_PAUSED : UI_STATE_IDLE_READY;
        chime(a, CHIME_CONFIRM);
    } else if (st == UI_STATE_STEP_DONE) {
        lt_load(&a->brk, APP_BREAK_MS, APP_BREAK_MS, LT_RUNNING, a->now_ms);
        a->m.break_remaining_ms = APP_BREAK_MS;
        a->m.state = UI_STATE_BREAK;
    } else if (st == UI_STATE_BREAK) {
        lt_stop(&a->brk);
        a->m.state = a->m.has_active_step ? UI_STATE_PAUSED : UI_STATE_IDLE_READY;
    } else if (a->m.has_active_step && (st == UI_STATE_RUNNING || st == UI_STATE_PAUSED || st == UI_STATE_IDLE_READY)) {
        complete_step(a);
    }
}

void app_button_sample(app_t *a, btn_id_t btn, bool pressed, uint32_t now_ms)
{
    gesture_event_t ev[4];
    a->now_ms = now_ms;
    int n = gestures_update(&a->gest, btn, pressed, now_ms, ev, 4);
    for (int i = 0; i < n; i++) {
        app_on_gesture(a, &ev[i]);
    }
}
